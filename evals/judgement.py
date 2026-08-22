#!/usr/bin/env python3
"""
Judgement measurement for the Precedent Analyst.

    python3 evals/runner.py --mode judgement --config evals/config.judgement.yaml
    python3 evals/judgement.py --config evals/config.judgement.yaml --arm shipped

The other half of evals/runner.py. Retrieval mode measures the surface with
no model in the loop and costs nothing to re-run. This mode measures the
agent: one live `oa run` per case, an API key, and the patches/ provider
patch, because a stock install 400s the moment the model calls a tool.

What that buys, and it is the reason the split exists rather than a cost
inconvenience. Retrieval mode cannot see a false precedent, a refusal, or a
citation, because none of those are properties of the surface. They are
properties of what the agent did with what the surface handed it.

Three rules this file is built on, all of them learned the expensive way
elsewhere in this repo:

  An output cannot attest to its own tool use. The runner does not bind tool
  results into outputs, so a passage_id in a citation is a string the model
  wrote either way. Every claim about what was retrieved is read from the
  adapter's audit log, never from the output. That is what makes
  groundedness_log a measurement rather than a restatement.

  The agent is scored on the queries it issued, not on the dataset's
  canonical probe. That probe exists to measure the surface. Case a04's is
  the reported symptom used whole, which clears the floor zero times: an
  agent that copies it retrieves nothing and refuses, and the archive held
  precedent, so the refusal is a real false refusal rather than an artefact.

  A run from this mode is not a regenerable artefact. Two sweeps of the same
  arm differ, so nothing diffs a fresh sweep against a committed one, and the
  record carries a timestamp, the spec and prompt it ran, the runtime and the
  model, because those are what a reader would otherwise take on trust. What
  is derived from a record is regenerable and is treated like every other
  generated file here: --comparison rebuilds the per-arm tables and the Phase 5
  grid from the records, and CI diffs them. Those are also what --check-records reads back: it asks
  whether a recording still describes the configuration on disk, which is a
  different question from whether it would come back the same.

Deterministic and judged metrics are reported apart, always. false_precedent_
rate, no_precedent_accuracy, false_refusal_rate and groundedness_log are read
off the typed output and the adapter log by code: they are as reliable as the
ground truth. groundedness_judge and divergence_quality are a model's opinion
of a model, scored with the prompt committed beside this file and whatever
sampling the transport can pin, which the record states rather than assumes.
Mixing them into one table would launder the second as the first. Their level
is judge-relative and measured to be so: on the shipped arm the same claims
score 38 of 52 under one judge family and 17 of 52 under another, while the
ordering between arms survives both.

Stdlib plus PyYAML, like runner.py and validate.py. The judge calls the
Messages API over raw HTTP rather than through the anthropic SDK, so that
this directory keeps the dependency footprint it documents; the agent runs
through `oa`, which brings its own.
"""

import argparse
import concurrent.futures
import hashlib
import inspect
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runner import (  # noqa: E402
    DATASET, RESULTS, check_corpus_pin, dataset_fingerprint, file_fingerprint,
    pct, rpc, start_adapter,
)
from validate import (  # noqa: E402
    fingerprint as fingerprint_corpus, load_corpus,
)

API_URL = "https://api.anthropic.com/v1/messages"
args_config_path = "evals/config.judgement.yaml"
_RUNTIME = None
API_VERSION = "2023-06-01"

# The paragraph of the spec's system prompt the query-strategy arm replaces,
# located by its first line and terminated by the next rule. Anchored on the
# spec's own text rather than duplicated here: an arm that differs from the
# shipped prompt in ways nobody listed is not an experiment, it is two
# prompts. If the spec's wording moves, the derivation fails loudly instead
# of silently generating an arm that no longer isolates one rule.
RULE_ANCHOR = "4. Query the distinctive terms, and query more than once."
RULE_NEXT = "5. State the divergence or do not offer the precedent."

# What the guidance would have been without the measurement behind it: one
# search, carrying the whole reported symptom. Written as an instruction a
# competent author would write, not as sabotage. The point of the arm is
# whether the shipped rule is worth its words, so the alternative has to be
# the plausible thing it replaced.
SINGLE_QUERY_RULE = """\
4. Issue one search, carrying the reported symptom in full. Put the
   symptom into the query as it was reported, so that nothing the incident
   is showing is left out of what you ask for. One search over the whole
   description is enough: there is no need to decompose the symptom into
   separate behaviours, and no need to search again on terms the
   description already contains. Record the query you issued in
   queries_issued.
"""


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def load_config(path):
    with open(path) as handle:
        config = yaml.safe_load(handle) or {}
    for key in ("spec", "task", "arms", "judge"):
        if key not in config:
            raise SystemExit(f"{path} is missing {key}")
    return config


def pick_arm(config, label):
    arms = config["arms"]
    if label is None:
        return arms[0]
    for arm in arms:
        if arm["label"] == label:
            return arm
    names = ", ".join(a["label"] for a in arms)
    raise SystemExit(f"no arm {label!r}. Arms in this config: {names}")


def spec_document(path):
    with open(path) as handle:
        return yaml.safe_load(handle)


def spec_port(spec, path):
    """The port the spec's tool binding names, not one this runner picks.

    Retrieval mode chooses its own port because it is the caller. Here the
    caller is `oa`, which dials whatever the spec declares, so a port
    argument would only ever produce a run against an adapter the agent
    could not reach.
    """
    endpoint = spec["tools"]["precedent_archive"]["endpoint"]
    port = urllib.parse.urlparse(endpoint).port
    if not port:
        raise SystemExit(f"{path} declares endpoint {endpoint!r} with no port")
    return port


def system_prompt_for(spec, arm):
    """The system prompt this arm runs, and where it came from.

    A --system-prompt override replaces the whole prompt rather than editing
    it, which the Phase 3 stripped-prompt work settled: a stripped run is not
    a plain run minus one rule. So the override arm's file is generated from
    the spec's prompt with one paragraph substituted, and --check-prompts
    fails when the spec moves underneath it.

    The delivery path is equivalent, and that was read rather than assumed:
    oas_cli/runner.py `_resolve_prompts` assigns `system = override_system`
    at exactly the point it would otherwise take the spec's, and only the
    user template is placeholder-substituted. So an arm that overrides the
    system prompt differs from one that does not in the text and in nothing
    else. Worth checking again after a CLI upgrade: if that ever stops being
    true, the guidance arm's delta stops being about the paragraph.
    """
    if not arm.get("system_prompt"):
        return spec["prompts"]["system"], "spec", None
    path = arm["system_prompt"]
    with open(path) as handle:
        text = handle.read()
    return text, path, file_fingerprint(path)


# --------------------------------------------------------------------------
# The query-strategy arm's prompt, derived from the spec
# --------------------------------------------------------------------------

def derive_single_query_prompt(spec):
    text = spec["prompts"]["system"]
    start = text.find(RULE_ANCHOR)
    end = text.find(RULE_NEXT)
    if start == -1 or end == -1 or end < start:
        raise SystemExit(
            "cannot locate rule 4 in the spec's system prompt. The arm is "
            "defined as the shipped prompt with exactly that paragraph "
            "replaced, so a wording change there has to be re-read rather "
            "than regenerated around: fix RULE_ANCHOR/RULE_NEXT in "
            "evals/judgement.py once you have.")
    return text[:start] + SINGLE_QUERY_RULE + "\n" + text[end:]


def write_prompts(config, check):
    spec = spec_document(config["spec"])
    failures = 0
    for arm in config["arms"]:
        path = arm.get("system_prompt")
        if not path or arm.get("derive") != "single_query":
            continue
        derived = derive_single_query_prompt(spec)
        current = open(path).read() if os.path.exists(path) else None
        if check:
            if current == derived:
                print(f"{path} is current")
            else:
                failures += 1
                print(f"{path} does not match a fresh derivation from "
                      f"{config['spec']}. The arm is only an experiment while "
                      f"it differs from the shipped prompt in one paragraph. "
                      f"Regenerate it:\n"
                      f"  python3 evals/judgement.py --config "
                      f"evals/config.judgement.yaml --write-prompts")
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(derived)
        print(f"wrote {path}")
    return 1 if failures else 0


# --------------------------------------------------------------------------
# Preconditions
# --------------------------------------------------------------------------

def require_contracts():
    """Fail closed on the degradation that exits 0.

    The runner skips contract validation with only a warning when the
    behavioural-contracts extra is missing, which a pipx upgrade drops. A
    sweep measured with contracts silently off is a sweep of a different
    harness, and every rate in it would be quietly better.
    """
    oa = shutil.which("oa")
    if not oa:
        raise SystemExit("oa is not on the path. Judgement mode runs the "
                         "agent: pip install 'open-agent-spec[contracts]'.")
    with open(oa) as handle:
        shebang = handle.readline().strip()
    interpreter = shebang[2:].strip() if shebang.startswith("#!") else None
    if not interpreter or not os.access(interpreter, os.X_OK):
        # Fails closed, unlike the governance demos, and for a different
        # reason: a demo that cannot verify this still shows a boundary
        # working, while a sweep that cannot verify it produces rates measured
        # against a harness nobody established. Every one of them would be
        # quietly better than the harness this repo ships.
        raise SystemExit(
            f"cannot resolve oa's interpreter from {oa}, so whether contract "
            f"validation is enabled is unknown. A sweep measured with "
            f"contracts silently off is a sweep of a different harness: "
            f"install oa with the contracts extra where its shebang names a "
            f"real interpreter, or run the sweep from that environment.")
    probe = subprocess.run(
        [interpreter, "-c", "import sys; from oas_cli.runner import "
         "CONTRACTS_ENABLED; sys.exit(0 if CONTRACTS_ENABLED else 1)"],
        capture_output=True)
    if probe.returncode != 0:
        raise SystemExit(
            "behavioural-contracts is missing from oa's environment, so the "
            "runner would skip contract validation with a warning and every "
            "rate below would be measured against a harness that is not the "
            "one this repo ships. Reinstall it:\n"
            "  pipx runpip open-agent-spec install behavioural-contracts")
    return oa


# --------------------------------------------------------------------------
# One case, live
# --------------------------------------------------------------------------

def agent_runtime(oa):
    """What actually ran the agent, by version and by content.

    The CLI version alone is not enough here. Tool calling needs the provider
    patch in patches/, which edits an installed file in place, so two installs
    reporting the same version can behave differently: one 400s the moment the
    model calls a tool and the other does not. The provider module is
    fingerprinted for that reason. Sol asked for this at the gate, and the
    reason it blocks a claim rather than a run is that an arm recorded before
    an upgrade and one recorded after would otherwise compare as differing in
    one input.
    """
    with open(oa) as handle:
        shebang = handle.readline().strip()
    interpreter = shebang[2:].strip() if shebang.startswith("#!") else None
    probe = subprocess.run(
        [interpreter or sys.executable, "-c",
         "import importlib.metadata as m, hashlib, json\n"
         "import oas_cli.providers.anthropic_http as provider\n"
         "print(json.dumps({\n"
         "  'cli_version': m.version('open-agent-spec'),\n"
         "  'provider_module': provider.__file__,\n"
         "  'provider_fingerprint': hashlib.sha256(\n"
         "      open(provider.__file__, 'rb').read()).hexdigest(),\n"
         "}))"],
        capture_output=True, text=True)
    if probe.returncode != 0:
        raise SystemExit(
            f"cannot establish what would run the agent: {probe.stderr[-300:]}"
            f"\nA sweep that cannot say which CLI and which provider produced "
            f"it cannot support a one-input comparison.")
    runtime = json.loads(probe.stdout)
    runtime["oa"] = oa
    runtime["interpreter"] = interpreter
    return runtime


def case_input(case):
    """The recall task's input, built from the case.

    signals carries the signature with its entity id attached, as the real
    signals do, because the agent is required to strip it before querying and
    handing it a pre-stripped type would test nothing. evidence and
    missing_evidence are objects rather than strings for the same reason the
    fixture's are: the task's input schema types them as objects, and the
    runner substitutes what it is given.
    """
    return {
        "as_of": case["as_of"],
        "symptom": case["symptom"].strip(),
        "signals": [{
            "source": "problem_feed",
            "type": "signature",
            "signature": case["signature"],
            "observed_at": case["as_of"],
        }],
        "evidence": [{"description": item.strip()}
                     for item in case.get("evidence") or []],
        "missing_evidence": [{"description": item.strip(),
                              "still_outstanding": True}
                             for item in case.get("missing_evidence") or []],
    }


def log_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, errors="replace") as handle:
        return handle.readlines()


def parse_log(lines):
    """What the surface actually did, by id and uri.

    hits is the set the agent was given. Every citation is checked against
    this and never against the output's own word.
    """
    text = "".join(lines)
    hits = dict(re.findall(r"^\[mock-precedent_archive\] hit (\S+) (\S+)$",
                           text, re.M))

    # Which call each passage came back from. The adapter logs a call line and
    # then the passages that left the surface on it, so the attribution is the
    # log's order rather than an inference. It matters because a passage the
    # agent fetched by id to check a citation is not a passage its queries
    # found, and agent_reach is a claim about what the queries reached. Sol
    # found the two collapsed into one set at the gate.
    by_call, current = {}, None
    for line in lines:
        call = re.match(r"^\[mock-precedent_archive\] tools/call (\S+)$",
                        line.strip())
        if call:
            current = call.group(1)
            continue
        hit = re.match(r"^\[mock-precedent_archive\] hit (\S+) (\S+)$",
                       line.strip())
        if hit and current:
            by_call.setdefault(current, {})[hit.group(1)] = hit.group(2)
    calls = re.findall(r"^\[mock-precedent_archive\] tools/call (\S+)$",
                       text, re.M)
    # What the agent asked for, from the surface's own record of it. The
    # output's queries_issued is the agent's account of the same thing, and
    # the identity rule is exactly the sort of rule an account gets wrong in
    # its own favour.
    asked = []
    for name, blob in re.findall(
            r"^\[mock-precedent_archive\] args (\S+) (.*)$", text, re.M):
        try:
            asked.append({"tool": name, "arguments": json.loads(blob)})
        except json.JSONDecodeError:
            asked.append({"tool": name, "arguments": None, "raw": blob})
    searches = re.findall(
        r"^\[mock-precedent_archive\] returned (\d+) passages of (\d+) above "
        r"floor \((\d+) considered, (\d+) scoring\)$", text, re.M)
    return {
        "hits": hits,
        "hits_by_tool": by_call,
        "calls": calls,
        "asked": asked,
        "searches": [{"returned": int(a), "above_floor": int(b),
                      "considered": int(c), "scoring": int(d)}
                     for a, b, c, d in searches],
    }


