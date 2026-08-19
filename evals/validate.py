#!/usr/bin/env python3
"""
Integrity check for evals/dataset.yaml.

The dataset is hand-authored, because ground truth is a judgement and a
dataset generated from the retriever measures only that the retriever agrees
with itself. Hand-authored is also how a dataset rots: the corpus moves, a
document gets a date, and a case that used to test the time bound quietly
stops testing anything while still passing.

So every claim in the dataset that the corpus can settle is asserted here,
against both indexes, and drift is a failure rather than a stale comment.

    python3 evals/validate.py
    python3 evals/validate.py --index corpus/index.fixed.json

This is not retrieval quality measurement, and it deliberately does not check
that the documents a case calls `relevant` are the ones the surface returns.
That number is precedent_hit_rate, it is what the runner reports, and
asserting it here would make the dataset grade itself: any case the retriever
missed would be "fixed" by editing the ground truth. Coverage is printed as an
observation instead, so a collapse is visible without being enforced.

Stdlib plus PyYAML, same shape as corpus/eval.py: the mock is started on a
spare port and driven over JSON-RPC, so what is checked is the surface rather
than an import of its internals.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import yaml

PORT = 8527          # not 8426, and not eval.py's 8526: CI runs both
DATASET = "evals/dataset.yaml"


def rpc(name, args):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": args}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}", data=body,
                                 headers={"Content-Type": "application/json"})
    payload = json.loads(urllib.request.urlopen(req, timeout=10).read())
    result = payload["result"]
    text = result["content"][0]["text"]
    if result.get("isError"):
        return {"_fault": text}
    return json.loads(text)


def search(case, limit=8):
    """The canonical probe. limit 8 matches the demos, so a case that turns on
    what fits under the limit is measured at the limit it will be run at."""
    return rpc("precedent_search", {"symptom_text": case["query"],
                                    "before": case["as_of"], "limit": limit})


def uris(result):
    return [p["source_uri"] for p in result.get("passages", [])]


def load_corpus():
    with open("corpus/manifest.yaml") as handle:
        manifest = yaml.safe_load(handle)
    return {d["source_uri"]: d for d in manifest["documents"]}


def named_uris(case):
    """Every source_uri a case mentions, wherever it mentions it."""
    expect = case["expect"]
    out = list(expect.get("relevant") or [])
    out += list((expect.get("applicability") or {}).keys())
    for key in ("must_not_cite", "must_be_retrieved", "unreachable_by_bound"):
        out += list(expect.get(key) or [])
    out += list((expect.get("must_not_cite_reason") or {}).keys())
    return out


# --------------------------------------------------------------------------
# Checks. Each returns a list of failure strings, empty when the case holds.
# --------------------------------------------------------------------------

def check_uris_exist(case, corpus):
    """A case naming a document the corpus no longer holds is not a failing
    case, it is a case that stopped being about anything."""
    missing = sorted({u for u in named_uris(case) if u not in corpus})
    return [f"names documents not in the corpus: {missing}"] if missing else []


def check_applicability_covers_relevant(case):
    """Truth per document is what false_precedent_rate is computed against. A
    relevant document with no applicability truth is a document the metric
    would silently skip."""
    expect = case["expect"]
    relevant = set(expect.get("relevant") or [])
    truth = set((expect.get("applicability") or {}).keys())
    gaps = sorted(relevant - truth)
    extra = sorted(truth - relevant)
    out = []
    if gaps:
        out.append(f"relevant with no applicability truth: {gaps}")
    if extra:
        out.append(f"applicability truth for documents not marked relevant: {extra}")
    return out


def check_refusal_has_no_relevant(case):
    """precedent_exists false and a relevant document is a contradiction: the
    case is asserting both that nothing applies and that something does."""
    expect = case["expect"]
    if not expect["precedent_exists"] and (expect.get("relevant")):
        return ["precedent_exists is false but relevant documents are named"]
    if expect["precedent_exists"] and not expect.get("relevant"):
        return ["precedent_exists is true but no relevant document is named"]
    return []


def check_unreachable_by_bound(case, corpus):
    """The claim that a document is out of reach at this bound is checked
    against the document's own recorded_at, not assumed from its id."""
    out = []
    bound = str(case["as_of"])[:10]
    for uri in case["expect"].get("unreachable_by_bound") or []:
        recorded = corpus[uri]["recorded_at"]
        if not str(recorded) > bound:
            out.append(f"{uri} is claimed unreachable at {bound} but is "
                       f"recorded {recorded}")
    return out


