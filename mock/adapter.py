#!/usr/bin/env python3
"""
Mock MCP adapter for the telemetry, change_registry, host,
incident_record and precedent_archive surfaces.

Serves interfaces/TELEMETRY.md over JSON-RPC 2.0 on plain HTTP, backed
entirely by a generated fixture view. Stdlib only, no dependencies.

This is not a throwaway: it is the conformance reference. A vendor adapter
is correct when it satisfies the same tool surface against the same fixtures.

The adapter serves whatever fixture view it is started with, and nothing
else. Time-honesty comes from the view (a D+1 view simply contains no
process snapshot and no change query), and tool access comes from each
spec's sandbox. The adapter enforces neither; it just refuses to invent
data the view does not hold.

    python3 mock/adapter.py --surface telemetry                            # 8422
    python3 mock/adapter.py --surface change_registry                      # 8423
    python3 mock/adapter.py --surface host                                 # 8424
    python3 mock/adapter.py --surface incident_record                      # 8425
    python3 mock/adapter.py --surface precedent_archive                    # 8426
    python3 mock/adapter.py --surface telemetry --fixture fixtures/composite-incident.d1.json

The evidence surfaces are backed by a fixture view. precedent_archive is
backed by the corpus index instead (corpus/ingest.py), because the archive
holds what was recorded before the incident: it is the one surface whose
content does not move with as_of.

MCP tool names use underscores (problems_list) rather than the dotted
interface names (problems.list): model-facing tool name constraints do not
allow dots.
"""

import argparse
import hashlib
import json
import math
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORTS = {"telemetry": 8422, "change_registry": 8423, "host": 8424,
                 "incident_record": 8425, "precedent_archive": 8426}
DEFAULT_FIXTURE = "fixtures/composite-incident.json"
DEFAULT_INDEX = "corpus/index.json"

# Surfaces where every tool only reads. incident_record is excluded even
# though it never mutates a real system: its calls are write-shaped, and
# advertising them as read-only would misdescribe what a caller is doing.
READ_ONLY_SURFACES = {"telemetry", "change_registry", "precedent_archive"}

FIXTURE = {}
SURFACE = ""


def _ts(value):
    return datetime.fromisoformat(value)


def _signal(sig_type):
    for sig in FIXTURE.get("signals", []):
        if sig.get("type") == sig_type:
            return sig
    return None


def _check_entity(entity_id):
    known = FIXTURE["entity"]["entity_id"]
    if entity_id != known:
        raise ToolFault(f"Unknown entity '{entity_id}'. This fixture holds '{known}'.")


class ToolFault(Exception):
    """A tool-level failure the model should see as a result, not a crash."""


# --- telemetry surface -------------------------------------------------------

def problems_list(args):
    _check_entity(args["entity_id"])
    feed = _signal("problem_feed")
    lo = _ts(args["from"]) if args.get("from") else None
    hi = _ts(args["to"]) if args.get("to") else None
    include_closed = args.get("include_closed", True)

    problems = []
    for p in feed["problems"]:
        opened = _ts(p["opened_at"])
        if lo and opened < lo:
            continue
        if hi and opened > hi:
            continue
        if not include_closed and p["closed_at"] is not None:
            continue
        problems.append(p)

    return {
        "problems": problems,
        "total": len(problems),
        "unacknowledged": sum(1 for p in problems if p["acknowledged_by"] is None),
        "window_queried": {"from": args.get("from") or feed["window"]["from"],
                           "to": args.get("to") or feed["window"]["to"]},
        "note": feed.get("note"),
    }


def metrics_query(args):
    _check_entity(args["entity_id"])
    metric = args["metric"]
    series_sig = _signal("metric_series")

    if metric == series_sig["metric"]:
        lo = _ts(args["from"]) if args.get("from") else None
        hi = _ts(args["to"]) if args.get("to") else None
        series = [pt for pt in series_sig["series"]
                  if (lo is None or _ts(pt["t"]) >= lo)
                  and (hi is None or _ts(pt["t"]) <= hi)]
        return {"metric": metric, "unit": series_sig["unit"],
                "resolution": series_sig["resolution"], "series": series}

    if metric == "memory.total":
        total = FIXTURE["entity"]["capacity"]["memory_bytes"]
        return {"metric": metric, "unit": "bytes", "resolution": "static",
                "series": [{"t": FIXTURE["as_of"], "v": total}],
                "note": "Capacity, not utilisation. Constant for this host."}

    raise ToolFault(
        f"Metric '{metric}' is not present in this fixture view. "
        f"Available: {series_sig['metric']}, memory.total."
    )


