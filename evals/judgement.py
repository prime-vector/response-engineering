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

  A record from this mode is not a regenerable artefact. Two runs of the same
  arm differ, so there is no --check here and nothing in CI diffs the table.
  It carries a timestamp, the spec and prompt it ran, and the model that ran
  it, because those are what a reader would otherwise have to take on trust.

Deterministic and judged metrics are reported apart, always. false_precedent_
rate, no_precedent_accuracy, false_refusal_rate and groundedness_log are read
off the typed output and the adapter log by code: they are as reliable as the
ground truth. groundedness_judge and divergence_quality are a model's opinion
of a model, scored at temperature 0 with the prompt committed beside this
file. Mixing them into one table would launder the second as the first.

Stdlib plus PyYAML, like runner.py and validate.py. The judge calls the
Messages API over raw HTTP rather than through the anthropic SDK, so that
this directory keeps the dependency footprint it documents; the agent runs
through `oa`, which brings its own.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
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

API_URL = "https://api.anthropic.com/v1/messages"
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
        print("warning: cannot locate oa's interpreter; contract validation "
              "is unverified for this run.", file=sys.stderr)
        return oa
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

def cited_ids(precedent):
    ref = precedent.get("incident_ref") or {}
    ids = list(precedent.get("grounded_in") or [])
    if ref.get("passage_id"):
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
    reached = {uri.split("#")[0] for uri in hits.values()}

    out = {
        "precedent_exists": bool(expect["precedent_exists"]),
        "refused": None,
        "claims": [],
        "citations": {"total": 0, "in_returned_set": 0, "invented": []},
        "must_not_cite_violations": [],
        "query_hygiene_violations": [],
        "queries_issued": [],
        "coverage_called": "coverage_describe" in record["surface"]["calls"],
        "searches": len([c for c in record["surface"]["calls"]
                         if c == "precedent_search"]),
        "reach": {"relevant": len(relevant),
                  "reached": len(relevant & reached),
                  "missed": sorted(relevant - reached)},
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
    out["queries_reported_but_not_issued"] = (
        len(queries) - len(searched) if len(queries) > len(searched) else 0)

    for precedent in output.get("precedents") or []:
        ref = precedent.get("incident_ref") or {}
        uri = ref.get("source_uri") or ""
        offered = precedent.get("applicability")
        expected = truth.get(uri)
        ids = cited_ids(precedent)
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
        })
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