def check_reachable(case, corpus):
    """The mirror of the above, and the one that actually rots. A relevant
    document recorded after the bound can never be retrieved, so the case
    would score an unreachable miss against the retriever forever."""
    out = []
    bound = str(case["as_of"])[:10]
    for uri in case["expect"].get("relevant") or []:
        recorded = corpus[uri]["recorded_at"]
        if str(recorded) > bound:
            out.append(f"{uri} is named relevant at {bound} but is not "
                       f"recorded until {recorded}")
    return out


def check_must_not_cite_status(case, corpus):
    """A document is barred from grounding a claim for a reason. Either the
    corpus shows it, meaning the record is a draft, or the case has to argue
    it in must_not_cite_reason.

    This used to accept any `expect.note` as the argument, which let a note
    written about something else waive the check entirely: a filed document
    could be added to the barred list and pass on the strength of a comment
    that never mentioned it. The reason is now per-uri and cannot be borrowed.
    """
    out = []
    barred = case["expect"].get("must_not_cite") or []
    reasons = case["expect"].get("must_not_cite_reason") or {}
    for uri in barred:
        if corpus[uri].get("record_status") == "draft":
            continue
        if str(reasons.get(uri, "")).strip():
            continue
        out.append(f"{uri} is filed, and must_not_cite_reason does not say "
                   f"why it cannot ground a claim")
    stray = sorted(set(reasons) - set(barred))
    if stray:
        # A reason outliving the entry it justified means the list moved and
        # the argument did not.
        out.append(f"must_not_cite_reason argues for documents that are not "
                   f"barred: {stray}")
    return out


def check_floor(case, index_label):
    """Cases that turn on the floor state what it does, per index, because the
    two chunkers cross it differently and that difference is the measurement."""
    stated = case["expect"].get("floor_cleared")
    if stated is None:
        return []
    if index_label not in stated:
        return []
    result = search(case)
    actual = result["cleared_floor"]
    if actual != stated[index_label]:
        return [f"cleared_floor is {actual} against {index_label}, "
                f"case states {stated[index_label]}"]
    return []


def check_candidates(case):
    stated = case["expect"].get("candidates_considered")
    if stated is None:
        return []
    result = search(case)
    actual = result["candidates_considered"]
    if actual != stated:
        return [f"candidates_considered is {actual}, case states {stated}"]
    return []


def check_must_be_retrieved(case):
    """Guards against a case going vacuous. If the trap stops being returned,
    a case about rejecting it proves nothing and should fail loudly rather
    than pass quietly, which is how the grounding demo's assertion went hollow
    once the distractors widened the scoring band."""
    wanted = case["expect"].get("must_be_retrieved") or []
    if not wanted:
        return []
    returned = set(uris(search(case)))
    missing = sorted(set(wanted) - returned)
    return [f"must_be_retrieved not in the returned set: {missing}"] if missing else []


def check_novel_refuses(case):
    """A novel case whose query retrieves something is not a refusal case any
    more, it is a judgement call, and the whole point of choosing distant
    vocabulary was to keep it from becoming one.

    Documents the case already names as must_not_cite are allowed through:
    those cases refuse on record status after retrieval, not on the floor.
    """
    if case["expect"]["precedent_exists"]:
        return []
    allowed = set(case["expect"].get("must_not_cite") or [])
    returned = set(uris(search(case)))
    leaked = sorted(returned - allowed)
    if leaked:
        return [f"a case with no applicable precedent retrieves {leaked}; "
                f"the refusal is no longer the floor's doing"]
    return []