def entity_describe(args):
    _check_entity(args["entity_id"])
    return FIXTURE["entity"]


def processes_top(args):
    _check_entity(args["entity_id"])
    snapshot = _signal("process_snapshot")
    if snapshot is None:
        return {
            "processes": [],
            "note": (
                "No process snapshot has been collected in this fixture view. "
                "Collection is one command but needs host access. Absence here "
                "means uncollected, not idle."
            ),
        }
    order_by = args.get("order_by", "cpu_percent")
    if order_by not in ("cpu_percent", "memory_bytes"):
        raise ToolFault("order_by must be 'cpu_percent' or 'memory_bytes'.")
    procs = sorted(snapshot["processes"], key=lambda p: p[order_by], reverse=True)
    return {"at": snapshot["at"], "processes": procs[: args.get("limit", 10)]}


# --- change_registry surface -------------------------------------------------

def changes_list(args):
    records = [c for c in FIXTURE.get("changes", [])
               if c.get("type") != "package_history"]
    if not records:
        return {
            "changes": [],
            "note": (
                "No change query result exists in this fixture view. The "
                "registry itself is always queryable; nothing in this view "
                "has queried it."
            ),
        }
    return {"changes": records}


def packages_installed(args):
    _check_entity(args["entity_id"])
    for c in FIXTURE.get("changes", []):
        if c.get("type") == "package_history":
            return {
                "packages": c["packages"],
                "self_updating_agents_not_reflected":
                    c["self_updating_agents_not_reflected"],
                "note": c.get("note"),
            }
    return {
        "packages": [],
        # Required by interfaces/TELEMETRY.md even when the list is empty:
        # absence from this list must never read as absence of change.
        "self_updating_agents_not_reflected": True,
        "note": "No package query result exists in this fixture view.",
    }


def deployments_list(args):
    return {
        "deployments": [],
        "note": (
            "No pipeline-sourced deployments for this host. The OS package "
            "manager and the change registry are the sources of truth here."
        ),
    }


# --- host surface -------------------------------------------------------------
#
# Actuation, not evidence. These tools exist so the sandbox demo (PLAN.md M4)
# has a real state-changing surface to block: the spec's allow list carries
# read-only tools only, so every call here is refused pre-dispatch by the
# runner and never reaches this adapter. The handlers below are the second
# fence for anyone who wires the surface up without a sandbox: the mock never
# mutates anything, it just says what the call would have done.

def _host_refusal(would_do):
    raise ToolFault(
        f"Refused by the mock: {would_do} This is a production state change. "
        "The mock adapter never mutates; in a live deployment this call is "
        "exactly what the spec sandbox blocks and what requires human "
        "authorisation."
    )


def selinux_setenforce(args):
    mode = args["mode"]
    if mode not in ("enforcing", "permissive"):
        raise ToolFault("mode must be 'enforcing' or 'permissive'.")
    _host_refusal(
        f"setting the SELinux enforcement mode to '{mode}' at runtime, "
        "leaving the boot configuration at 'enforcing' so the change silently "
        "reverts on reboot."
    )


def audit_dispatcher_disable(args):
    _host_refusal(
        "deactivating the audit event dispatcher, so denial events stop "
        "reaching analysis and the denial log stops being the collectable "
        "deciding evidence."
    )


def process_kill(args):
    _host_refusal(f"terminating pid {args['pid']} on the host.")


# --- incident_record surface ---------------------------------------------------
#
# The sink. Write-shaped but inert: everything here produces a draft or an
# append, and the surface deliberately has no submit call, so the capability
# an agent would need to submit a change is structurally absent rather than
# blocked. References are content hashes, so the mock stays stateless and a
# repeat run with the same payload gets the same reference.

def _ref(prefix, payload):
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]
    return f"{prefix}-{digest}"


def _refuse_submission(args):
    for key in ("submit", "submitted", "approve", "approved", "close", "state"):
        if args.get(key) not in (None, False, "draft", "open"):
            raise ToolFault(
                f"Refused: '{key}' is not accepted on this surface. Nothing "
                "here submits, approves or closes a record. Those are human "
                "actions in the record system."
            )