def run_case(oa, config, case, log_path, system_prompt, timeout):
    """One live recall, and everything measurable about it that is not the
    model's opinion."""
    mark = len(log_lines(log_path))
    command = [oa, "run", "--spec", config["spec"], "--task", config["task"],
               "--input", json.dumps(case_input(case)), "--quiet"]
    if system_prompt is not None:
        command += ["--system-prompt", system_prompt]

    started = time.perf_counter()
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout)
        stdout, stderr, status = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr, status = "", f"timed out after {timeout}s", -1
    elapsed = (time.perf_counter() - started) * 1000

    surface = parse_log(log_lines(log_path)[mark:])
    record = {
        "case": case["id"],
        "group": case["group"],
        "elapsed_ms": round(elapsed, 1),
        "exit_status": status,
        "surface": surface,
        "output": None,
        "failure": None,
    }
    if status != 0:
        # A rejection is a result, not a crash: the contract refusing an
        # output is the harness working. It is reported as its own row rather
        # than folded into a rate, because an agent that produced nothing
        # usable neither offered a false precedent nor refused.
        record["failure"] = {
            "kind": "rejected" if re.search(r"(SCHEMA|CONTRACT)", stderr)
            else "run_failed",
            "detail": stderr.strip()[-600:],
        }
        return record
    try:
        record["output"] = json.loads(stdout)
    except json.JSONDecodeError as exc:
        # The runner exits 0 on a json task whose output does not parse, with
        # schema and contract validation skipped. Counting that as anything
        # other than a failure would score a truncated run as a refusal.
        record["failure"] = {"kind": "unparseable",
                             "detail": f"{exc}: {stdout.strip()[:300]}"}
    return record


# --------------------------------------------------------------------------
# Deterministic scoring
# --------------------------------------------------------------------------

def offered_claim(precedent):
    """The claim as the agent wrote it, minus the citation block.

    Its own function because the judge fingerprint hashes it. Hashing the
    whole of score_run instead meant that adding a deterministic check, the
    time bound for instance, demanded a paid re-judge for a change the judge
    could not see. What the judge is asked is this shape and nothing else in
    that function.
    """
    return {key: value for key, value in precedent.items()
            if key not in ("incident_ref", "grounded_in")}


def cited_ids(precedent):
    """Every passage id this claim rests on, each counted once.

    incident_ref.passage_id is normally also in grounded_in, which is the
    contract's ordinary shape, so appending it produced a denominator no
    reader could tally from the output: one cited id read as 2/2. The rate
    was unaffected, both copies being in the log or neither, and a
    denominator that cannot be checked is worth fixing anyway.
    """
    ref = precedent.get("incident_ref") or {}
    ids = list(precedent.get("grounded_in") or [])
    if ref.get("passage_id") and ref["passage_id"] not in ids:
        ids.append(ref["passage_id"])
    return ids


def score_run(case, record):
    """Everything code can settle about one run.

    Kept separate from the judged scores on purpose. Every number here is a
    consequence of the typed output, the adapter log and the ground truth,
    and a reader can check any of it from the record beside this table.
    """
    expect = case["expect"]
    truth = expect.get("applicability") or {}
    relevant = set(expect.get("relevant") or [])
    hits = record["surface"]["hits"]
    # Everything the surface returned, by whatever call. Used for citation
    # membership, where the question is only whether the agent was ever handed
    # the passage it cites.
    searched = (record["surface"].get("hits_by_tool") or {}).get(
        "precedent_search", {})
    # Reach is a claim about the queries the agent chose, so it counts only
    # what came back from precedent_search.
    reached = {uri.split("#")[0] for uri in searched.values()}

    out = {
        "precedent_exists": bool(expect["precedent_exists"]),
        "refused": None,
        "claims": [],
        "citations": {"total": 0, "in_returned_set": 0, "invented": []},
        "must_not_cite_violations": [],
        "citation_identity_violations": [],
        "cross_document_citations": [],
        "time_bound_violations": [],
        "query_hygiene_violations": [],
        "queries_issued": [],
        # A coverage call made with the wrong bound establishes coverage of a
        # different archive, so it does not settle the question this field
        # exists for.
        "coverage_called": any(
            ask["tool"] == "coverage_describe"
            and (ask["arguments"] or {}).get("before") == case["as_of"]
            for ask in record["surface"]["asked"]),
        "searches": len([c for c in record["surface"]["calls"]
                         if c == "precedent_search"]),
        "reach": {"relevant": len(relevant),
                  "reached": len(relevant & reached),
                  "missed": sorted(relevant - reached)},
        # The failure every rate below is blind to. A document the ground
        # truth says applies here, which the archive handed the agent, and
        # which never reached the board: no claim was offered on it, so
        # false_precedent_rate sees nothing, understated sees nothing, and
        # agent_reach counts it as reached because the surface did return it.
        # The case answers, so it is not a refusal either.
        "applies_retrieved": sorted(uri for uri, verdict in truth.items()
                                    if verdict == "applies" and uri in reached),
        "applies_offered": [],
    }
    if record["failure"]:
        return out

    output = record["output"] or {}
    out["refused"] = bool(output.get("no_applicable_precedent"))
    coverage = output.get("search_coverage") or {}
    queries = [q for q in (coverage.get("queries_issued") or [])
               if isinstance(q, str)]
    out["queries_issued"] = queries

    # From the log, not from queries_issued. The dataset's rule is about what
    # the agent asked the archive, and the output is the agent's account of
    # that: a run that put the entity id in a query and reported it stripped
    # would pass a check read off its own report. The self-report is still
    # scored, as its own line, because a refusal that cannot say what it
    # searched is the unfalsifiable one.
    searched = [ask for ask in record["surface"]["asked"]
                if ask["tool"] == "precedent_search"]
    out["queries_searched"] = [ask["arguments"] for ask in searched]
    for banned in expect.get("queries_must_not_contain") or []:
        for ask in searched:
            blob = json.dumps(ask["arguments"] or {})
            if banned.lower() in blob.lower():
                out["query_hygiene_violations"].append(
                    {"banned": banned, "arguments": ask["arguments"],
                     "seen_in": "the adapter log"})
        for query in queries:
            if banned.lower() in query.lower():
                out["query_hygiene_violations"].append(
                    {"banned": banned, "query": query,
                     "seen_in": "queries_issued"})
    # The bound, on every call that takes one. This is the archive's hindsight
    # boundary: the corpus carries a working note dated inside the incident's
    # own window, and the only thing keeping it out of a D+1 view is `before`.
    # Nothing checked it. A run that searched with a later bound, or none,
    # could retrieve a record written after the view and still score clean,
    # which would hollow out the demo the same way an unbounded query does.
    # Read from the log, because the bound the agent reports is not evidence.
    for ask in record["surface"]["asked"]:
        if ask["tool"] not in ("precedent_search", "coverage_describe"):
            continue
        bound = (ask["arguments"] or {}).get("before")
        if bound != case["as_of"]:
            out["time_bound_violations"].append(
                {"tool": ask["tool"], "before": bound,
                 "as_of": case["as_of"]})

    out["queries_reported_but_not_issued"] = (
        len(queries) - len(searched) if len(queries) > len(searched) else 0)

    for precedent in output.get("precedents") or []:
        ref = precedent.get("incident_ref") or {}
        claimed_uri = ref.get("source_uri") or ""
        ids = cited_ids(precedent)

        # Which document this claim is really about, according to the
        # archive rather than according to the claim. hits maps a returned
        # passage id to the uri it came from, so a claim naming INC-2411
        # while citing a passage of INC-2419 is visible here and was not
        # before: groundedness_log asks only whether a cited id was
        # returned, and the truth lookup used the model's own source_uri, so
        # such a claim was scored against the applicability of a document it
        # had not cited. Sol found it at the gate.
        anchor = ref.get("passage_id")
        resolved = (hits.get(anchor, "").split("#")[0] if anchor else "")
        elsewhere = sorted({hits[i].split("#")[0] for i in ids if i in hits}
                           - {claimed_uri})
        # Two different things, kept apart. A claim whose own citation comes
        # from a document it does not name is misnamed, and that is the hole
        # groundedness_log cannot see. A claim that also rests on passages
        # from other documents is doing what the contract allows, a precedent
        # supported by a record and the procedure that covers it, and
        # counting it as a violation would be a check inflating its own
        # findings.
        if bool(resolved) and resolved != claimed_uri:
            out["citation_identity_violations"].append({
                "named": claimed_uri,
                "incident_ref_resolves_to": resolved,
            })
        if elsewhere:
            out["cross_document_citations"].append({
                "named": claimed_uri,
                "also_rests_on": elsewhere,
            })

        # Truth is looked up against the document the archive says the
        # citation came from, falling back to the claimed uri only when the
        # anchor was never returned, which groundedness_log already counts.
        uri = resolved or claimed_uri
        offered = precedent.get("applicability")
        expected = truth.get(uri)
        grounded = [i for i in ids if i in hits]
        invented = [i for i in ids if i not in hits]
        out["citations"]["total"] += len(ids)
        out["citations"]["in_returned_set"] += len(grounded)
        out["citations"]["invented"] += invented
        if uri in (expect.get("must_not_cite") or []):
            out["must_not_cite_violations"].append(uri)
        out["claims"].append({
            "source_uri": uri,
            "offered": offered,
            "truth": expected,
            # The headline. Offering `applies` where the record diverges, was
            # superseded, or is not precedent for this incident at all, is
            # the anchoring failure the whole agent is built against. An
            # over-cautious `partial` on a document that does apply is a
            # different and much cheaper mistake, counted separately.
            "false_precedent": offered == "applies" and expected != "applies",
            "understated": offered != "applies" and expected == "applies",
            "unrelated": expected is None,
            "confidence": precedent.get("confidence"),
            "divergence": (precedent.get("divergence") or "").strip(),
            "grounded_in": ids,
            "ungrounded": invented,
            # The claim as the agent wrote it. The scored fields above are a
            # reading of it; the judge gets the thing itself.
            "offered_claim": offered_claim(precedent),
        })
    out["applies_offered"] = sorted(
        {c["source_uri"] for c in out["claims"]}
        & set(out["applies_retrieved"]))
    return out