def check_query_hygiene(case):
    """The canonical query has to obey the rule the agent is scored against.
    A dataset probe carrying an entity id would be measuring the retriever on
    a query the spec forbids."""
    out = []
    query = case["query"].lower()
    for banned in case["expect"].get("queries_must_not_contain") or []:
        if banned.lower() in query:
            out.append(f"the canonical query contains the banned substring "
                       f"{banned!r}")
    return out


def observe_hit_coverage(cases):
    """Reported, never asserted. See the module docstring: this is the number
    the runner measures, and enforcing it here would let a retrieval failure
    be repaired by editing the ground truth."""
    scored = [c for c in cases if c["expect"].get("relevant")
              and not c["expect"].get("floor_cleared")]
    hits = total = 0
    misses = []
    for case in scored:
        returned = set(uris(search(case)))
        for uri in case["expect"]["relevant"]:
            total += 1
            if uri in returned:
                hits += 1
            else:
                misses.append(f"{case['id']}:{uri.replace('corpus://', '')}")
    return hits, total, misses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default="corpus/index.json")
    args = parser.parse_args()
    index_label = "fixed" if "fixed" in args.index else "heading"

    with open(DATASET) as handle:
        dataset = yaml.safe_load(handle)
    cases = dataset["cases"]
    corpus = load_corpus()

    proc = subprocess.Popen(
        [sys.executable, "mock/adapter.py", "--surface", "precedent_archive",
         "--port", str(PORT), "--index", args.index],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                rpc("coverage_describe", {"before": "2026-03-17"})
                break
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.1)
        else:
            print("adapter did not come up")
            return 2

        print(f"dataset integrity, {len(cases)} cases, index {args.index} "
              f"({index_label})\n")

        failures = 0
        for case in cases:
            problems = []
            problems += check_uris_exist(case, corpus)
            if problems:
                # Everything below indexes into the corpus by uri.
                print(f"  FAIL  {case['id']}: {problems[0]}")
                failures += 1
                continue
            problems += check_refusal_has_no_relevant(case)
            problems += check_applicability_covers_relevant(case)
            problems += check_unreachable_by_bound(case, corpus)
            problems += check_reachable(case, corpus)
            problems += check_must_not_cite_status(case, corpus)
            problems += check_floor(case, index_label)
            problems += check_candidates(case)
            problems += check_must_be_retrieved(case)
            problems += check_novel_refuses(case)
            problems += check_query_hygiene(case)
            if problems:
                failures += 1
                print(f"  FAIL  {case['id']}: {problems[0]}")
                for extra in problems[1:]:
                    print(f"              {extra}")

        # Composition, asserted because docs/precedent-analyst.md fixes it and
        # a dataset that drifts under the minimum stops measuring refusal.
        novel = [c for c in cases if not c["expect"]["precedent_exists"]]
        near = [c for c in cases if c["group"] == "near_miss"]
        for label, got, want in (("no-precedent cases", len(novel), 8),
                                 ("near-miss cases", len(near), 4)):
            if got < want:
                print(f"  FAIL  composition: {got} {label}, the spec fixes a "
                      f"minimum of {want}")
                failures += 1

        ids = [c["id"] for c in cases]
        if len(ids) != len(set(ids)):
            print("  FAIL  composition: duplicate case ids")
            failures += 1
        if not 30 <= len(cases) <= 50:
            print(f"  FAIL  composition: {len(cases)} cases, the spec fixes "
                  f"30 to 50")
            failures += 1

        hits, total, misses = observe_hit_coverage(cases)
        print(f"\n  obs   canonical probe reaches {hits}/{total} relevant "
              f"documents at limit 8")
        if misses:
            print(f"        not reached: {', '.join(misses)}")
        print("        Observed, not asserted: this is precedent_hit_rate, "
              "the runner measures it,")
        print("        and enforcing it here would let the ground truth be "
              "edited to match a miss.")

        print(f"\n{len(cases) - failures}/{len(cases)} cases intact"
              if failures else f"\n{len(cases)}/{len(cases)} cases intact")
        return 1 if failures else 0
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