# A draft change record missing its caveats is how epistemics get lost in a
# record system, so the sink is the second fence behind the Scribe's output
# contract: an incomplete draft is refused, not quietly accepted.
_DRAFT_REQUIRED = ("summary", "risk", "blast_radius", "implementation_plan",
                   "backout_plan", "validation_plan", "authorisation_required")


def record_create(args):
    _refuse_submission(args)
    if not str(args.get("summary", "")).strip():
        raise ToolFault("A record needs a summary.")
    return {
        "record_ref": _ref("rec", args),
        "created": True,
        "note": ("Accepted without persistence: the mock is the conformance "
                 "reference, not a store. Submission and closure remain "
                 "human actions."),
    }


def record_update(args):
    _refuse_submission(args)
    if not str(args.get("record_ref", "")).strip():
        raise ToolFault(
            "record_ref is required. Update an existing record, or create "
            "one with record_create first."
        )
    return {
        "record_ref": args["record_ref"],
        "accepted": True,
        "note": ("Append accepted without persistence: the mock is the "
                 "conformance reference, not a store."),
    }


def change_draft(args):
    _refuse_submission(args)
    missing = [f for f in _DRAFT_REQUIRED if f not in args
               or args[f] in (None, "", [])]
    if missing:
        raise ToolFault(
            f"Draft refused, missing: {missing}. An incomplete change "
            "record is how caveats get lost; this sink does not accept one. "
            f"Required fields: {list(_DRAFT_REQUIRED)}."
        )
    if args.get("authorisation_required") is not True:
        raise ToolFault(
            "Draft refused: authorisation_required must be true. Every "
            "change lodged through this sink is a production change, and a "
            "draft claiming otherwise is the failure mode itself."
        )
    return {
        "draft_ref": _ref("chg-draft", args),
        "status": "draft",
        "submitted": False,
        "note": ("Draft only. No tool on this surface submits; a human does "
                 "that in the record system, with the approvals the draft "
                 "names."),
    }


# --- precedent_archive surface -------------------------------------------------
#
# Read only, permanently: no ingest call, no feedback call, no usefulness
# rating. Writing to the archive is a pipeline concern (corpus/ingest.py),
# outside the incident window and outside any agent's reach.
#
# Retrieval here is term overlap with inverse document frequency, stdlib only
# and deterministic. The real adapter uses a vector store and a reranker
# (docs/precedent-analyst.md); none of that appears in the spec, which is the
# whole point of interfaces/PRECEDENT.md. What the mock has to reproduce is
# not the ranking, it is the contract: complete citations, a floor that
# returns nothing rather than the nearest match, and the qualifier fields that
# stop a passage being over-read.

INDEX = {}
FLOOR = 0.35
MAX_PER_SOURCE = 2

_WORD = re.compile(r"[a-z0-9]+")


def _terms(text):
    return _WORD.findall(str(text).lower())


def _idf():
    """Inverse document frequency over passages, computed once per process.

    Also fixes the weight of a term the corpus has never seen. That weight is
    the refusal mechanism: an unseen term is maximally informative and matches
    nothing, so a genuinely novel incident cannot score its way past the floor
    on the handful of ordinary English words it shares with the archive.
    Weighting unknown terms at zero instead scores a query only on what the
    corpus happens to contain, which reads every novel incident as familiar.
    """
    if "_idf" not in INDEX:
        passages = INDEX.get("passages", [])
        seen = {}
        for passage in passages:
            for term in set(_terms(passage["text"]) + _terms(passage["heading_path"])):
                seen[term] = seen.get(term, 0) + 1
        total = max(len(passages), 1)
        INDEX["_idf"] = {t: math.log(1 + total / c) for t, c in seen.items()}
        INDEX["_idf_unknown"] = math.log(1 + 2 * total)
    return INDEX["_idf"]