def call_judge(judge, system, payload, key):
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
    judge = config["judge"]
    with open(judge["groundedness_prompt"]) as handle:
        grounding_system = handle.read()
    with open(judge["divergence_prompt"]) as handle:
        divergence_system = handle.read()
    by_id = {c["id"]: c for c in cases}

    verdicts = {"groundedness": [], "divergence": []}
    usage_total = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def account(usage):
        usage_total["calls"] += 1
        usage_total["input_tokens"] += usage.get("input_tokens", 0)
        usage_total["output_tokens"] += usage.get("output_tokens", 0)

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
            passages = []
            for passage_id in grounded:
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
            verdict, usage = call_judge(judge, grounding_system, {
                "incident": {"symptom": case["symptom"].strip(),
                             "as_of": case["as_of"]},
                "precedent_claim": {
                    "source_uri": claim["source_uri"],
                    "applicability": claim["offered"],
                    "confidence": claim["confidence"],
                    "divergence": claim["divergence"],
                },
                "cited_passages": passages,
            }, key)
            account(usage)
            verdicts["groundedness"].append({
                "case": record["case"], "document": claim["source_uri"],
                "verdict": verdict})

        if case["group"] != "near_miss":
            continue
        wanted = case["expect"].get("divergence_names") or []
        for claim in scores[record["case"]]["claims"]:
            if claim["truth"] not in ("partial", "superseded"):
                continue
            verdict, usage = call_judge(judge, divergence_system, {
                "incident": {"symptom": case["symptom"].strip(),
                             "missing_evidence": case.get("missing_evidence")
                             or []},
                "precedent_document": claim["source_uri"],
                "distinguishing_factors": wanted,
                "divergence_text": claim["divergence"],
            }, key)
            account(usage)
            verdicts["divergence"].append({
                "case": record["case"], "document": claim["source_uri"],
                "verdict": verdict})

    def rate(entries, field):
        scored = [e for e in entries if "error" not in e["verdict"]]
        good = [e for e in scored if e["verdict"].get(field) is True]
        return {
            "value": round(len(good) / len(scored), 4) if scored else None,
            "numerator": len(good),
            "denominator": len(scored),
            "errors": [e for e in entries if "error" in e["verdict"]],
            "verdicts": entries,
        }

    near_miss_cases = [c["id"] for c in cases if c["group"] == "near_miss"]
    judged_cases = {e["case"] for e in verdicts["divergence"]}
    return {
        "model": judge["model"],
        "temperature": judge.get("temperature", 0),
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
        "scorer": {"path": os.path.relpath(os.path.abspath(__file__)),
                   "fingerprint": file_fingerprint(os.path.abspath(__file__))},
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
        "prompt and the model that produced it, and nothing checks it for "
        "drift.",
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
        metric_row("no_precedent_accuracy", summary["no_precedent_accuracy"]),
        metric_row("false_refusal_rate", summary["false_refusal_rate"]),
        metric_row("groundedness_log", summary["groundedness_log"]),
        metric_row("agent_reach", summary["agent_reach"]),
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
            f"A separate judge, {judged['model']} at temperature "
            f"{judged['temperature']}, with the prompts committed at "
            f"`{judged['prompts']['groundedness']['path']}` and "
            f"`{judged['prompts']['divergence']['path']}`. This is a model's "
            f"opinion of a model, reported apart from the table above so it "
            f"cannot be read as the same kind of number.",
            "",
            "| Metric | Value | Count | Denominator |",
            "| --- | --- | --- | --- |",
            metric_row("groundedness_judge", judged["groundedness_judge"]),
            metric_row("divergence_quality", judged["divergence_quality"]),
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
            f"{judged['usage']['output_tokens']} output tokens.",
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


def rescore(path):
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
    result["deterministic"] = aggregate(cases, records, scores)
    result["per_case"] = [{**r, "score": scores[r["case"]]} for r in records]
    result["rescored_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result["scorer"] = {
        "path": os.path.relpath(os.path.abspath(__file__)),
        "fingerprint": file_fingerprint(os.path.abspath(__file__)),
    }
    with open(path, "w") as handle:
        json.dump(result, handle, indent=2, sort_keys=False)
        handle.write("\n")
    table = os.path.join(RESULTS, f"{result['label']}.md")
    with open(table, "w") as handle:
        handle.write(markdown(result))
    print(f"rescored {path} and rewrote {table}")
    return 0


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
    parser.add_argument("--check-prompts", action="store_true",
                        help="regenerate every derived arm prompt and fail if "
                             "it has drifted. Needs no API key, so CI can "
                             "run it.")
    parser.add_argument("--list-arms", action="store_true")
    parser.add_argument("--rescore", metavar="RECORD",
                        help="recompute the deterministic figures of a "
                             "recorded sweep with the current scoring, from "
                             "what the record already holds. Judged verdicts "
                             "are kept: re-judging is a new measurement.")
    parser.add_argument("--stamp", default=None)
    args = parser.parse_args()

    if args.rescore:
        return rescore(args.rescore)

    config = load_config(args.config)
    if args.write_prompts or args.check_prompts:
        return write_prompts(config, check=args.check_prompts)

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
        print(f"adapter on port {spec_port(spec, config['spec'])}, "
              f"judge {config['judge']['model']} at temperature "
              f"{config['judge'].get('temperature', 0)}")
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


if __name__ == "__main__":
    sys.exit(main())