def aggregate(cases, records, scores):
    by_id = {c["id"]: c for c in cases}
    answerable = [r for r in records if scores[r["case"]]["precedent_exists"]]
    novel = [r for r in records if not scores[r["case"]]["precedent_exists"]]
    usable = [r for r in records if not r["failure"]]
    failed = [r for r in records if r["failure"]]

    claims = [claim for r in usable for claim in scores[r["case"]]["claims"]]
    false_claims = [c for c in claims if c["false_precedent"]]

    refused_answerable = [r for r in answerable
                          if not r["failure"] and scores[r["case"]]["refused"]]
    correct_refusals = [r for r in novel
                        if not r["failure"] and scores[r["case"]]["refused"]]
    novel_usable = [r for r in novel if not r["failure"]]
    answerable_usable = [r for r in answerable if not r["failure"]]

    citations = sum(scores[r["case"]]["citations"]["total"] for r in usable)
    grounded = sum(scores[r["case"]]["citations"]["in_returned_set"]
                   for r in usable)

    pairs = sum(scores[r["case"]]["reach"]["relevant"] for r in usable
                if scores[r["case"]]["precedent_exists"])
    reached = sum(scores[r["case"]]["reach"]["reached"] for r in usable
                  if scores[r["case"]]["precedent_exists"])

    omitted = [f"{r['case']}:{uri}" for r in usable
               for uri in scores[r["case"]]["applies_retrieved"]
               if uri not in scores[r["case"]]["applies_offered"]]
    applies_pairs = sum(len(scores[r["case"]]["applies_retrieved"])
                        for r in usable)
    offered_words = {}
    for claim in claims:
        offered_words[claim["offered"]] = offered_words.get(
            claim["offered"], 0) + 1

    latencies = sorted(r["elapsed_ms"] for r in records)
    return {
        "cases": len(records),
        "failures": {
            "total": len(failed),
            "by_kind": {kind: sum(1 for r in failed
                                  if r["failure"]["kind"] == kind)
                        for kind in sorted({r["failure"]["kind"]
                                            for r in failed})},
            "cases": [{"case": r["case"], "kind": r["failure"]["kind"],
                       "detail": r["failure"]["detail"]} for r in failed],
        },
        "false_precedent_rate": {
            "value": round(len(false_claims) / len(claims), 4) if claims
            else None,
            "numerator": len(false_claims),
            "denominator": len(claims),
            "unit": "precedent claims offered across every scored case",
            "offending": [{"case": r["case"], "document": c["source_uri"],
                           "offered": c["offered"], "truth": c["truth"]}
                          for r in usable
                          for c in scores[r["case"]]["claims"]
                          if c["false_precedent"]],
        },
        # Read this one before the rate above it. false_precedent_rate can
        # only fire on a claim the agent made; this fires on one it did not.
        # A document the archive handed over, which the ground truth says
        # applies here, and which never reached the board, is the anchoring
        # failure's quiet twin: nothing was overclaimed and the responder
        # still did not get the thing that applies.
        "applies_omission_rate": {
            "value": round(len(omitted) / applies_pairs, 4)
            if applies_pairs else None,
            "numerator": len(omitted),
            "denominator": applies_pairs,
            "unit": "(case, document) pairs whose ground truth is `applies` "
                    "and which the surface returned to the agent, counted "
                    "when no precedent was offered on them at all",
            "omitted": omitted,
        },
        # The distribution the headline rate depends on, printed because a
        # rate of zero over a word nobody used is not a result. Sol and Grok
        # both have to be able to see this without opening the record.
        "applicability_offered": offered_words,
        "no_precedent_accuracy": {
            "value": round(len(correct_refusals) / len(novel_usable), 4)
            if novel_usable else None,
            "numerator": len(correct_refusals),
            "denominator": len(novel_usable),
            "unit": "cases where no applicable precedent exists",
            "missed": [r["case"] for r in novel_usable
                       if not scores[r["case"]]["refused"]],
        },
        "false_refusal_rate": {
            "value": round(len(refused_answerable) / len(answerable_usable), 4)
            if answerable_usable else None,
            "numerator": len(refused_answerable),
            "denominator": len(answerable_usable),
            "unit": "cases where the archive held applicable precedent",
            "refused": [r["case"] for r in refused_answerable],
        },
        "groundedness_log": {
            "value": round(grounded / citations, 4) if citations else None,
            "numerator": grounded,
            "denominator": citations,
            "unit": "cited passage ids, checked against the adapter's "
                    "returned set",
            "invented": [{"case": r["case"],
                          "ids": scores[r["case"]]["citations"]["invented"]}
                         for r in usable
                         if scores[r["case"]]["citations"]["invented"]],
        },
        "agent_reach": {
            "value": round(reached / pairs, 4) if pairs else None,
            "numerator": reached,
            "denominator": pairs,
            "unit": "(case, relevant document) pairs the archive returned to "
                    "the agent across the queries it chose",
        },
        "understated_claims": {
            "count": len([c for c in claims if c["understated"]]),
            "of": len(claims),
            "unit": "precedent claims offered as `partial` or `superseded` "
                    "where the ground truth says the document applies. The "
                    "cheap direction of the same error, counted so that a "
                    "false precedent rate of zero cannot be read as a "
                    "calibrated agent when it is a uniformly cautious one.",
            "claims": sorted({f"{r['case']}:{c['source_uri']}"
                              for r in usable
                              for c in scores[r["case"]]["claims"]
                              if c["understated"]}),
        },
        # Read beside groundedness_log, which cannot see this: every id in a
        # misnamed claim was returned by the surface, so the citation check
        # passes while the claim is about a document it did not cite.
        "citation_identity": {
            "claims": len(claims),
            "misnamed": [
                {"case": r["case"], **entry}
                for r in usable
                for entry in scores[r["case"]]["citation_identity_violations"]],
            "cross_document": [
                {"case": r["case"], **entry}
                for r in usable
                for entry in scores[r["case"]]["cross_document_citations"]],
            "unit": "misnamed: claims whose own incident_ref passage came "
                    "from a document other than the one the claim names, "
                    "resolved through the adapter log. cross_document: claims "
                    "that also rest on passages from other documents, which "
                    "the contract permits and which are reported, not scored.",
        },
        "unrelated_claims": {
            "count": len([c for c in claims if c["unrelated"]]),
            "of": len(claims),
            "unit": "precedent claims on documents this case's ground truth "
                    "does not call relevant. Not a rate: relevance is judged "
                    "sharply, so offering an unlisted document as `partial` "
                    "is a softer error than offering a diverging one as "
                    "`applies`, and it is reported rather than scored.",
            "claims": sorted({f"{r['case']}:{c['source_uri']}"
                              for r in usable
                              for c in scores[r["case"]]["claims"]
                              if c["unrelated"]}),
        },
        "hygiene": {
            "identity_in_queries": [
                {"case": r["case"],
                 "violations": scores[r["case"]]["query_hygiene_violations"]}
                for r in usable
                if scores[r["case"]]["query_hygiene_violations"]],
            # With the applicability each one was offered under, because
            # that is the whole question. A draft named in prose as
            # unusable, and typed as `partial` anyway, has put the caveat
            # somewhere the contract does not carry it.
            "must_not_cite": [
                {"case": r["case"],
                 "documents": scores[r["case"]]["must_not_cite_violations"],
                 "offered": [c["offered"] for c in scores[r["case"]]["claims"]
                             if c["source_uri"] in
                             scores[r["case"]]["must_not_cite_violations"]]}
                for r in usable
                if scores[r["case"]]["must_not_cite_violations"]],
            "wrong_time_bound": [
                {"case": r["case"],
                 "calls": scores[r["case"]]["time_bound_violations"]}
                for r in usable
                if scores[r["case"]]["time_bound_violations"]],
            "refused_without_coverage": [
                r["case"] for r in usable
                if scores[r["case"]]["refused"]
                and not scores[r["case"]]["coverage_called"]],
            "self_report_overstated": [
                {"case": r["case"],
                 "reported": len(scores[r["case"]]["queries_issued"]),
                 "issued": len(scores[r["case"]]["queries_searched"])}
                for r in usable
                if scores[r["case"]]["queries_reported_but_not_issued"]],
            "queries_per_case": {
                "median": round(statistics.median(
                    [len(scores[r["case"]]["queries_searched"])
                     for r in usable]), 1) if usable else None,
                "issued": sum(len(scores[r["case"]]["queries_searched"])
                              for r in usable),
                "reported": sum(len(scores[r["case"]]["queries_issued"])
                                for r in usable),
            },
        },
        "latency_ms": {
            "calls": len(latencies),
            "p50": round(statistics.median(latencies), 1) if latencies
            else None,
            "p95": round(latencies[max(0, -(-len(latencies) * 95 // 100) - 1)],
                         1) if latencies else None,
            "note": "wall clock per `oa run`, provider time included. It is "
                    "the agent's latency, not the surface's: retrieval mode "
                    "measures the surface and the two are not comparable.",
        },
        "groups": sorted({by_id[r["case"]]["group"] for r in records}),
    }


# --------------------------------------------------------------------------
# The judge
# --------------------------------------------------------------------------

def judge_code_fingerprint(transport="anthropic"):
    """The code that decides what a judge is asked and how its reply is read.

    Narrow on purpose. A fingerprint over this whole file would be simpler and
    would demand a paid re-judge for a comment, which is how a check that
    costs money gets switched off. What actually determines a verdict is the
    payload built for it, the request that carries it, the parse that reads it
    back, and the claim shape it is handed. The prompts, the model and the
    temperature are fingerprinted separately in the record.
    """
    # score_run is here because judge_run builds its task list from the claims
    # score_run produces: which claims are judged at all, and the divergence
    # filter, come from it. It was removed once to stop a deterministic check
    # like the time bound from demanding a paid re-judge, and that traded the
    # fingerprint's correctness for its convenience. The honest version
    # over-triggers; the way out is to extract claim construction into its own
    # function rather than to hash less than the payload depends on.
    functions = [judge_run, call_judge, extract_json, offered_claim,
                 cited_ids, score_run, rpc]
    # The isolation code determines a verdict only where the judge has file
    # tools. Hashing it for a metered round made an edit to the jail invalidate
    # rounds it could not possibly have touched, and the remedy for that is
    # paid. Transport-aware, so each round is pinned to the code that could
    # have changed it.
    if transport == "cursor":
        functions += [judge_via_cursor, judge_jail, verify_jail,
                      repo_checkouts]
    source = "".join(inspect.getsource(fn) for fn in functions)
    # Values, not only code. The endpoint and the API version shape every
    # request, and rpc is what resolves a cited passage to the text the judge
    # is shown. Hashing the functions alone left all three able to move
    # without the record noticing.
    return hashlib.sha256(
        (source + API_URL + API_VERSION).encode()).hexdigest()


def repo_checkouts(repo_root):
    """Every checkout of this repository, not just the one running.

    A worktree masks its own path and leaves the primary checkout, and any
    sibling worktree, holding the same corpus at a different path. The review
    that found this ran in a worktree while /home/.../response-engineering sat
    readable beside it. git knows where they all are, so ask git.

    This still masks paths rather than content: a copy of the corpus outside
    any checkout git knows about is not covered, and nothing here can cover
    it. The transport with no file tools is the only version of this that is
    structural, and the record says so.
    """
    paths = {repo_root}
    listing = subprocess.run(
        ["git", "-C", repo_root, "worktree", "list", "--porcelain"],
        capture_output=True, text=True)
    if listing.returncode != 0:
        # Failing open here masks one checkout, and the probe then repeats the
        # same short list and passes, so an alternate checkout holding the
        # corpus stays readable while isolation reports clean. The whole point
        # of the probe is that it cannot be satisfied by the thing it checks.
        raise SystemExit(
            f"cannot enumerate this repository's checkouts, so the corpus "
            f"cannot be shown absent from all of them: "
            f"{listing.stderr.strip()[:200]}")
    for line in listing.stdout.splitlines():
        if line.startswith("worktree "):
            paths.add(line.split(" ", 1)[1].strip())
    return sorted(paths)


def judge_jail(repo_root):
    """A mount namespace with nothing to read, or a refusal.

    The threat is specific: the CLI judge is a general-purpose agent with file
    tools, and it is asked whether a claim is supported by the passages it
    cites. Given this repository it can open the document those passages came
    from and answer from that instead, which is a different question with the
    same shape.

    --mode ask does not close it: ask mode forbids writes, not reads. An empty
    --workspace does not close it either, and neither does a different cwd:
    absolute paths still resolve. Both were claimed as locks here and a probe
    showed the judge reading corpus/documents through them.

    What closes the obvious path is not having the files. An empty tmpfs over
    the repository root inside a private mount namespace means the corpus is
    absent rather than forbidden, which is the same reason a sandbox allow
    list names tools rather than asking the model not to call them.

    Be exact about how much that buys, because it is less than a sandbox. It
    masks one pathname. It does not build a new root, and a determined reader
    could still find the same bytes through another mount of the same
    filesystem or through /proc. The judge is a model answering a question,
    not an adversary looking for a way around, so masking the path it would
    otherwise take is a proportionate control and not a containment boundary.
    The structural version of this is the metered transport, which has no file
    tools at all: if the groundedness figure has to be unimpeachable rather
    than cheap, judge through that.

    Returns the command prefix, or raises when the namespace cannot be made:
    a judge that could read the corpus is not a judge this metric can use, and
    the metered transport needs none of this because it has no tools at all.
    """
    probe = subprocess.run(["unshare", "--map-root-user", "--mount", "true"],
                           capture_output=True)
    if probe.returncode != 0:
        raise SystemExit(
            "cannot create a mount namespace on this host, so the CLI judge "
            "would run with read access to the corpus it is scoring claims "
            "against. Judge through transport: anthropic instead, which has "
            "no file tools at all, or run where unshare works.\n"
            f"  unshare said: {probe.stderr.decode(errors='replace')[:200]}")
    wrapper = tempfile.NamedTemporaryFile(
        "w", suffix=".sh", prefix="judge-jail-", delete=False)
    # /proc is remounted, not just the repository masked. A new PID namespace
    # without it leaves the host's procfs in place, and /proc/<pid>/root/ is a
    # second door to every path the tmpfs hides. Sol found that at the gate.
    masks = "".join(
        f"mount -t tmpfs none {path} 2>/dev/null || exit 97\n"
        for path in repo_checkouts(repo_root))
    wrapper.write("#!/bin/bash\n" + masks
                  + "mount -t proc proc /proc 2>/dev/null || exit 96\n"
                  + 'exec "$@"\n')
    wrapper.close()
    os.chmod(wrapper.name, 0o700)
    # --pid --fork so the judge cannot walk /proc back to a process outside
    # the namespace and reach the filesystem through its root link. Cheap, and
    # it removes the most obvious route around the mask.
    return ["unshare", "--map-root-user", "--mount", "--pid", "--fork",
            wrapper.name]


def verify_jail(judge, prefix, repo_root):
    """Ask the judge to read a file it must not be able to read.

    One call, before any claim is scored. A boundary this file asserts and
    never tests is the kind of claim the rest of this repository refuses to
    make, and the record carries the answer so a reader does not have to take
    the comment above on trust.
    """
    target = os.path.join(repo_root, "corpus", "documents", "incidents",
                          "INC-2411.md")
    # A shell first, because a boundary checked by asking a model whether it
    # got through is a boundary checked by self-report. Both the masked path
    # and the /proc route into another process's root, inside the same
    # namespace the judge will run in.
    # Every checkout, by both routes. Testing only the one this process runs
    # from is what let a worktree pass while the primary checkout beside it
    # was readable.
    checks = "".join(
        f'cat {os.path.join(path, "corpus", "documents", "incidents", "INC-2411.md")}'
        f' >/dev/null 2>&1 && echo DIRECT_OK; '
        f'cat /proc/*/root{os.path.join(path, "corpus")}/documents/incidents/'
        f'INC-2411.md >/dev/null 2>&1 && echo PROC_OK; '
        for path in repo_checkouts(repo_root))
    script = checks + "echo SHELL_DONE"
    shell = subprocess.run(prefix + ["bash", "-c", script],
                           capture_output=True, text=True, timeout=60)
    routes = shell.stdout.strip().replace("\n", " ")
    if "DIRECT_OK" in routes or "PROC_OK" in routes:
        raise SystemExit(
            f"the corpus is reachable from inside the namespace ({routes}), "
            f"so masking it did not work and nothing should be scored on it.")
    probe = subprocess.run(
        prefix + ["agent", "-p",
                  f"Use your file reading tool on the absolute path {target}. "
                  f"Reply with one word and nothing else: READ_OK if you "
                  f"read it, READ_FAILED if you could not. Do not explain.",
                  "--model", judge["model"], "--output-format", "json",
                  "--mode", "ask", "--trust"],
        capture_output=True, text=True, timeout=judge.get("timeout", 300))
    try:
        answer = (json.loads(probe.stdout).get("result") or "").upper()
    except (json.JSONDecodeError, AttributeError):
        answer = ""
    # Only an explicit failure passes. An answer with neither word in it
    # proves nothing, and reading "no READ_OK" as "cannot read" is how a probe
    # comes to certify a boundary it never tested: the first version of this
    # did exactly that and passed on a truncated preamble.
    blocked = "READ_FAILED" in answer and "READ_OK" not in answer
    if not blocked:
        raise SystemExit(
            "the jail probe did not come back with a clear refusal, so "
            "whether the judge can read the corpus it is scoring against is "
            "unestablished. Nothing is scored on that.\n"
            f"  probe answered: {answer.strip()[:200] or '(nothing)'}")
    return {"shell_probe": f"direct path and /proc/*/root refused in "
                          f"{len(repo_checkouts(repo_root))} checkout(s)",
            "checkouts_masked": repo_checkouts(repo_root),
            "shell_answer": routes,
            "model_probe": "read a corpus document by its usual path",
            "model_answer": answer.strip()[:120],
            "reachable": False,
            "scope": "two routes into every checkout git knows about. Not "
                     "every route and not every copy: a corpus outside those "
                     "checkouts is not masked and cannot be. This is a "
                     "control against a model taking an available path, not "
                     "a container, and the metered transport is the "
                     "structural version because it has no file tools."}


def cursor_version():
    """The CLI that judged, by version. Same reason the agent runtime is
    pinned: two installs behave differently and a record should not need a
    reader to assume which one ran."""
    probe = subprocess.run(["agent", "--version"], capture_output=True,
                           text=True)
    return probe.stdout.strip() or None


def judge_via_cursor(judge, system, payload):
    """Judge through the Cursor CLI, on the subscription rather than metered.

    Two things this has to get right, and the second is not about cost.

    The harness is an agent with file tools, and the judge's whole job is to
    answer from the passages it is handed. Given the repository it can open
    corpus/documents and confirm a claim from the document rather than from
    the citation, which is precisely the check being run. The empty workspace
    and read-only mode do not stop that: ask mode forbids writes, not reads,
    and an absolute path resolves regardless of the workspace. A probe showed
    exactly that. What stops it is judge_jail, the mount namespace, and the
    only structural version is the metered transport, which has no file tools
    at all.

    Sampling cannot be set here. The CLI takes a model and effort, not a
    temperature, so a run through this transport cannot claim temperature 0.
    That is a real reduction in what the harness pins, and the documents say
    so rather than carrying the old phrase. It costs less than it reads:
    four judgings at temperature 0 through the metered API moved two to four
    claims per arm, so the determinism the phrase implied was not there.
    """
    prompt = system + "\n\n" + json.dumps(payload, indent=2)
    prefix = judge["_jail"]
    with tempfile.TemporaryDirectory(prefix="judge-") as empty:
        proc = subprocess.run(
            # The model id carries its own effort on this family:
            # cursor-grok-4.6-high is the high-effort variant, and the
            # bracket override the CLI documents applies to parameterised
            # models only, which this is not. Appending one is rejected with
            # the full model list, so effort is pinned by choosing the id.
            prefix + ["agent", "-p", prompt, "--model", judge["model"],
                      "--output-format", "json", "--mode", "ask", "--trust",
                      "--workspace", empty],
            capture_output=True, text=True, timeout=judge.get("timeout", 300),
            cwd=empty)
    if proc.returncode != 0:
        return {"error": f"agent exited {proc.returncode}: "
                         f"{(proc.stderr or proc.stdout)[-300:]}"}, {}
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"agent output did not parse ({exc}): "
                         f"{proc.stdout[:200]}"}, {}
    if envelope.get("is_error"):
        return {"error": f"agent reported an error: {str(envelope)[:300]}"}, {}
    usage = envelope.get("usage") or {}
    verdict = extract_json(envelope.get("result", ""))
    if verdict is None:
        return {"error": "judge output did not parse: "
                         f"{str(envelope.get('result'))[:300]}"}, usage
    return verdict, usage


TRANSPORTS = ("anthropic", "cursor")


def call_judge(judge, system, payload, key):
    # A transport this file does not implement is a typo, and falling through
    # to the metered API for one produced plausible verdicts filed under a
    # name nothing supports: the record kept the misspelling and dropped the
    # sampling fields that transport pins. Refused instead.
    transport = judge.get("transport", "anthropic")
    if transport not in TRANSPORTS:
        raise SystemExit(
            f"judge transport {transport!r} is not one this runner "
            f"implements ({', '.join(TRANSPORTS)}). Nothing is judged on a "
            f"transport whose provenance cannot be recorded.")
    if transport == "cursor":
        return judge_via_cursor(judge, system, payload)
    body = json.dumps({
        "model": judge["model"],
        "max_tokens": judge.get("max_tokens", 1500),
        # Temperature 0 is what docs/precedent-analyst.md fixes, and it is why
        # the judge is pinned to a model that still accepts the parameter:
        # the current generation rejects it outright. A judge whose sampling
        # nobody set is not the check that was specified.
        "temperature": judge.get("temperature", 0),
        "system": system,
        "messages": [{"role": "user",
                      "content": json.dumps(payload, indent=2)}],
    }).encode()
    request = urllib.request.Request(API_URL, data=body, headers={
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": API_VERSION,
    })
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                reply = json.loads(response.read())
                break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            last = f"HTTP {exc.code}: {detail}"
            if exc.code not in (408, 409, 429, 500, 502, 503, 529):
                return {"error": last}, {}
        except (urllib.error.URLError, OSError) as exc:
            last = str(exc)
        time.sleep(2 ** attempt)
    else:
        return {"error": last}, {}

    text = "".join(block.get("text", "") for block in reply["content"]
                   if block.get("type") == "text").strip()
    usage = reply.get("usage", {})
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    verdict = extract_json(text)
    if verdict is None:
        # Recorded as an error rather than as a failed check. A judge whose
        # reply did not parse has said nothing about the claim, and scoring
        # it as unsupported would turn the judge's formatting into the
        # agent's mistake.
        return {"error": f"judge output did not parse: {text[:300]}"}, usage
    return verdict, usage


def extract_json(text):
    """The reply's JSON object, whether or not it arrived alone.

    The prompt asks for the object and nothing else, and mostly gets it. When
    it does not, the verdict is still in there behind a paragraph of working,
    and discarding it would lose a real judgement to a formatting slip. The
    scan is deliberately narrow: a balanced object, the last one in the
    reply, or nothing.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for start in range(len(text) - 1, -1, -1):
        if text[start] != "{":
            continue
        depth, in_string, escaped = 0, False, False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:index + 1])
                    except json.JSONDecodeError:
                        break
    return None


def judge_run(config, records, scores, cases, port, key):
    """The two metrics a model has to score, kept apart from the rest.

    groundedness_judge asks whether a precedent's claims are supported by the
    passages it cites, which the log check cannot: the log proves a cited
    passage was returned, not that it says what the claim says. Neither
    closes the section-level gap, because document-level ground truth cannot
    tell a citation of Resolution from one of Gaps.

    divergence_quality asks whether the stated difference is the one that
    actually distinguishes the two incidents, against the factors the dataset
    names. A near-miss case where the near miss was never offered is not
    scored: there is no divergence to judge, and counting it as a failure
    would fold a retrieval miss into a judgement metric.
    """
    judge = dict(config["judge"])
    isolation = None
    if judge.get("transport", "anthropic") == "cursor":
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        effort = judge.get("effort", "high")
        if not judge["model"].endswith(f"-{effort}"):
            raise SystemExit(
                f"the config declares effort {effort!r} and the model id is "
                f"{judge['model']!r}, which does not carry it. This transport "
                f"has no effort flag: the id is the control, so the two have "
                f"to agree or the config is describing an input nobody set.")
        judge["_jail"] = judge_jail(repo_root)
        isolation = verify_jail(judge, judge["_jail"], repo_root)
        isolation["namespace"] = f"tmpfs over {repo_root}"
    with open(judge["groundedness_prompt"]) as handle:
        grounding_system = handle.read()
    with open(judge["divergence_prompt"]) as handle:
        divergence_system = handle.read()
    by_id = {c["id"]: c for c in cases}

    verdicts = {"groundedness": [], "divergence": []}
    usage_total = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def account(usage):
        # The two transports name these differently: the Messages API returns
        # input_tokens, the CLI envelope returns inputTokens. Reading one
        # spelling recorded zeros for the other and made a real cost look free.
        usage_total["calls"] += 1
        usage_total["input_tokens"] += (usage.get("input_tokens")
                                        or usage.get("inputTokens") or 0)
        usage_total["output_tokens"] += (usage.get("output_tokens")
                                         or usage.get("outputTokens") or 0)
        for extra in ("cacheReadTokens", "cacheWriteTokens"):
            if usage.get(extra):
                usage_total[extra] = usage_total.get(extra, 0) + usage[extra]

    # Every judgement is independent by construction: a claim is scored
    # against the passages it cites and nothing else, which is what makes the
    # metric mean anything. So they are built as a list first and then run
    # concurrently. Sequentially, one arm took the better part of an hour
    # through the CLI transport, where about half of each call is process
    # spawn and preamble rather than the model thinking.
    #
    # The two speedups not taken, because both trade the measurement for the
    # clock: reusing one session across claims would remove the spawn and let
    # claims see each other, and batching several claims into one call would
    # change what the judge is answering.
    tasks = []
    for record in records:
        if record["failure"]:
            continue
        case = by_id[record["case"]]
        hits = record["surface"]["hits"]
        for claim in scores[record["case"]]["claims"]:
            grounded = [i for i in claim["grounded_in"] if i in hits]
            if not grounded:
                # Nothing to judge: every id it cited is one the archive never
                # returned, which groundedness_log has already counted.
                continue
            tasks.append({"kind": "groundedness", "case": record["case"],
                          "document": claim["source_uri"], "claim": claim,
                          "grounded": grounded, "as_of": case["as_of"],
                          "symptom": case["symptom"].strip()})
        if case["group"] != "near_miss":
            continue
        for claim in scores[record["case"]]["claims"]:
            if claim["truth"] not in ("partial", "superseded"):
                continue
            tasks.append({"kind": "divergence", "case": record["case"],
                          "document": claim["source_uri"], "claim": claim,
                          "symptom": case["symptom"].strip(),
                          "missing_evidence": case.get("missing_evidence")
                          or [],
                          "wanted": case["expect"].get("divergence_names")
                          or []})

    def run_task(task):
        claim = task["claim"]
        if task["kind"] == "groundedness":
            passages = []
            for passage_id in task["grounded"]:
                try:
                    # The passage as the archive returned it, whole. An
                    # earlier version sent text and heading_path only, and
                    # the judge then called a correct `superseded` claim
                    # unsupported: document_superseded_by is a field on the
                    # passage rather than a sentence in it, and a judge that
                    # cannot see the qualifier marks down the agent for
                    # copying it, which is the behaviour the spec pins.
                    passages.append(rpc(port, "passage_get",
                                        {"passage_id": passage_id}))
                except SystemExit as exc:
                    passages.append({"passage_id": passage_id,
                                     "error": str(exc)})
            # The whole claim, every field of it. The first version passed
            # source_uri, applicability, confidence and divergence only,
            # while the metric reported the proportion of claims their
            # citations support: an invented resolution_taken or
            # signature_overlap scored as grounded because the judge was
            # never shown it. Sol found that at the gate.
            return call_judge(judge, grounding_system, {
                "incident": {"symptom": task["symptom"],
                             "as_of": task["as_of"]},
                "precedent_claim": claim["offered_claim"],
                "cited_passages": passages,
            }, key)
        return call_judge(judge, divergence_system, {
            "incident": {"symptom": task["symptom"],
                         "missing_evidence": task["missing_evidence"]},
            "precedent_document": task["document"],
            "distinguishing_factors": task["wanted"],
            "divergence_text": claim["divergence"],
        }, key)

    # Ordered results, whatever order they complete in: a record that changes
    # its verdict order between runs would show a diff that is not a finding.
    lanes = max(1, int(judge.get("concurrency", 4)))
    started = time.perf_counter()
    if tasks:
        def timed(task):
            call_started = time.perf_counter()
            result = run_task(task)
            return result, (time.perf_counter() - call_started) * 1000

        with concurrent.futures.ThreadPoolExecutor(max_workers=lanes) as pool:
            timings = list(pool.map(timed, tasks))
        outcomes = [result for result, _ in timings]
        # The claims about this transport being slower per call, and about
        # concurrency changing the wall clock, were in commit messages and
        # nowhere a reader could check them.
        per_call = sorted(ms for _, ms in timings)
        pace = {
            "lanes": lanes,
            "calls": len(per_call),
            "per_call_p50_ms": round(statistics.median(per_call), 1),
            "per_call_p95_ms": round(
                per_call[max(0, -(-len(per_call) * 95 // 100) - 1)], 1),
            "wall_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    else:
        outcomes, pace = [], {"lanes": lanes, "calls": 0}
    for task, (verdict, usage) in zip(tasks, outcomes):
        account(usage)
        verdicts[task["kind"]].append({
            "case": task["case"], "document": task["document"],
            "verdict": verdict})

    def rate(entries, field):
        # A reply that parsed but does not carry the boolean this metric is
        # about has said nothing, and scoring it false would put a judge's
        # formatting into the agent's column. Same treatment as a reply that
        # did not parse: an error, out of the denominator, listed.
        def malformed(entry):
            return ("error" in entry["verdict"]
                    or not isinstance(entry["verdict"].get(field), bool))

        errors = [e for e in entries if malformed(e)]
        scored = [e for e in entries if not malformed(e)]
        good = [e for e in scored if e["verdict"][field] is True]
        return {
            "value": round(len(good) / len(scored), 4) if scored else None,
            "numerator": len(good),
            "denominator": len(scored),
            "errors": errors,
            "verdicts": entries,
        }

    near_miss_cases = [c["id"] for c in cases if c["group"] == "near_miss"]
    judged_cases = {e["case"] for e in verdicts["divergence"]}
    transport = judge.get("transport", "anthropic")
    return {
        "model": judge["model"],
        "transport": transport,
        # What the harness can pin, per transport, said as itself. The metered
        # API takes a temperature and a token limit; the CLI takes a model and
        # an effort and neither of the other two. A record that carried
        # "temperature: 0" from a transport that cannot set one would be
        # asserting a control nobody exercised.
        "temperature": (judge.get("temperature", 0)
                        if transport == "anthropic" else None),
        "max_tokens": (judge.get("max_tokens", 1500)
                       if transport == "anthropic" else None),
        "sampling": (f"temperature {judge.get('temperature', 0)}"
                     if transport == "anthropic"
                     else "no temperature; effort is carried by the model id, "
                          "which is pinned and compared like any other input"),
        "effort": (judge.get("effort", "high") if transport == "cursor"
                   else None),
        "cli_version": (cursor_version() if transport == "cursor" else None),
        # Whether the judge could reach the corpus, tested rather than
        # asserted. The metered transport has no file tools, so it records
        # None: there is nothing to isolate.
        "isolation": isolation,
        # The code that built these payloads and read these verdicts, and
        # only that code. Not the record's top-level scorer fingerprint,
        # which covers this whole file and moves on any edit: that one is
        # answered by a free rescore, this one by a paid re-judge.
        "scorer_fingerprint": judge_code_fingerprint(transport),
        "prompts": {
            "groundedness": {
                "path": judge["groundedness_prompt"],
                "fingerprint": file_fingerprint(judge["groundedness_prompt"]),
            },
            "divergence": {
                "path": judge["divergence_prompt"],
                "fingerprint": file_fingerprint(judge["divergence_prompt"]),
            },
        },
        "usage": usage_total,
        "pace": pace,
        "groundedness_judge": {
            **rate(verdicts["groundedness"], "supported"),
            "unit": "precedent claims whose cited passages support them",
        },
        "divergence_quality": {
            **rate(verdicts["divergence"], "names_a_distinguishing_factor"),
            "unit": "near-miss precedents offered, scored on whether the "
                    "stated divergence names an actual distinguishing factor",
            "near_miss_cases": len(near_miss_cases),
            "near_miss_cases_with_a_precedent_to_judge": len(judged_cases),
            "not_offered": sorted(set(near_miss_cases) - judged_cases),
        },
    }


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------

def run_arm(config, arm, cases, stamp, judged=True):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Judgement mode runs the agent "
            "live: there is no offline path to a false precedent rate.")
    oa = require_contracts()

    spec = spec_document(config["spec"])
    port = spec_port(spec, config["spec"])
    with open(arm["index"]) as handle:
        index = json.load(handle)
    if index.get("chunker") != arm["chunker"]:
        raise SystemExit(
            f"arm {arm['label']} says chunker {arm['chunker']}, "
            f"{arm['index']} was built with {index.get('chunker')}. An arm "
            f"recorded against the wrong index compares nothing.")
    prompt_text, prompt_source, prompt_fingerprint = system_prompt_for(spec,
                                                                      arm)
    # None means the spec's own prompt, which `oa` uses when nothing overrides
    # it. Passing the spec's text back in as an override would look identical
    # and would not be: an override replaces the whole prompt, so any future
    # change to how the runner assembles one would silently stop applying.
    override = prompt_text if arm.get("system_prompt") else None
    if arm.get("system_prompt") and arm.get("derive") == "single_query":
        if prompt_text != derive_single_query_prompt(spec):
            raise SystemExit(
                f"{arm['system_prompt']} is not a fresh derivation from "
                f"{config['spec']}, so this arm differs from the shipped "
                f"prompt in more than the paragraph it names. Regenerate it "
                f"with --write-prompts and re-read the diff.")

    with open(DATASET) as handle:
        dataset = yaml.safe_load(handle)
    # Before the sweep, not after it. This used to sit beside the record it
    # writes, which is 38 live runs too late to learn that the ground truth
    # was judged against different documents.
    corpus, corpus_fingerprint = check_corpus_pin(dataset)

    log_dir = os.path.join(RESULTS, ".logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{arm['label']}.log")
    proc = start_adapter(arm["index"], port, log_path=log_path)
    records, scores = [], {}
    try:
        for position, case in enumerate(cases, 1):
            record = run_case(oa, config, case, log_path, override,
                              config.get("timeout", 600))
            records.append(record)
            scores[case["id"]] = score_run(case, record)
            state = ("failed: " + record["failure"]["kind"]
                     if record["failure"]
                     else ("refused" if scores[case["id"]]["refused"]
                           else f"{len(scores[case['id']]['claims'])} "
                                f"precedent(s)"))
            print(f"  [{position}/{len(cases)}] {case['id']:<4} "
                  f"{record['elapsed_ms'] / 1000:6.1f}s  "
                  f"{len(record['surface']['calls'])} calls, {state}",
                  flush=True)
        summary = aggregate(cases, records, scores)
        judgement = (judge_run(config, records, scores, cases, port, key)
                     if judged else None)
        sample = rpc(port, "precedent_search",
                     {"symptom_text": cases[0]["query"],
                      "before": cases[0]["as_of"], "limit": 1})
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    return {
        "recorded_at": stamp,
        "label": arm["label"],
        "mode": "judgement",
        "arm": {
            "description": arm.get("description", ""),
            "index": arm["index"],
            "chunker": arm["chunker"],
            "system_prompt": prompt_source,
            "system_prompt_fingerprint": prompt_fingerprint,
        },
        "index": arm["index"],
        "index_fingerprint": file_fingerprint(arm["index"]),
        "chunker": arm["chunker"],
        "agent": {
            "runtime": agent_runtime(oa),
            "spec": config["spec"],
            "spec_fingerprint": file_fingerprint(config["spec"]),
            "task": config["task"],
            "model": spec["intelligence"]["model"],
            "temperature": spec["intelligence"]["config"].get("temperature"),
            "max_tokens": spec["intelligence"]["config"].get("max_tokens"),
        },
        "corpus": {"documents": len(corpus),
                   "fingerprint": corpus_fingerprint},
        "dataset": {
            "cases": len(cases),
            "path": DATASET,
            "fingerprint": dataset_fingerprint(DATASET),
            "ids": [c["id"] for c in cases],
            "complete": len(cases) == len(dataset["cases"]),
        },
        "surface": {"floor_applied": sample.get("floor_applied"),
                    "port": port},
        # Which scoring produced these figures. The runs are the expensive
        # half and the scoring is the half that gets edited, so a record
        # carries the fingerprint of the code that read it and --rescore can
        # recompute every deterministic figure from what is stored here
        # rather than paying for 38 more live runs.
        # Scoped deliberately. This fingerprints the code that produced the
        # deterministic figures, which --rescore can recompute from the
        # record. The judged verdicts cannot be recomputed: re-judging is a
        # fresh call to a model. So they carry their own fingerprint, taken
        # when they were produced, and a rescore leaves both the verdicts and
        # that fingerprint alone. Stamping one number over both would certify
        # judged figures against code that never saw them.
        "scorer": {"path": os.path.relpath(os.path.abspath(__file__)),
                   "fingerprint": file_fingerprint(os.path.abspath(__file__)),
                   "scope": "the deterministic figures. The judged half "
                            "carries its own fingerprint under judged."},
        "deterministic": summary,
        "judged": judgement,
        "not_measured": {
            "cost_per_recall_usd":
                "oa reports no token usage, so a per-recall cost from this "
                "runner would be a price list multiplied by an estimate. The "
                "judge's own usage is recorded because the API returns it.",
            "section_level_citation":
                "ground truth names documents, so neither the log check nor "
                "the judge distinguishes a citation of the right document's "
                "Resolution from its Gaps. Unmeasured, not mitigated.",
        },
        "per_case": [
            {**record, "score": scores[record["case"]]} for record in records
        ],
    }


def divergence_by_case(judged):
    """The spec's unit for divergence_quality: near-miss cases, not claims.

    docs/precedent-analyst.md section 7 defines it over cases where the
    divergence names the distinguishing factor. The judge scores a claim at a
    time, which is the right unit to ask a judge in, and a case offering two
    diverging records would otherwise carry twice the weight of one offering a
    single record. Computed here from the verdicts the record already stores,
    so it costs nothing and needs no re-judge: this is a different aggregation
    of the same measurement, and both are published.
    """
    verdicts = (judged.get("divergence_quality") or {}).get("verdicts") or []
    by_case = {}
    for entry in verdicts:
        verdict = entry["verdict"]
        if not isinstance(verdict.get("names_a_distinguishing_factor"), bool):
            continue
        by_case.setdefault(entry["case"], []).append(
            verdict["names_a_distinguishing_factor"])
    good = sum(1 for outcomes in by_case.values() if any(outcomes))
    return {
        "value": round(good / len(by_case), 4) if by_case else None,
        "numerator": good,
        "denominator": len(by_case),
        "unit": "near-miss cases where the divergence names an actual "
                "distinguishing factor, which is the unit section 7 defines",
    }


def metric_row(name, block):
    if block is None or block.get("value") is None:
        return f"| `{name}` | - | - | not scored in this run |"
    return (f"| `{name}` | {pct(block['value'])} | "
            f"{block['numerator']}/{block['denominator']} | {block['unit']} |")


def markdown(result):
    summary = result["deterministic"]
    judged = result["judged"]
    arm = result["arm"]
    lines = [
        f"# Precedent Analyst, judgement run `{result['label']}`",
        "",
        "Generated by `evals/judgement.py`. **A record of one live run, not "
        "a regenerable artefact.** Every other table in this directory is a "
        "function of the corpus, the dataset and a config, and CI fails when "
        "one drifts. This one has a model in it: re-running the same arm "
        "gives different numbers, so it carries a timestamp, the spec, the "
        "prompt and the model that produced it. Nothing checks the numbers "
        "for drift, because nothing can regenerate them. What can be checked "
        "is the inputs listed below, which is what `--check-records` does: "
        "it says when this recording has stopped describing the tree.",
        "",
        f"- Recorded {result['recorded_at']}"
        + (f", rescored {result['rescored_at']} with "
           f"`{result['scorer']['fingerprint'][:16]}`"
           if result.get("rescored_at") else ""),
        f"- Arm `{result['label']}`" + (f", {arm['description']}"
                                        if arm["description"] else ""),
        f"- Agent `{result['agent']['spec']}` task `{result['agent']['task']}`,"
        f" model {result['agent']['model']}, temperature "
        f"{result['agent']['temperature']}",
        f"- System prompt: {arm['system_prompt']}"
        + (f" (`{arm['system_prompt_fingerprint'][:16]}`)"
           if arm["system_prompt_fingerprint"] else ""),
        f"- Index `{result['index']}`, chunker {result['chunker']}, "
        f"relevance floor {result['surface']['floor_applied']}",
        f"- Corpus {result['corpus']['documents']} documents, fingerprint "
        f"`{result['corpus']['fingerprint'][:16]}`",
        f"- Dataset {result['dataset']['cases']} cases"
        + ("" if result["dataset"]["complete"]
           else " (a subset: this is not a full sweep)")
        + f", ground truth `{result['dataset']['fingerprint'][:16]}`",
        "",
        "## Measured by code",
        "",
        "Every figure here follows from the typed output, the adapter's "
        "audit log and the ground truth. None of it is a model's opinion.",
        "",
        "| Metric | Value | Count | Denominator |",
        "| --- | --- | --- | --- |",
        metric_row("false_precedent_rate", summary["false_precedent_rate"]),
        metric_row("applies_omission_rate", summary["applies_omission_rate"]),
        metric_row("no_precedent_accuracy", summary["no_precedent_accuracy"]),
        metric_row("false_refusal_rate", summary["false_refusal_rate"]),
        metric_row("groundedness_log", summary["groundedness_log"]),
        metric_row("agent_reach", summary["agent_reach"]),
        "",
        "**Read the two top rows together.** `false_precedent_rate` fires "
        "only on a claim the agent made. `applies_omission_rate` fires on one "
        "it did not: a document the ground truth says applies here, which the "
        "surface returned, and which no precedent was offered on at all. "
        "Nothing is overclaimed and the responder still does not get the "
        "thing that applies, and every other rate here is blind to it, "
        "`agent_reach` included, because the archive did return it.",
        "",
        "Applicability offered across this run: "
        + ", ".join(f"`{word}` {count}" for word, count
                    in sorted(summary["applicability_offered"].items(),
                              key=lambda kv: -kv[1]))
        + ". A `false_precedent_rate` of zero over a run that never used "
          "`applies` is a property of the vocabulary the agent reached for, "
          "not evidence that it judged applicability well.",
        "",
        "`groundedness_log` is the check the adapter log can settle: every "
        "cited `passage_id` was in the set the surface returned. It proves a "
        "citation was not invented. It does not prove the claim rests on the "
        "passage, which is what the judge below is for.",
        "",
        f"{summary['unrelated_claims']['count']} of "
        f"{summary['unrelated_claims']['of']} precedent claims name a "
        f"document the case's ground truth does not call relevant"
        + (": " + ", ".join(
            "`" + c.split(":", 1)[0] + "` " +
            c.split(":", 1)[1].replace("corpus://", "")
            for c in summary["unrelated_claims"]["claims"])
           if summary["unrelated_claims"]["claims"] else "")
        + ". Reported rather than scored, for the reason in the record: "
          "relevance is judged sharply, so an unlisted document offered as "
          "`partial` is a softer error than a diverging one offered as "
          "`applies`.",
        "",
        f"{summary['understated_claims']['count']} of "
        f"{summary['understated_claims']['of']} claims go the other way: "
        f"offered as `partial` or `superseded` where the truth is `applies`. "
        f"Read this beside the false precedent rate. A zero there is only "
        f"worth having if this is not large, because an agent that never "
        f"says `applies` cannot offer a false precedent and has not "
        f"calibrated anything.",
        "",
        "`agent_reach` is the retrieval figure this mode can report and "
        "retrieval mode cannot: relevant documents the archive actually "
        "returned across the queries **the agent chose**, rather than across "
        "one canonical probe. It is not comparable to "
        "`precedent_hit_rate@k`: no rank truncates it and the queries are "
        "not the dataset's.",
        "",
    ]

    if judged:
        lines += [
            "## Judged by a model",
            "",
            f"A separate judge, {judged['model']} through the "
            f"{judged.get('transport', 'anthropic')} transport, "
            f"{judged.get('sampling') or 'sampling unstated'}, scored by "
            + (f"`{judged['scorer_fingerprint'][:16]}`"
               if judged.get("scorer_fingerprint")
               else "a scorer this record does not fingerprint, because it "
                    "was recorded before that field existed")
            + f", with the prompts committed at "
            f"`{judged['prompts']['groundedness']['path']}` and "
            f"`{judged['prompts']['divergence']['path']}`. This is a model's "
            f"opinion of a model, reported apart from the table above so it "
            f"cannot be read as the same kind of number.",
            "",
            (f"It ran with the repository replaced by an empty tmpfs inside a "
             f"private mount namespace, so the documents behind the passages "
             f"were absent rather than forbidden, and that is tested before "
             f"any claim is scored rather than asserted: a shell tried the "
             f"masked path and the /proc route into another process's root "
             f"and both failed, then the judge itself was asked and answered "
             f"`{(judged.get('isolation') or {}).get('model_answer', '')[-20:].strip()}`. "
             f"Without the namespace this judge reads the corpus straight "
             f"through an empty workspace and read-only mode, which was "
             f"measured rather than assumed. The namespace masks paths and remounts /proc "
             f"rather than building a container, so read it as a control "
             f"against the obvious route and not as containment; the metered "
             f"transport, which has no file tools at all, is the structural "
             f"version."
             if (judged.get("isolation") or {}).get("namespace")
             else "This transport has no file tools, so there is nothing for "
                  "the judge to read but the passages it is given."),
            "",
            "| Metric | Value | Count | Denominator |",
            "| --- | --- | --- | --- |",
            metric_row("groundedness_judge", judged["groundedness_judge"]),
            metric_row("divergence_quality", divergence_by_case(judged)),
            "",
            f"`divergence_quality` is reported over cases, which is the unit "
            f"section 7 of `docs/precedent-analyst.md` defines. The judge "
            f"scores one claim at a time, and that figure, "
            f"{judged['divergence_quality']['numerator']}/"
            f"{judged['divergence_quality']['denominator']} claims, is in the "
            f"record beside every verdict. They differ whenever a case offers "
            f"more than one diverging record.",
            "",
        ]
        rounds = result.get("judgings") or []
        if rounds:
            lines += [
                "This arm has been judged "
                + f"{len(rounds) + 1} times over the same claims. Earlier "
                  "rounds, kept because the spread is part of the result:",
                "",
                "| judged at | transport | corpus reachable? | "
                "groundedness_judge | divergence_quality |",
                "| --- | --- | --- | --- | --- |",
            ]
            for entry in rounds:
                grounded = entry["groundedness_judge"]
                diverged = entry["divergence_quality"]
                failed = not (grounded["denominator"]
                              or diverged["denominator"])
                transport = entry.get("transport")
                if transport is None:
                    # Predates the field. Inferring anthropic here would let a
                    # round with unknown provenance report "no file tools",
                    # which is the opposite of the promise this record makes.
                    transport, proof = "not recorded", "**not recorded**"
                elif transport == "anthropic":
                    proof = "no file tools"
                elif (entry.get("isolation") or {}).get("scope"):
                    proof = "namespace, probed"
                else:
                    # Not the same as "it ran unisolated": for these rounds
                    # the evidence is not in the record, which for a cited
                    # figure is the thing to say rather than a guess either
                    # way.
                    proof = "**not recorded**"
                lines.append(
                    f"| {entry['at']} | {transport} | {proof} | "
                    f"{grounded['numerator']}/{grounded['denominator']} | "
                    f"{diverged['numerator']}/{diverged['denominator']}"
                    + (" (every call failed)" if failed else "") + " |")
            current = judged["groundedness_judge"]
            current_div = judged["divergence_quality"]
            current_transport = judged.get("transport", "anthropic")
            current_proof = ("no file tools" if current_transport == "anthropic"
                             else "namespace, probed"
                             if (judged.get("isolation") or {}).get("scope")
                             else "**not recorded**")
            lines += [
                f"| {result.get('rejudged_at', result['recorded_at'])} "
                f"(current) | {current_transport} | {current_proof} | "
                f"{current['numerator']}/{current['denominator']} | "
                f"{current_div['numerator']}/{current_div['denominator']} |",
                "",
                ("Same claims, same prompts and same payload. What moves "
                 "between rounds is the judge."
                 if all(entry.get("scorer_fingerprint")
                        == judged.get("scorer_fingerprint")
                        and entry.get("model") == judged.get("model")
                        and entry.get("temperature") == judged.get(
                            "temperature")
                        and entry.get("transport", "anthropic")
                        == judged.get("transport", "anthropic")
                        and entry.get("cli_version") == judged.get(
                            "cli_version")
                        and entry.get("effort") == judged.get("effort")
                        and entry.get("max_tokens") == judged.get("max_tokens")
                        and all(entry.get("prompts", {}).get(name)
                                == (judged.get("prompts") or {})
                                .get(name, {}).get("fingerprint")
                                for name in ("groundedness", "divergence"))
                        for entry in rounds)
                 else "These rounds did not all run the same judge inputs: "
                      "re-judging is also the remedy for a changed prompt or "
                      "payload, so compare the fingerprints in the record "
                      "before reading the spread as judge variance."),
                "",
            ]

        divergence = judged["divergence_quality"]
        not_offered = (", ".join(f"`{c}`" for c in divergence["not_offered"])
                       or "none")
        lines += [
            f"{divergence['near_miss_cases_with_a_precedent_to_judge']} of "
            f"{divergence['near_miss_cases']} near-miss cases offered a "
            f"precedent for the diverging record, so the rest have no "
            f"divergence to judge. Not offered: {not_offered}. A retrieval "
            f"miss is not folded into this metric; it shows up in "
            f"`agent_reach` and in the false refusal rate.",
            "",
            f"Judge usage: {judged['usage']['calls']} calls, "
            f"{judged['usage']['input_tokens']} input and "
            f"{judged['usage']['output_tokens']} output tokens"
            + (f", {(judged.get('pace') or {}).get('lanes')} at a time, "
               f"{(judged.get('pace') or {}).get('per_call_p50_ms', 0) / 1000:.1f}s "
               f"per call at p50 and "
               f"{(judged.get('pace') or {}).get('wall_ms', 0) / 1000:.0f}s "
               f"for the round"
               if (judged.get("pace") or {}).get("calls") else "")
            + ".",
            "",
        ]
    else:
        lines += ["## Judged by a model", "",
                  "Not scored in this run (`--no-judge`).", ""]

    hygiene = summary["hygiene"]
    failures = summary["failures"]
    lines += [
        "## What went wrong, by name",
        "",
        f"- Runs the harness rejected or that failed to parse: "
        f"{failures['total']} of {summary['cases']}"
        + (f" ({', '.join(f'{k} {v}' for k, v in failures['by_kind'].items())})"
           if failures["by_kind"] else "")
        + ". A rejected output is the contract working, so it is reported "
          "here rather than folded into a rate: an agent that produced "
          "nothing usable neither offered a precedent nor refused.",
        f"- Named one document and cited a passage of another: "
        f"{len(summary['citation_identity']['misnamed'])} claim(s) of "
        f"{summary['citation_identity']['claims']}"
        + (": " + ", ".join(
            f"`{v['case']}` names {v['named'].replace('corpus://', '')} and "
            f"cites {v['incident_ref_resolves_to'].replace('corpus://', '')}"
            for v in summary["citation_identity"]["misnamed"])
           if summary["citation_identity"]["misnamed"] else "")
        + ". Resolved through the adapter log, which is the only place the "
          "document a passage came from is stated by anything but the claim "
          "itself. `groundedness_log` cannot see this: every id in such a "
          "claim was returned by the surface.",
        f"- Rested a claim on passages from more than one document: "
        f"{len(summary['citation_identity']['cross_document'])} claim(s). "
        f"Reported, not scored: a precedent supported by a prior record and "
        f"the procedure that covers it is doing what the contract allows.",
        f"- Cited a document the case bars from grounding a claim: "
        f"{len(hygiene['must_not_cite'])} case(s)"
        + (": " + "; ".join(
            f"`{h['case']}` "
            + ", ".join(d.replace("corpus://", "") for d in h["documents"])
            + " as " + ", ".join(str(a) for a in h["offered"])
            for h in hygiene["must_not_cite"])
           if hygiene["must_not_cite"] else "")
        + ". The applicability matters as much as the citation: `precedents[]`"
          " has no entry that means retrieved and rejected, so a document "
          "named in prose as unusable and typed as `partial` anyway has put "
          "its caveat where the contract does not carry it.",
        f"- Called the archive with a bound other than the view's `as_of`: "
        f"{len(hygiene['wrong_time_bound'])} case(s)"
        + (f" ({', '.join(h['case'] for h in hygiene['wrong_time_bound'])})"
           if hygiene["wrong_time_bound"] else "")
        + ". The bound is what keeps a record written after the view out of "
          "it, so this is read from the log rather than from the agent's "
          "account of what it asked.",
        f"- Put an entity id in a query: "
        f"{len(hygiene['identity_in_queries'])} case(s)"
        + (f" ({', '.join(h['case'] for h in hygiene['identity_in_queries'])})"
           if hygiene["identity_in_queries"] else ""),
        f"- Reported no applicable precedent without calling "
        f"`coverage_describe`: {len(hygiene['refused_without_coverage'])} "
        f"case(s)"
        + (f" ({', '.join(hygiene['refused_without_coverage'])})"
           if hygiene["refused_without_coverage"] else "")
        + ". Read from the log, not from the output, which cannot attest to "
          "its own tool use.",
        f"- Reported more queries than the surface was asked: "
        f"{len(hygiene['self_report_overstated'])} case(s)"
        + (f" ({', '.join(h['case'] for h in hygiene['self_report_overstated'])})"
           if hygiene["self_report_overstated"] else "")
        + ". `queries_issued` against the calls in the log, which is the "
          "only place the two can be told apart.",
        f"- Searches the surface was asked for: "
        f"{hygiene['queries_per_case']['issued']} across {summary['cases']} "
        f"cases, median {hygiene['queries_per_case']['median']} per case. "
        f"Reported in `queries_issued`: "
        f"{hygiene['queries_per_case']['reported']}.",
        "",
        "## Latency",
        "",
        f"p50 {summary['latency_ms']['p50'] / 1000:.1f}s "
        f"({summary['latency_ms']['p50']:.0f}ms), p95 "
        f"{summary['latency_ms']['p95'] / 1000:.1f}s "
        f"({summary['latency_ms']['p95']:.0f}ms) over "
        f"{summary['latency_ms']['calls']} runs. "
        f"{summary['latency_ms']['note']}",
        "",
        "## What this run does not measure",
        "",
        "| Metric | Why not |",
        "| --- | --- |",
    ]
    for name, why in sorted(result["not_measured"].items()):
        lines.append(f"| `{name}` | {why} |")
    lines += [
        "",
        "Per-case detail, including every query issued, every passage the "
        "surface returned and every judge verdict, is in the timestamped "
        "JSON beside this file.",
        "",
    ]
    return "\n".join(lines)


def rescore(path, config=None):
    """Recompute every deterministic figure from a recorded sweep.

    The runs are what cost money; the scoring is what gets edited. A record
    stores each case's typed output and the adapter log lines that run
    produced, which is everything score_run() reads, so a scoring change can
    be applied to a sweep already paid for. The judged verdicts are kept as
    recorded: re-judging is a fresh call to a model and would be a different
    measurement, not a recount.

    The record says it was rescored and by which scorer. A file whose numbers
    changed after it was written has to say so, or it reads as what the run
    reported at the time.
    """
    with open(path) as handle:
        result = json.load(handle)
    if result.get("mode") != "judgement":
        raise SystemExit(f"{path} is not a judgement record")

    with open(DATASET) as handle:
        dataset = yaml.safe_load(handle)
    by_id = {c["id"]: c for c in dataset["cases"]}
    missing = [i for i in result["dataset"]["ids"] if i not in by_id]
    if missing:
        raise SystemExit(
            f"the dataset no longer holds {', '.join(missing)}, so this "
            f"record cannot be rescored against it. Ground truth moving is "
            f"a reason to re-run, not to recount.")
    if dataset_fingerprint(DATASET) != result["dataset"]["fingerprint"]:
        raise SystemExit(
            "the dataset has changed since this sweep was recorded. "
            "Rescoring against different ground truth would produce figures "
            "that belong to neither run: re-run the arm.")

    cases = [by_id[i] for i in result["dataset"]["ids"]]
    records = [{k: v for k, v in entry.items() if k != "score"}
               for entry in result["per_case"]]
    scores = {r["case"]: score_run(by_id[r["case"]], r) for r in records}
    before = result["deterministic"]
    result["deterministic"] = aggregate(cases, records, scores)
    # Which published figures moved, by name. A stamp saying a rescore
    # happened meets the letter of "a file whose numbers changed says so" and
    # not the point of it: a reader should not have to diff two JSON files to
    # learn that a headline rate is a different number than it was.
    for name in sorted(set(before) | set(result["deterministic"])):
        old_block = before.get(name)
        new_block = result["deterministic"].get(name)
        if isinstance(new_block, dict) and "count" in new_block:
            # understated_claims and unrelated_claims carry a count rather
            # than a rate, and they were moving in the published table with
            # nothing on stdout to say so.
            was_count = (old_block or {}).get("count")
            if was_count != new_block["count"]:
                print(f"  {name}: {was_count}/{(old_block or {}).get('of')} "
                      f"-> {new_block['count']}/{new_block['of']}")
            continue
        if not isinstance(new_block, dict) or "value" not in new_block:
            # Everything else in the deterministic block: hygiene, the
            # applicability distribution, latency. markdown() rewrites the
            # published table from all of it, so a scoring edit that moved a
            # must_not_cite line or the p95 index could change a published
            # file with nothing on stdout but a rescored_at stamp.
            if old_block != new_block:
                print(f"  {name}: changed")
            continue
        if not isinstance(old_block, dict) or "value" not in old_block:
            # A metric this scoring added. Worth a line of its own: a figure
            # appearing in a published table without the tool saying it is
            # new reads as one that was always there.
            print(f"  {name}: new, {pct(new_block.get('value'))} "
                  f"({new_block.get('numerator')}/"
                  f"{new_block.get('denominator')})")
            continue
        was = (old_block.get("value"), old_block.get("numerator"),
               old_block.get("denominator"))
        now = (new_block.get("value"), new_block.get("numerator"),
               new_block.get("denominator"))
        if was != now:
            print(f"  {name}: {pct(was[0])} ({was[1]}/{was[2]}) -> "
                  f"{pct(now[0])} ({now[1]}/{now[2]})")
    result["per_case"] = [{**r, "score": scores[r["case"]]} for r in records]
    # An arm's description is a label on the experiment rather than a
    # measurement of it, and a label that describes the arm wrongly is worse
    # in a published table than in a config nobody reads. Refreshed from the
    # config when it has changed, and said out loud, because editing anything
    # in a record after the run has to be visible.
    if config:
        for arm in config.get("arms") or []:
            if arm["label"] != result["label"]:
                continue
            fresh = arm.get("description", "")
            if fresh and fresh != result["arm"].get("description"):
                print(f"  arm description updated from {args_config_path}:")
                print(f"    was: {result['arm'].get('description')}")
                print(f"    now: {fresh}")
                result["arm"]["description"] = fresh

    result["rescored_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # The deterministic half only. result["judged"] is carried through
    # untouched, including the fingerprint of the code that produced it: a
    # rescore re-reads a record, it does not re-judge one, and a single
    # fingerprint over both halves would say the judge output was produced by
    # whatever this file happens to be today.
    result["scorer"] = {
        "path": os.path.relpath(os.path.abspath(__file__)),
        "fingerprint": file_fingerprint(os.path.abspath(__file__)),
        "scope": "the deterministic figures. The judged half carries its own "
                 "fingerprint under judged.",
    }
    with open(path, "w") as handle:
        json.dump(result, handle, indent=2, sort_keys=False)
        handle.write("\n")
    table = os.path.join(RESULTS, f"{result['label']}.md")
    with open(table, "w") as handle:
        handle.write(markdown(result))
    print(f"rescored {path} and rewrote {table}")
    return 0


# --------------------------------------------------------------------------
# Whether a recording still describes this configuration
# --------------------------------------------------------------------------

STAMP = re.compile(r"\d{8}T\d{6}Z")


def latest_record(label):
    """The most recent recording of an arm, by the stamp in its filename.

    The stamp is ISO basic UTC, so lexicographic order is chronological. The
    pattern match is what stops a label that is a prefix of another label
    reading the other one's records and reporting on the wrong arm.
    """
    if not os.path.isdir(RESULTS):
        return None
    names = sorted(
        name for name in os.listdir(RESULTS)
        if name.startswith(f"{label}-") and name.endswith(".json")
        and STAMP.fullmatch(name[len(label) + 1:-len(".json")]))
    return os.path.join(RESULTS, names[-1]) if names else None


def fingerprint_or_none(path):
    """A missing input is drift, not a crash: the check reports every arm."""
    try:
        return file_fingerprint(path)
    except OSError:
        return None


def current_runtime():
    """The installed runtime, read once per process.

    record_drift asks about it per arm, and shelling out to the CLI's
    interpreter three times to learn the same thing is waste.
    """
    global _RUNTIME
    if _RUNTIME is None:
        oa = shutil.which("oa")
        _RUNTIME = agent_runtime(oa) if oa else {}
    return _RUNTIME


def record_drift(config, arm, record):
    """What has moved under a recording since it was made.

    Two kinds, and the difference between them is money. An input the runs
    depended on invalidates the runs: only a fresh sweep can say what this
    configuration does. The scoring code invalidates the figures and not the
    runs, and --rescore recomputes those from what the record already holds.
    """
    rerun, rescore_owed, rejudge_owed = [], [], []

    # The spec file carries the model, the sampling config and, for the two
    # arms that do not override it, the system prompt. One fingerprint over
    # the file covers all three.
    agent = record.get("agent", {})
    if agent.get("task") != config["task"]:
        rerun.append(f"the config runs task {config['task']}, the recording "
                     f"ran {agent.get('task')}")
    runtime = agent.get("runtime") or {}
    if not runtime:
        # A provenance gap rather than a moved input, and worth saying as
        # that: nothing about this recording has changed, it was made before
        # the runtime was pinned. Only a re-run can close it, so it is listed
        # with the re-runs, and it is the one entry there that does not mean
        # something under the record has moved.
        rerun.append("the recording does not pin the CLI and provider that "
                     "ran it, so which runtime produced it is an assertion "
                     "rather than a property of the record. Only a fresh "
                     "sweep can close that")
    elif runtime.get("cli_version") != current_runtime().get("cli_version"):
        rerun.append(f"the recording ran CLI {runtime.get('cli_version')}, "
                     f"this tree has {current_runtime().get('cli_version')}")
    elif (runtime.get("provider_fingerprint")
          != current_runtime().get("provider_fingerprint")):
        rerun.append("the provider module has changed since the recording, so "
                     "tool calling is not the behaviour that was measured")
    if agent.get("spec") != config["spec"]:
        rerun.append(f"the config names spec {config['spec']}, the recording "
                     f"ran {agent.get('spec')}")
    elif agent.get("spec_fingerprint") != fingerprint_or_none(config["spec"]):
        rerun.append(f"{config['spec']} has changed since the recording")

    recorded_arm = record.get("arm", {})
    prompt = arm.get("system_prompt")
    if (prompt or "spec") != recorded_arm.get("system_prompt"):
        rerun.append(f"the arm now runs {prompt or 'the spec prompt'}, the "
                     f"recording ran {recorded_arm.get('system_prompt')}")
    elif prompt and (recorded_arm.get("system_prompt_fingerprint")
                     != fingerprint_or_none(prompt)):
        rerun.append(f"{prompt} has changed since the recording")

    if arm["index"] != record.get("index"):
        rerun.append(f"the arm now names {arm['index']}, the recording ran "
                     f"{record.get('index')}")
    elif record.get("index_fingerprint") != fingerprint_or_none(arm["index"]):
        rerun.append(f"{arm['index']} has been rebuilt since the recording")
    if arm["chunker"] != record.get("chunker"):
        rerun.append(f"the arm now declares chunker {arm['chunker']}, the "
                     f"recording ran {record.get('chunker')}")

    dataset = record.get("dataset", {})
    if dataset.get("fingerprint") != dataset_fingerprint(DATASET):
        rerun.append(f"{DATASET} has changed since the recording, so these "
                     f"figures were scored against different ground truth")
    if not dataset.get("complete", True):
        rerun.append(f"the recording is a subset, {dataset.get('cases')} of "
                     f"the dataset's cases: a smoke run, not the arm")

    try:
        corpus_now = fingerprint_corpus(load_corpus())
    except OSError:
        corpus_now = None
    if record.get("corpus", {}).get("fingerprint") != corpus_now:
        rerun.append("the corpus has changed since the recording, so the "
                     "archive the agent searched is not the one on disk")

    # The judged half costs a model call rather than a re-run: --rejudge
    # re-scores stored claims against the passages they cite. So a moved
    # judge is its own remedy, listed apart from a rescore because it spends
    # money and apart from a re-run because it does not spend a sweep.
    judge = config["judge"]
    judged = record.get("judged")
    if judged is None:
        # --no-judge leaves everything --rejudge consumes: the outputs, the
        # log lines and the citations. Calling for a fresh sweep here quotes
        # the most expensive remedy for the cheapest gap.
        rejudge_owed.append("the recording has no judged half, so "
                            "groundedness_judge and divergence_quality are "
                            "unmeasured for it")
    else:
        if judged.get("model") != judge["model"]:
            rejudge_owed.append(f"the config judges with {judge['model']}, "
                                f"the recording used {judged.get('model')}")
        transport = judge.get("transport", "anthropic")
        if judged.get("transport", "anthropic") != transport:
            rejudge_owed.append(f"the config judges through {transport}, the "
                                f"recording used "
                                f"{judged.get('transport', 'anthropic')}")
        elif transport == "cursor":
            if judged.get("effort") != judge.get("effort", "high"):
                rejudge_owed.append(
                    f"the config judges at effort "
                    f"{judge.get('effort', 'high')}, the recording used "
                    f"{judged.get('effort')}")
            if judged.get("cli_version") != cursor_version():
                rejudge_owed.append(
                    f"the recording judged with CLI "
                    f"{judged.get('cli_version')}, this host has "
                    f"{cursor_version()}")
        elif transport == "anthropic":
            if judged.get("max_tokens") != judge.get("max_tokens", 1500):
                rejudge_owed.append(
                    f"the config allows the judge "
                    f"{judge.get('max_tokens', 1500)} tokens, the recording "
                    f"allowed {judged.get('max_tokens')}")
            if judged.get("temperature") != judge.get("temperature", 0):
                rejudge_owed.append(
                    f"the config judges at temperature "
                    f"{judge.get('temperature', 0)}, the recording used "
                    f"{judged.get('temperature')}")
        for name in ("groundedness", "divergence"):
            path = judge[f"{name}_prompt"]
            stored = judged.get("prompts", {}).get(name, {})
            if stored.get("path") != path:
                rejudge_owed.append(f"the config judges {name} with {path}, "
                                    f"the recording used {stored.get('path')}")
            elif stored.get("fingerprint") != fingerprint_or_none(path):
                rejudge_owed.append(f"{path} has changed since the recording")
        # The code that built the judge payloads and read the verdicts back.
        # A payload change is invisible in the model, the temperature and the
        # prompts, and it is exactly what moved these figures once already.
        if judged.get("scorer_fingerprint") != judge_code_fingerprint(
                transport):
            rejudge_owed.append(
                "evals/judgement.py has changed since these verdicts were "
                "produced" if judged.get("scorer_fingerprint")
                else "the recording predates the judge fingerprint, so what "
                     "produced its verdicts is not established")

    # The record pins this whole file, so a comment here trips this as
    # readily as a change to score_run. That is the right way round: the
    # remedy costs seconds and settles the question either way.
    scorer = record.get("scorer", {})
    scoring_now = file_fingerprint(os.path.abspath(__file__))
    if scorer.get("fingerprint") != scoring_now:
        rescore_owed.append("evals/judgement.py has changed since these "
                            "figures were scored")

    return rerun, rescore_owed, rejudge_owed


def check_records(config, config_path):
    """Which recordings still describe the configuration in this tree.

    A judgement record is not a regenerable artefact, so nothing can diff a
    fresh table against the committed one. The other direction can be
    checked, and it is the one worth money: every recording names the spec,
    prompt, index, corpus, ground truth and judge it ran against, by
    fingerprint, and this compares those against what is on disk now. Not
    "would this table come back the same" but "is it still about the current
    configuration".

    It answers in both directions, and the green line is the useful half: an
    arm nobody owes a sweep for. A live run per case is the cost of assuming
    otherwise.

    Deliberately not in CI, unlike --check-prompts. A stale recording is a
    statement about money owed rather than a broken artefact, and a gate
    that fails until somebody spends is a gate that gets switched off.
    """
    stale = 0
    for arm in config["arms"]:
        path = latest_record(arm["label"])
        if path is None:
            stale += 1
            print(f"{arm['label']:<24} never recorded")
            print(f"    python3 evals/judgement.py --config {config_path} "
                  f"--arm {arm['label']}")
            continue
        with open(path) as handle:
            record = json.load(handle)
        rerun, rescore_owed, rejudge_owed = record_drift(config, arm, record)
        recorded = record.get("recorded_at", "an unstamped run")
        if not rerun and not rescore_owed and not rejudge_owed:
            print(f"{arm['label']:<24} current, recorded {recorded}")
            continue
        stale += 1
        owed = ("re-run owed" if rerun
                else "re-judge owed" if rejudge_owed
                else "rescore owed")
        print(f"{arm['label']:<24} {owed}, recorded {recorded} in "
              f"{os.path.relpath(path)}")
        for line in rerun + rejudge_owed + rescore_owed:
            print(f"  {line}")
        if rerun:
            print(f"    python3 evals/judgement.py --config {config_path} "
                  f"--arm {arm['label']}")
        elif rejudge_owed:
            # Re-judging recomputes the deterministic half on its way past,
            # so it is the whole remedy when both are owed.
            print(f"    python3 evals/judgement.py --rejudge {path}")
        else:
            print(f"    python3 evals/judgement.py --rescore {path}")
    if stale:
        print(f"\n{stale} of {len(config['arms'])} arm(s) stale. A re-run is "
              f"a live sweep; a re-judge is one model call per claim against "
              f"passages already recorded; a rescore reads what the record "
              f"holds and spends nothing.")
    return 1 if stale else 0


def select_cases(dataset, only, limit):
    cases = dataset["cases"]
    if only:
        wanted = [c.strip() for c in only.split(",") if c.strip()]
        by_id = {c["id"]: c for c in cases}
        missing = [c for c in wanted if c not in by_id]
        if missing:
            raise SystemExit(f"no such case(s): {', '.join(missing)}")
        cases = [by_id[c] for c in wanted]
    if limit:
        cases = cases[:limit]
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="evals/config.judgement.yaml")
    parser.add_argument("--arm", default=None,
                        help="which arm to record. Defaults to the first.")
    parser.add_argument("--cases", default=None,
                        help="comma separated case ids, for a cheap smoke "
                             "run. A record from a subset says so.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-judge", action="store_true",
                        help="deterministic metrics only: no judge calls.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be run and spend nothing.")
    parser.add_argument("--write-prompts", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="with --comparison, fail if the grid has drifted "
                             "rather than rewriting it.")
    parser.add_argument("--check-prompts", action="store_true",
                        help="regenerate every derived arm prompt and fail if "
                             "it has drifted. Needs no API key, so CI can "
                             "run it.")
    parser.add_argument("--check-records", action="store_true",
                        help="report which arms have a recording that still "
                             "describes this tree, and which are owed a "
                             "sweep. Needs no API key and spends nothing.")
    parser.add_argument("--list-arms", action="store_true")
    parser.add_argument("--comparison", action="store_true",
                        help="regenerate the Phase 5 grid from the records "
                             "named in the config and inject it into every "
                             "document that publishes it. With --check, diff "
                             "instead of writing. Needs no API key.")
    parser.add_argument("--rejudge", metavar="RECORD",
                        help="re-run the judge over a recorded sweep with the "
                             "current prompts and payload, without re-running "
                             "the agent. A fresh measurement, not a recount: "
                             "it stamps rejudged_at and prints what moved.")
    parser.add_argument("--rescore", metavar="RECORD",
                        help="recompute the deterministic figures of a "
                             "recorded sweep with the current scoring, from "
                             "what the record already holds. Judged verdicts "
                             "are kept: re-judging is a new measurement.")
    parser.add_argument("--stamp", default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    if args.rejudge:
        return rejudge(args.rejudge, config)

    if args.rescore:
        global args_config_path
        args_config_path = args.config
        return rescore(args.rescore, config)

    if args.write_prompts or args.check_prompts:
        return write_prompts(config, check=args.check_prompts)

    if args.comparison:
        return comparison(config, check=args.check)

    if args.check_records:
        return check_records(config, args.config)

    if args.list_arms:
        for arm in config["arms"]:
            print(f"{arm['label']:<24} {arm['index']:<24} "
                  f"{arm.get('system_prompt') or 'the spec prompt'}")
            if arm.get("description"):
                print(f"  {arm['description']}")
        return 0

    arm = pick_arm(config, args.arm)
    with open(DATASET) as handle:
        dataset = yaml.safe_load(handle)
    cases = select_cases(dataset, args.cases, args.limit)

    if args.dry_run:
        spec = spec_document(config["spec"])
        print(f"arm {arm['label']}: {len(cases)} case(s) against "
              f"{arm['index']}, agent {spec['intelligence']['model']}, "
              f"prompt {arm.get('system_prompt') or config['spec']}")
        judge = config["judge"]
        print(f"adapter on port {spec_port(spec, config['spec'])}, "
              f"judge {judge['model']} through "
              f"{judge.get('transport', 'anthropic')}, "
              f"{judge.get('concurrency', 4)} lanes")
        for case in cases:
            expects = ("precedent exists"
                       if case["expect"]["precedent_exists"]
                       else "no precedent")
            print(f"  {case['id']:<4} {case['group']:<13} "
                  f"as_of {case['as_of']}  {expects}")
        print("\nnothing was run and nothing was spent.")
        return 0

    stamp = args.stamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"{arm['label']}: {len(cases)} case(s), one live oa run each")
    result = run_arm(config, arm, cases, stamp, judged=not args.no_judge)

    os.makedirs(RESULTS, exist_ok=True)
    slug = stamp.replace(":", "").replace("-", "")
    out = os.path.join(RESULTS, f"{arm['label']}-{slug}.json")
    with open(out, "w") as handle:
        json.dump(result, handle, indent=2, sort_keys=False)
        handle.write("\n")
    table = os.path.join(RESULTS, f"{arm['label']}.md")
    with open(table, "w") as handle:
        handle.write(markdown(result))

    summary = result["deterministic"]
    print()
    for name in ("false_precedent_rate", "no_precedent_accuracy",
                 "false_refusal_rate", "groundedness_log", "agent_reach"):
        block = summary[name]
        print(f"  {name:<22} {pct(block['value']):>6} "
              f"({block['numerator']}/{block['denominator']})")
    if result["judged"]:
        for name in ("groundedness_judge", "divergence_quality"):
            block = result["judged"][name]
            print(f"  {name:<22} {pct(block['value']):>6} "
                  f"({block['numerator']}/{block['denominator']}), judged")
    print(f"  failures               {summary['failures']['total']}"
          f"/{summary['cases']}")
    print(f"\nwrote {out}\nwrote {table}")
    return 0



# --------------------------------------------------------------------------
# The Phase 5 comparison grid
# --------------------------------------------------------------------------
#
# Generated, and injected into the documents that publish it. Every other
# number in this repo is generated with a check that fails on drift, and this
# grid was the exception: hand-typed into README.md and evals/README.md from
# three JSON files nobody was going to re-read. It had already been wrong once,
# an unrelated-claims figure typed as 6/22 where the record says 3/22, and a
# groundedness_log of 190/190 left in prose after the dedup made it 138.
#
# The records themselves are not regenerable, which is what makes this safe:
# they are committed files, so a table derived from them is a function of
# checked-in artefacts exactly like the retrieval tables, and CI can diff it.

MARK_START = "<!-- judgement-comparison:start -->"
MARK_END = "<!-- judgement-comparison:end -->"

PUBLISHED_IN = ["README.md", "evals/README.md"]


def _fraction(block):
    if not block or block.get("numerator") is None:
        return "-"
    return f"{block['numerator']}/{block['denominator']}"


def comparison_grid(records):
    """The Phase 5 grid, deterministic and judged kept apart."""
    labels = [r["label"] for r in records]
    dets = [r["deterministic"] for r in records]
    judged = [r.get("judged") or {} for r in records]

    rows = [
        ("`false_precedent_rate`", "claims offered", "false_precedent_rate"),
        ("`applies_omission_rate`", "applies documents returned to the agent",
         "applies_omission_rate"),
        ("`no_precedent_accuracy`", "cases with no precedent",
         "no_precedent_accuracy"),
        ("`false_refusal_rate`", "answerable cases", "false_refusal_rate"),
        ("`groundedness_log`", "cited passage ids", "groundedness_log"),
        ("`agent_reach`", "(case, relevant document) pairs", "agent_reach"),
    ]
    head = " | ".join(labels)
    lines = [
        MARK_START,
        "",
        "| measured by code | unit | " + head + " |",
        "| --- | --- | " + " | ".join("---" for _ in labels) + " |",
    ]
    for name, unit, key in rows:
        cells = " | ".join(_fraction(d.get(key)) for d in dets)
        lines.append(f"| {name} | {unit} | {cells} |")
    lines.append(
        "| claims understated | claims offered | "
        + " | ".join(f"{d['understated_claims']['count']}/"
                     f"{d['understated_claims']['of']}" for d in dets) + " |")
    lines.append(
        "| claims on documents not called relevant | claims offered | "
        + " | ".join(f"{d['unrelated_claims']['count']}/"
                     f"{d['unrelated_claims']['of']}" for d in dets) + " |")
    lines.append(
        "| searches issued | calls on the surface | "
        + " | ".join(f"{d['hygiene']['queries_per_case']['issued']}, median "
                     f"{d['hygiene']['queries_per_case']['median']}"
                     for d in dets) + " |")
    lines.append(
        "| p50 / p95 | one recall | "
        + " | ".join(f"{d['latency_ms']['p50'] / 1000:.1f}s / "
                     f"{d['latency_ms']['p95'] / 1000:.1f}s" for d in dets)
        + " |")

    lines += [
        "",
        "Applicability offered: "
        + "; ".join(
            f"{label} " + ", ".join(f"`{w}` {n}" for w, n in sorted(
                (d.get("applicability_offered") or {}).items(),
                key=lambda kv: -kv[1]))
            for label, d in zip(labels, dets))
        + ". `false_precedent_rate` fires only on `applies`.",
        "",
        "| judged by " + (judged[0].get("model") or "a model") + " via "
        + (judged[0].get("transport") or "an unrecorded transport")
        + (", no file tools"
           if judged[0].get("transport") == "anthropic"
           else ", an agent behind a mount namespace")
        + ", " + (judged[0].get("sampling") or "sampling unstated")
        + " | " + head + " |",
        "| --- | " + " | ".join("---" for _ in labels) + " |",
        "| `groundedness_judge` | "
        + " | ".join(_fraction(j.get("groundedness_judge")) for j in judged)
        + " |",
        "| `divergence_quality` | "
        + " | ".join(_fraction(divergence_by_case(j)) for j in judged)
        + " |",
        "",
    ]
    # The selection effect behind the judged rows, from the records rather
    # than from prose: a near miss never offered cannot fail its divergence.
    notes = []
    for label, j in zip(labels, judged):
        block = j.get("divergence_quality") or {}
        missing = block.get("not_offered") or []
        if missing:
            notes.append(f"{label} never offered the diverging record on "
                         + ", ".join(f"`{c}`" for c in missing))
    if notes:
        lines += ["Both judged rates are scored over what each run offered, so "
                  "offering less can raise them: " + "; ".join(notes) + ".",
                  ""]
    lines += [
        f"Generated by `python3 evals/judgement.py --comparison` from "
        f"{len(records)} records: "
        + ", ".join(f"`{r['label']}` recorded {r['recorded_at']}"
                    for r in records)
        + ". Do not hand-edit either copy: `--comparison --check` diffs this "
          "block in every file that publishes it.",
        MARK_END,
    ]
    return "\n".join(lines)


def inject(path, block, check):
    """Replace the marked region in a published document."""
    with open(path) as handle:
        current = handle.read()
    start, end = current.find(MARK_START), current.find(MARK_END)
    if start == -1 or end == -1:
        raise SystemExit(
            f"{path} has no judgement-comparison markers. A document that "
            f"publishes this grid keeps it inside {MARK_START} ... "
            f"{MARK_END} so it can be regenerated and diffed.")
    updated = current[:start] + block + current[end + len(MARK_END):]
    if check:
        return updated == current
    if updated != current:
        with open(path, "w") as handle:
            handle.write(updated)
    return True


def comparison(config, check):
    paths = config.get("comparison") or []
    if len(paths) < 2:
        raise SystemExit(
            "config has no `comparison` list naming the records the grid is "
            "generated from. Two or more, in column order.")
    records = []
    for path in paths:
        with open(path) as handle:
            records.append(json.load(handle))
    for record in records:
        if record.get("mode") != "judgement":
            raise SystemExit(f"{record.get('label')} is not a judgement record")
    # The same list --compare refuses on, imported rather than restated: a
    # grid checking three pins while the delta tool checks twelve is a CI job
    # approving a table the comparison would refuse.
    from runner import judgement_index_mismatch, judgement_mismatch
    clash = judgement_index_mismatch(records)
    if clash:
        path, fingerprints = clash
        raise SystemExit(
            f"two of these records name {path} and the file differed between "
            f"them: {', '.join(fingerprints)}. A column crediting a prompt "
            f"would also be carrying a rebuilt index.")
    mismatch = judgement_mismatch(records)
    if mismatch:
        label, path, seen = mismatch
        print(f"these records do not share a {label} ({path}), so one grid "
              f"cannot hold them:")
        for name, value in seen:
            print(f"  {name}: {str(value)[:70]}")
        raise SystemExit(
            "rescore or re-record before publishing a comparison.")

    # Arm isolation, which a grid implies by putting columns side by side.
    # Every column after the first must differ from it in at most one input,
    # or the reader is invited to attribute a difference to something no
    # record varies alone.
    first = records[0]["arm"]
    for record in records[1:]:
        changed = [key for key in ("index", "system_prompt")
                   if record["arm"].get(key) != first.get(key)]
        if len(changed) > 1:
            raise SystemExit(
                f"{record['label']} differs from {records[0]['label']} in "
                f"{' and '.join(changed)}. A column that moves two inputs at "
                f"once has no reading, and putting it in the grid invites "
                f"one.")

    # The grid renders each record's stored deterministic block. If the
    # scoring has moved since a record was scored, that block is stale and
    # this would republish it while CI stayed green: the check would be
    # verifying that one stale table matches another. Refused here, where the
    # remedy is free. Sol found it at the gate.
    scoring_now = file_fingerprint(os.path.abspath(__file__))
    stale_scores = [r["label"] for r in records
                    if (r.get("scorer") or {}).get("fingerprint") != scoring_now]
    if stale_scores:
        print("these records were scored by a different version of "
              "evals/judgement.py than this tree has: "
              + ", ".join(stale_scores))
        print("  python3 evals/judgement.py --rescore <record>")
        if check:
            return 1
        raise SystemExit("rescore before publishing a grid from them.")

    block = comparison_grid(records)
    path = os.path.join(RESULTS, "judgement-comparison.md")
    body = ("# Phase 5, three arms\n\nGenerated by `evals/judgement.py "
            "--comparison`. Do not hand-edit.\n\n" + block + "\n")

    # The per-arm tables are derived from the same records and were checked by
    # nothing, so a rescore of an older record, or a hand edit, stayed green
    # while the grid beside them was diffed. Same treatment.
    per_arm = [(os.path.join(RESULTS, f"{r['label']}.md"), markdown(r))
               for r in records]

    if check:
        current = open(path).read() if os.path.exists(path) else ""
        stale = [] if current == body else [path]
        stale += [p for p in PUBLISHED_IN if not inject(p, block, check=True)]
        stale += [table for table, fresh in per_arm
                  if (open(table).read() if os.path.exists(table) else "")
                  != fresh]
        if stale:
            print("judgement tables derived from the records have drifted: "
                  + ", ".join(stale))
            print("  python3 evals/judgement.py --comparison")
            return 1
        print("judgement tables are current: "
              + ", ".join([path] + PUBLISHED_IN
                          + [table for table, _ in per_arm]))
        return 0
    os.makedirs(RESULTS, exist_ok=True)
    with open(path, "w") as handle:
        handle.write(body)
    for published in PUBLISHED_IN:
        inject(published, block, check=False)
    for table, fresh in per_arm:
        with open(table, "w") as handle:
            handle.write(fresh)
    print(f"wrote {path}, the marked block in " + ", ".join(PUBLISHED_IN)
          + ", and " + ", ".join(table for table, _ in per_arm))
    return 0



def rejudge(record_path, config):
    """Re-run the judge over a recorded sweep, without re-running the agent.

    The two halves of a record cost differently and fail differently. The
    agent runs are the expensive half and cannot be reproduced; the judged
    half is cheap, and when the question put to the judge changes, the old
    verdicts answer a question nobody is asking any more. --rescore recounts
    and never re-judges, for the good reason that re-judging is a fresh
    measurement rather than a recount. This is that fresh measurement, made
    explicit: it stamps rejudged_at, records the fingerprint of the code that
    produced the new verdicts, and prints what moved.

    Needs the API key and the arm's index served, because a claim is judged
    against the text of the passages it cites.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key and config["judge"].get("transport", "anthropic") == "anthropic":
        raise SystemExit("ANTHROPIC_API_KEY is not set and the configured "
                         "judge transport is the metered API. Set the key, or "
                         "configure transport: cursor, which needs only "
                         "CURSOR_API_KEY.")
    with open(record_path) as handle:
        result = json.load(handle)
    if result.get("mode") != "judgement":
        raise SystemExit(f"{record_path} is not a judgement record")

    with open(DATASET) as handle:
        dataset = yaml.safe_load(handle)
    if dataset_fingerprint(DATASET) != result["dataset"]["fingerprint"]:
        raise SystemExit(
            "the dataset has changed since this sweep was recorded, and the "
            "divergence judge is scored against it. Re-run the arm.")
    by_id = {c["id"]: c for c in dataset["cases"]}
    cases = [by_id[i] for i in result["dataset"]["ids"]]
    records = [{k: v for k, v in entry.items() if k != "score"}
               for entry in result["per_case"]]
    scores = {r["case"]: score_run(by_id[r["case"]], r) for r in records}

    # A passage id is chunker|source_uri|heading_path|ordinal, so it survives
    # an edit to the text underneath it. Serving a rebuilt index would judge
    # stored claims against passages the agent never saw, and the record would
    # keep the old corpus and index metadata while it happened.
    served = file_fingerprint(result["index"])
    if served != result.get("index_fingerprint"):
        raise SystemExit(
            f"{result['index']} has been rebuilt since this sweep: the record "
            f"names {str(result.get('index_fingerprint'))[:16]} and the file "
            f"is {served[:16]}. Passage ids survive a text edit, so judging "
            f"against it would score claims on passages the agent never saw.")

    spec = spec_document(config["spec"])
    port = spec_port(spec, config["spec"])
    # A fresh checkout has no .logs: it is gitignored, and only a sweep
    # creates it. Without this the advertised remedy fails opening a file
    # before it judges anything.
    log_dir = os.path.join(RESULTS, ".logs")
    os.makedirs(log_dir, exist_ok=True)
    proc = start_adapter(result["index"], port,
                         log_path=os.path.join(
                             log_dir, f"rejudge-{result['label']}.log"))
    try:
        before = result.get("judged") or {}
        fresh = judge_run(config, records, scores, cases, port, key)
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    scored = (fresh["groundedness_judge"]["denominator"]
              + fresh["divergence_quality"]["denominator"])
    if not scored:
        raise SystemExit(
            "every judge call in this round failed, so there is nothing to "
            "record. The previous verdicts are left in place rather than "
            "overwritten with an empty round: a failed run is not a "
            "measurement of anything.\n"
            f"  first error: "
            f"{((fresh['groundedness_judge'].get('errors') or [{}])[0].get('verdict') or {}).get('error', 'unknown')[:200]}")

    for name in ("groundedness_judge", "divergence_quality"):
        was, now = before.get(name) or {}, fresh[name]
        print(f"  {name}: {pct(was.get('value'))} "
              f"({was.get('numerator')}/{was.get('denominator')}) -> "
              f"{pct(now['value'])} ({now['numerator']}/{now['denominator']})")
    # Every judging this record has had, kept. Overwriting in place left the
    # published claim that re-judging moves two to four claims resting on
    # prose and commit messages, because only the last round survived in the
    # artefact. A rate whose variance is part of the finding has to carry its
    # own rounds. Sol found that at the gate.
    history = list(result.get("judgings") or [])
    if before:
        history.append({
            "at": result.get("rejudged_at") or result.get("recorded_at"),
            "scorer_fingerprint": before.get("scorer_fingerprint"),
            "model": before.get("model"),
            "temperature": before.get("temperature"),
            "max_tokens": before.get("max_tokens"),
            "transport": before.get("transport", "anthropic"),
            "sampling": before.get("sampling"),
            "pace": before.get("pace"),
            # The proof, not just the configuration. A round whose figures are
            # cited has to carry the evidence that the corpus was absent when
            # it was produced, and archiving the transport while dropping this
            # left exactly the rounds the write-up quotes unable to show it.
            # None is a real answer for the metered transport, which has no
            # file tools, and for a round that predates the namespace.
            "isolation": before.get("isolation"),
            "cli_version": before.get("cli_version"),
            "effort": before.get("effort"),
            "prompts": {name: (before.get("prompts") or {})
                        .get(name, {}).get("fingerprint")
                        for name in ("groundedness", "divergence")},
            # Verdicts, not just counts. A round archived as three numbers
            # cannot support a claim about why it differs from another round,
            # and the reason the two judge families disagree is one of this
            # change's findings. The records grow; re-judging is rare and the
            # evidence is the point of keeping them.
            "groundedness_judge": {
                k: (before.get("groundedness_judge") or {}).get(k)
                for k in ("value", "numerator", "denominator", "verdicts")},
            "divergence_quality": {
                k: (before.get("divergence_quality") or {}).get(k)
                for k in ("value", "numerator", "denominator", "verdicts")},
        })
    result["judgings"] = history
    result["judged"] = fresh
    result["rejudged_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Rejudging recomputes the deterministic half as well, because the claims
    # handed to the judge come from it. So it owns that provenance too: a
    # record naming one scorer fingerprint at the top and figures produced by
    # another underneath is the same defect as one fingerprint covering both
    # halves. Stamped like a rescore, because that is what this half is.
    result["per_case"] = [{**r, "score": scores[r["case"]]} for r in records]
    result["deterministic"] = aggregate(cases, records, scores)
    result["rescored_at"] = result["rejudged_at"]
    result["scorer"] = {
        "path": os.path.relpath(os.path.abspath(__file__)),
        "fingerprint": file_fingerprint(os.path.abspath(__file__)),
        "scope": "the deterministic figures. The judged half carries its own "
                 "fingerprint under judged.",
    }
    with open(record_path, "w") as handle:
        json.dump(result, handle, indent=2, sort_keys=False)
        handle.write("\n")
    print(f"rejudged {record_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