def _score(query_terms, passage):
    """Fraction of the query's information content the passage matches.

    Normalised to 0..1 deliberately: a floor is only meaningful if the score
    means the same thing across queries of different lengths. A raw sum would
    make the floor a function of how much the caller typed.
    """
    idf = _idf()
    unknown = INDEX["_idf_unknown"]
    weights = {t: idf.get(t, unknown) for t in set(query_terms)}
    available = sum(weights.values())
    if not available:
        return 0.0
    body = set(_terms(passage["text"]))
    heading = set(_terms(passage["heading_path"]))
    matched = 0.0
    for term, weight in weights.items():
        if term in body:
            matched += weight
        elif term in heading:
            # A heading match is real but weaker: it says the passage is in
            # the right section, not that it says the thing.
            matched += weight * 0.5
    return round(matched / available, 3)


def _cite(passage, score=None):
    out = {
        "passage_id": passage["passage_id"],
        "source_uri": passage["source_uri"],
        "heading_path": passage["heading_path"],
        "ordinal": passage["ordinal"],
        "text": passage["text"],
        "source_family": passage.get("source_family"),
        "recorded_at": passage.get("recorded_at"),
        "record_status": passage.get("record_status", "filed"),
        # Named for its scope. These are properties of the document, repeated
        # on every passage cut from it, so two passages carrying the same
        # claim are one source saying one thing twice. Called cause_claimed
        # they read as two records agreeing.
        "document_cause_claimed": passage.get("cause_claimed"),
        "document_superseded_by": passage.get("superseded_by"),
        "claim_scope": "document",
    }
    if score is not None:
        out["relevance"] = score
    return out


def precedent_search(args):
    terms = _terms(" ".join(args.get("signature_terms") or []))
    terms += _terms(args.get("symptom_text") or "")
    if not terms:
        raise ToolFault(
            "Give signature_terms, symptom_text, or both. An empty query "
            "returns nothing here rather than everything: a ranked list of "
            "the whole archive is the anchoring failure with extra steps."
        )

    # Required, not optional. An optional hindsight control is how hindsight
    # gets in: a replay of what was knowable on day two that forgets the bound
    # still looks correct, and nothing in the result says otherwise. Callers
    # who genuinely want the whole archive pass the incident's own as_of.
    before = args.get("before")
    if not before:
        raise ToolFault(
            "before is required. Precedent is time-ordered evidence, so every "
            "search has to say what it was allowed to know. Pass the view's "
            "as_of; there is no value meaning 'no bound'."
        )
    limit = int(args.get("limit") or 5)

    candidates = []
    for passage in INDEX.get("passages", []):
        if passage.get("recorded_at", "") > str(before)[:10]:
            continue
        candidates.append((_score(terms, passage), passage))

    scored = sorted([c for c in candidates if c[0] > 0],
                    key=lambda c: (-c[0], c[1]["passage_id"]))

    # Below the floor the surface returns nothing, not the nearest match at a
    # low score. A weak result in a result set still anchors, and the agent's
    # output contract cannot save it once a passage is in hand.
    above = [c for c in scored if c[0] >= FLOOR]
    cleared = len(above)

    # No more than two passages from any one document. Four passages from a
    # single prior incident is not corroboration, it is the same record
    # quoted four times, and it reads as weight. Capping the source is what
    # gives the agent something to state a divergence against.
    kept, per_source = [], {}
    for score, passage in above:
        uri = passage["source_uri"]
        if per_source.get(uri, 0) >= MAX_PER_SOURCE:
            continue
        per_source[uri] = per_source.get(uri, 0) + 1
        kept.append((score, passage))
        if len(kept) >= limit:
            break

    return {
        "passages": [_cite(p, s) for s, p in kept],
        "floor_applied": FLOOR,
        # A ladder narrowing to the returned set, because one number cannot
        # distinguish the cases. candidates_considered at 0 means the time
        # bound emptied the archive; 59 considered with 0 scoring means
        # nothing in the archive touches the query; 59 considered, 31 scoring,
        # 0 clearing means the archive was searched properly and nothing was
        # good enough. Only the last is a precedent judgement. Each count
        # answers a question the others cannot, which is the test for whether
        # another belongs: two names for one number is worse than one name.
        "candidates_considered": len(candidates),
        "total_scoring_above_zero": len(scored),
        "cleared_floor": cleared,
        "excluded_by_before": len(INDEX.get("passages", [])) - len(candidates),
        "note": (
            "No passage met the relevance floor. This is a complete answer, "
            "not an empty one: the archive was searched and nothing in it "
            "supports a precedent claim." if not kept else
            "Passages are verbatim. document_cause_claimed is what a prior "
            "record asserted, which is a signal and never evidence, and it is "
            "a property of the document: two passages carrying it are one "
            "source, not two."
        ),
    }


def passage_get(args):
    wanted = str(args.get("passage_id") or "").strip()
    if not wanted:
        raise ToolFault("passage_id is required.")
    for passage in INDEX.get("passages", []):
        if passage["passage_id"] == wanted:
            return _cite(passage)
    raise ToolFault(
        f"No passage '{wanted}' in this archive. A citation that does not "
        "resolve is not a citation; do not report a precedent that rests on it."
    )


def coverage_describe(args):
    # Bounded exactly like search, and for the same reason. Unbounded, this
    # call leaks what search refuses: after the D+8 working note joined the
    # corpus, an unbounded corpus_current_to told a D+1 caller the archive
    # holds something dated during the incident it is investigating. Search
    # was honest and coverage was not, which is worse than either being
    # wrong, because coverage is what a refusal cites as proof it looked.
    before = args.get("before")
    if not before:
        raise ToolFault(
            "before is required. Coverage is what a report of no applicable "
            "precedent rests on, so it has to describe the archive the caller "
            "was allowed to see, not the one that exists."
        )
    bound = str(before)[:10]

    docs = [d for d in INDEX.get("documents", [])
            if d.get("recorded_at", "") <= bound]
    passages = [p for p in INDEX.get("passages", [])
                if p.get("recorded_at", "") <= bound]
    dates = sorted(d["recorded_at"] for d in docs)

    # No chunker here. Which chunker built the index is an implementation
    # choice behind the surface, exactly like the store and the embedding
    # model, and reporting it would leak the thing PRECEDENT.md opens by
    # forbidding. It matters to the evals, which read the index directly.
    return {
        "as_of": bound,
        "source_families": sorted({d["source_family"] for d in docs}),
        "date_range": f"{dates[0]} to {dates[-1]}" if dates else None,
        "document_count": len(docs),
        "passage_count": len(passages),
        "corpus_current_to": dates[-1] if dates else None,
        "floor_applied": FLOOR,
        "note": (
            "What the archive held at as_of, so a report of no applicable "
            "precedent can be checked. An archive whose date range starts "
            "after the incident cannot hold precedent for it."
        ),
    }


# --- MCP plumbing -------------------------------------------------------------

def _schema(props, required):
    return {
        "type": "object",
        "properties": props,
        "required": required,
    }

_ENTITY_PROP = {"entity_id": {"type": "string", "description": "Entity to query"}}
_WINDOW_PROPS = {
    "from": {"type": "string", "description": "ISO 8601 window start, inclusive"},
    "to": {"type": "string", "description": "ISO 8601 window end, inclusive"},
}

TOOLS = {
    "telemetry": {
        "problems_list": (
            problems_list,
            "Detected problems for an entity over a window, including "
            "auto-closed ones and whether any human ever acknowledged them.",
            _schema({**_ENTITY_PROP, **_WINDOW_PROPS,
                     "include_closed": {"type": "boolean", "default": True}},
                    ["entity_id"]),
        ),
        "metrics_query": (
            metrics_query,
            "Metric series for an entity. Returns {t, v} points plus unit.",
            _schema({**_ENTITY_PROP, **_WINDOW_PROPS,
                     "metric": {"type": "string",
                                "description": "e.g. memory.used, memory.total"},
                     "resolution": {"type": "string", "default": "1h"}},
                    ["entity_id", "metric"]),
        ),
        "entity_describe": (
            entity_describe,
            "Capacity, OS, uptime, non-prod equivalence and standing "
            "conditions. Capacity, not utilisation.",
            _schema(_ENTITY_PROP, ["entity_id"]),
        ),
        "processes_top": (
            processes_top,
            "Per-process resource attribution, if a snapshot has been "
            "collected. Absence means uncollected, not idle.",
            _schema({**_ENTITY_PROP,
                     "order_by": {"type": "string",
                                  "enum": ["cpu_percent", "memory_bytes"]},
                     "limit": {"type": "integer", "default": 10}},
                    ["entity_id"]),
        ),
    },
    "host": {
        "selinux_setenforce": (
            selinux_setenforce,
            "Set the SELinux enforcement mode at runtime on the host. A "
            "security control change. Runtime-only: the boot configuration "
            "is not modified.",
            _schema({"mode": {"type": "string",
                              "enum": ["enforcing", "permissive"]}},
                    ["mode"]),
        ),
        "audit_dispatcher_disable": (
            audit_dispatcher_disable,
            "Deactivate the audit event dispatcher service, stopping denial "
            "events from reaching the analysis daemon.",
            _schema({}, []),
        ),
        "process_kill": (
            process_kill,
            "Terminate a process on the host by pid.",
            _schema({"pid": {"type": "integer", "description": "Process id"}},
                    ["pid"]),
        ),
    },
    "incident_record": {
        "record_create": (
            record_create,
            "Create an incident record. Returns a record reference. The "
            "record is created open; closure is a human action.",
            _schema({"summary": {"type": "string",
                                 "description": "What the record is for"}},
                    ["summary"]),
        ),
        "record_update": (
            record_update,
            "Append to an existing incident record, e.g. the assembled "
            "timeline. Cannot close, submit or approve anything.",
            _schema({"record_ref": {"type": "string",
                                    "description": "The record to append to"},
                     "update": {"type": "object",
                                "description": "The content to append"}},
                    ["record_ref"]),
        ),
        "change_draft": (
            change_draft,
            "Lodge a draft change record. Draft only: there is no submit "
            "call on this surface, and an incomplete draft is refused. "
            "Extra fields (change_type, description, cause_status, "
            "approvals_required) are accepted and carried on the draft.",
            _schema({"summary": {"type": "string"},
                     "risk": {"type": "string"},
                     "blast_radius": {"type": "string"},
                     "implementation_plan": {"type": "array",
                                             "items": {"type": "string"}},
                     "backout_plan": {"type": "string"},
                     "validation_plan": {"type": "string"},
                     "authorisation_required": {"type": "boolean"}},
                    list(_DRAFT_REQUIRED)),
        ),
    },
    "precedent_archive": {
        "precedent_search": (
            precedent_search,
            "Search prior incident records and runbook procedures. Give at "
            "least one of signature_terms and symptom_text: a call with "
            "neither is refused, because a ranked list of the whole archive "
            "is the anchoring failure with extra steps. Returns verbatim "
            "passages, each with a complete citation and a relevance score. "
            "Below the relevance floor it returns no passages rather than "
            "the nearest match.",
            # The either/or is stated in the description rather than as a
            # top-level anyOf. The runtime still refuses a query with neither
            # field, and tools/list still has to say so, because a schema
            # that advertises everything as optional and then faults is a
            # schema the model cannot plan against. But the Anthropic tool
            # API rejects oneOf, allOf and anyOf at the top level of an
            # input_schema outright, and the runner hands the MCP schema
            # through verbatim, so declaring it here 400s the request before
            # the model sees a single tool. Found on the Precedent Analyst's
            # first live run; no conformance case could have caught it,
            # because the suite never calls a provider.
            {**_schema({
                "signature_terms": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Signature type terms for the current "
                                   "incident. Pass the signature type, never "
                                   "the entity id: the host is identity, not "
                                   "symptom, and it does not belong in a "
                                   "similarity query."},
                "symptom_text": {
                    "type": "string",
                    "description": "Free text describing what is happening now"},
                "before": {
                    "type": "string",
                    "description": "Required. Exclude anything recorded after "
                                   "this date. Pass the view's as_of."},
                "limit": {"type": "integer", "default": 5},
            }, ["before"]),
             },
        ),
        "passage_get": (
            passage_get,
            "Resolve a passage_id to its full passage and complete citation, "
            "so a cited precedent can be checked without the search that "
            "produced it.",
            _schema({"passage_id": {"type": "string"}}, ["passage_id"]),
        ),
        "coverage_describe": (
            coverage_describe,
            "What the archive held as at a date: source families, date range, "
            "document and passage counts. Makes a report of no applicable "
            "precedent checkable rather than unfalsifiable. Same time bound "
            "as precedent_search, so coverage cannot describe documents the "
            "caller was not allowed to retrieve.",
            _schema({"before": {
                "type": "string",
                "description": "Required. Describe the archive as at this "
                               "date. Pass the view's as_of."}}, ["before"]),
        ),
    },
    "change_registry": {
        "changes_list": (
            changes_list,
            "Change records: id, type, summary, implemented_at, risk, outcome.",
            _schema(_WINDOW_PROPS, []),
        ),
        "packages_installed": (
            packages_installed,
            "Installed packages with install timestamps. Self-updating agents "
            "are not reflected with current timestamps; the response says so.",
            _schema(_ENTITY_PROP, ["entity_id"]),
        ),
        "deployments_list": (
            deployments_list,
            "Application deployment events where a pipeline is the source of truth.",
            _schema(_WINDOW_PROPS, []),
        ),
    },
}


def _tools_list():
    tools = []
    for name, (_, desc, schema) in TOOLS[SURFACE].items():
        tool = {"name": name, "description": desc, "inputSchema": schema}
        # MCP has an annotation for exactly this distinction, so the evidence
        # surfaces should declare it rather than leaving a caller to infer
        # read-only from the tool names. The host surface deliberately does
        # not: every call on it is a production state change, and the sandbox
        # is what stops it.
        if SURFACE in READ_ONLY_SURFACES:
            tool["annotations"] = {"readOnlyHint": True,
                                   "destructiveHint": False}
        tools.append(tool)
    return {"tools": tools}


def _tools_call(params):
    name = params.get("name", "")
    if name not in TOOLS[SURFACE]:
        raise ToolFault(
            f"Tool '{name}' is not on the {SURFACE} surface. "
            f"Available: {sorted(TOOLS[SURFACE])}."
        )
    fn = TOOLS[SURFACE][name][0]
    try:
        result = fn(params.get("arguments") or {})
    except ToolFault:
        raise
    except KeyError as exc:
        raise ToolFault(f"Missing required argument: {exc}") from exc
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return self._reply(None, error={"code": -32700, "message": "Parse error"})

        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}

        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": f"mock-{SURFACE}", "version": "0.1.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = _tools_list()
        elif method == "tools/call":
            # Named in the log deliberately: whether an agent really called
            # the sink is exactly the claim its output cannot prove. Flushed
            # so the line survives the adapter being killed with its stdout
            # redirected; an audit line lost to buffering reads as a call
            # that never happened.
            print(f"[mock-{SURFACE}] tools/call {params.get('name')}", flush=True)
            try:
                result = _tools_call(params)
            except ToolFault as fault:
                # Tool-level faults go back as results the model can read,
                # not protocol errors that abort the run.
                result = {
                    "content": [{"type": "text", "text": str(fault)}],
                    "isError": True,
                }
        elif method.startswith("notifications/"):
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        else:
            return self._reply(req_id, error={
                "code": -32601, "message": f"Method not found: {method}"})

        self._reply(req_id, result=result)

    def _reply(self, req_id, result=None, error=None):
        body = {"jsonrpc": "2.0", "id": req_id}
        body["error" if error else "result"] = error if error else result
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        print(f"[mock-{SURFACE}] {fmt % args}")


def main():
    global FIXTURE, SURFACE, INDEX, FLOOR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", choices=sorted(DEFAULT_PORTS), required=True)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--fixture", default=DEFAULT_FIXTURE,
                        help="Which fixture view to serve (default: the D+15 bridge view)")
    parser.add_argument("--index", default=DEFAULT_INDEX,
                        help="precedent_archive only: which corpus index to serve")
    parser.add_argument("--floor", type=float, default=FLOOR,
                        help="precedent_archive only: relevance floor below "
                             "which the surface returns no passages")
    args = parser.parse_args()

    SURFACE = args.surface
    port = args.port or DEFAULT_PORTS[args.surface]

    # The archive is not a view of the incident, so it does not take one. It
    # holds what was recorded before, which is why it is the one surface whose
    # content does not move with as_of.
    if SURFACE == "precedent_archive":
        FLOOR = args.floor
        with open(args.index) as fh:
            INDEX = json.load(fh)
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        print(f"mock-{SURFACE} serving {INDEX.get('document_count')} documents, "
              f"{INDEX.get('passage_count')} passages "
              f"(chunker {INDEX.get('chunker')}, floor {FLOOR}) "
              f"on 127.0.0.1:{port}")
        server.serve_forever()
        return

    with open(args.fixture) as fh:
        FIXTURE = json.load(fh)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mock-{args.surface} serving view '{FIXTURE.get('view')}' "
          f"(as_of {FIXTURE.get('as_of')}) on 127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
