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
import hashlib
import json
import os
import re
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


def fingerprint(corpus):
    """sha256 over every (source_uri, sha256) pair, sorted.

    Contents, not names. A document can be rewritten under the same uri, or a
    new one added, and every name a case cites still resolves while the
    judgement behind it no longer describes what is there.
    """
    pairs = sorted((uri, doc["sha256"]) for uri, doc in corpus.items())
    body = "\n".join(f"{uri} {sha}" for uri, sha in pairs)
    return hashlib.sha256(body.encode()).hexdigest()


def check_corpus_fingerprint(dataset, corpus):
    """The corpus this ground truth was judged against, exactly.

    Deliberately a failure rather than a warning. Re-reading the judgements is
    the work; --repin is the two seconds afterwards.
    """
    want = dataset.get("corpus_fingerprint")
    if not want:
        return ["the dataset names no corpus_fingerprint, so ground truth is "
                "pinned to nothing"]
    got = fingerprint(corpus)
    if got == want:
        return []
    out = [f"corpus fingerprint is {got[:16]}, dataset pinned to "
           f"{want[:16]}: the documents these judgements were made against "
           f"have changed"]
    count = dataset.get("corpus_document_count")
    if count is not None and count != len(corpus):
        out.append(f"document count is {len(corpus)}, dataset pinned to "
                   f"{count}")
    out.append("re-read the affected judgements in evals/RELEVANCE.md, then "
               "re-pin with: python3 evals/validate.py --repin")
    return out


def repin(dataset_path, corpus):
    """Rewrite the pin in place. Deliberately a separate, explicit act."""
    with open(dataset_path) as handle:
        text = handle.read()
    text = re.sub(r"^corpus_fingerprint: .*$",
                  f"corpus_fingerprint: {fingerprint(corpus)}",
                  text, count=1, flags=re.M)
    text = re.sub(r"^corpus_document_count: .*$",
                  f"corpus_document_count: {len(corpus)}",
                  text, count=1, flags=re.M)
    with open(dataset_path, "w") as handle:
        handle.write(text)


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


def covering_runbooks():
    return sorted(set(COVERING_PROCEDURE.values()))


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


def check_relevance_groups(cases):
    """Cases sharing a relevance_group are one incident seen one way, so their
    ground truth has to be identical.

    Grok's second review flagged this as residual: the rule was applied by hand
    and nothing stopped a later edit letting a01 and d02 disagree again, which
    is precisely how the first version of this dataset drifted. Making it
    mechanical is cheaper than remembering it.
    """
    out = []
    groups = {}
    for case in cases:
        name = case.get("relevance_group")
        if name:
            groups.setdefault(name, []).append(case)
    for name, members in sorted(groups.items()):
        first = members[0]
        for other in members[1:]:
            for field in ("relevant", "applicability"):
                a = first["expect"].get(field)
                b = other["expect"].get(field)
                if isinstance(a, list):
                    a, b = sorted(a or []), sorted(b or [])
                if a != b:
                    out.append(f"relevance_group {name}: {first['id']} and "
                               f"{other['id']} disagree on {field}")
    return out


# A runbook covers a signature type when the procedure is about that failure.
# Stated here rather than inferred, because the corpus does not encode it and
# guessing it from title words would be a checker that agrees with whoever
# named the file.
COVERING_PROCEDURE = {
    "host.memory.exhaustion": "corpus://runbooks/memory-pressure",
    "host.memory.pressure": "corpus://runbooks/memory-pressure",
    "container.memory.limit": "corpus://runbooks/container-resource-limits",
}


def check_covering_procedure(case, corpus):
    """Every case whose failure has a procedure in the archive either names it
    or argues why not.

    This check exists because the same defect was found in four consecutive
    reviews, one group at a time: the composite cluster, then the near misses,
    then the applies group, then record status. Each fix was correct and each
    was applied only where somebody happened to be looking. A rule enforced by
    attention gets exactly as far as the attention does.

    The worst instance was d01, which omitted the procedure AND declared
    precedent_exists false, so an agent citing the runbook correctly scored as
    a false precedent while a refusal scored as correct. A gold set can be
    wrong in the direction of over-refusal too, and nothing else here would
    have caught that.
    """
    signature = case["signature"].split(":")[0]
    runbook = COVERING_PROCEDURE.get(signature)
    if not runbook:
        return []
    if str(corpus[runbook]["recorded_at"]) > str(case["as_of"])[:10]:
        return []                      # not written yet at this bound
    if runbook in (case["expect"].get("relevant") or []):
        return []
    if str(case["expect"].get("covering_procedure_waived", "")).strip():
        return []
    return [f"{signature} is covered by {runbook}, which is in reach at this "
            f"bound and is neither named relevant nor waived in "
            f"covering_procedure_waived"]


def check_coverage(case):
    """What coverage_describe reports at this case's bound.

    A refusal cites coverage as proof it looked, so a case asserting the
    archive was nearly empty has to be able to show it. These were prose in
    `coverage_must_show` for three rounds, which meant nothing read them while
    the README claimed every corpus-settleable claim was asserted. Prose in a
    dataset is a comment; the field is now structured and checked.
    """
    expect = case["expect"].get("coverage_expect")
    if not expect:
        return []
    got = rpc("coverage_describe", {"before": case["as_of"]})
    out = []

    if "source_families" in expect:
        want = sorted(expect["source_families"])
        have = sorted(got.get("source_families") or [])
        if want != have:
            out.append(f"coverage source_families {have}, case expects {want}")
    if "document_count" in expect and got.get("document_count") != expect["document_count"]:
        out.append(f"coverage document_count {got.get('document_count')}, "
                   f"case expects {expect['document_count']}")
    if "max_document_count" in expect:
        count = got.get("document_count")
        if count is None or count > expect["max_document_count"]:
            out.append(f"coverage document_count {count}, case expects at "
                       f"most {expect['max_document_count']}")
    if expect.get("date_range_is_null") and got.get("date_range") is not None:
        out.append(f"coverage date_range is {got.get('date_range')!r}, case "
                   f"expects the bound to leave no documents")
    if "date_range_ends_on_or_before" in expect:
        rng = got.get("date_range") or ""
        end = rng.split(" to ")[-1] if rng else ""
        if not end or end > expect["date_range_ends_on_or_before"]:
            out.append(f"coverage date_range ends {end!r}, case expects on or "
                       f"before {expect['date_range_ends_on_or_before']}")
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


def check_scoring(case, index_label):
    """Figures a case states about its own probe: how much scored at all, and
    where a document landed in the returned order.

    These were prose in the intent text, which the header promised was checked
    and which nothing read. One had already rotted: g01 claimed the unstripped
    query clears the floor seven times, which is the fixed index's figure,
    while heading-aware gives nine. A number in a comment is a number nobody
    is holding to anything.
    """
    out = []
    expect = case["expect"]

    stated = expect.get("scoring_above_zero")
    if stated and index_label in stated:
        got = search(case)["total_scoring_above_zero"]
        if got != stated[index_label]:
            out.append(f"total_scoring_above_zero is {got} against "
                       f"{index_label}, case states {stated[index_label]}")

    for uri, rank in (expect.get("rank_of") or {}).items():
        returned = uris(search(case))
        if uri not in returned:
            out.append(f"rank_of names {uri}, which the probe does not return")
        elif returned.index(uri) + 1 != rank:
            out.append(f"{uri} is at rank {returned.index(uri) + 1} against "
                       f"{index_label}, case states {rank}")

    probe = expect.get("identity_probe")
    if probe and index_label in (probe.get("floor_cleared") or {}):
        got = rpc("precedent_search", {"symptom_text": probe["query"],
                                       "before": case["as_of"], "limit": 8})
        want = probe["floor_cleared"][index_label]
        if got["cleared_floor"] != want:
            out.append(f"identity probe clears the floor "
                       f"{got['cleared_floor']} times against {index_label}, "
                       f"case states {want}")
    return out


def check_candidates(case):
    stated = case["expect"].get("candidates_considered")
    if stated is None:
        return []
    result = search(case)
    actual = result["candidates_considered"]
    if actual != stated:
        return [f"candidates_considered is {actual}, case states {stated}"]
    return []


def check_barred_is_guarded(case):
    """A case that bars a document from grounding a claim, and whose own probe
    returns that document, has to say so in must_be_retrieved.

    Without it the case passes when the document stops being retrieved, and a
    test of "retrieved and correctly rejected" quietly becomes a test of
    nothing. d02 had this guard and the others did not, which is the same
    "applied where somebody was looking" pattern as the covering procedure.

    Limits, stated rather than papered over: this can only guard documents the
    canonical probe actually reaches. a03, a04 and g02 bar a document their own
    probe does not return, because the agent issues queries this dataset does
    not, and d02 is the case that holds the trap's reachability for all of
    them. If d02 ever stops returning it, that fails here and the others are
    known to be resting on it.
    """
    barred = set(case["expect"].get("must_not_cite") or [])
    if not barred:
        return []
    exempt = set(case["expect"].get("unreachable_by_bound") or [])
    guarded = set(case["expect"].get("must_be_retrieved") or [])
    returned = set(uris(search(case)))
    gap = sorted((barred & returned) - guarded - exempt)
    return [f"{u} is barred and returned by this case's own probe, but is not "
            f"in must_be_retrieved, so the case passes if it stops being "
            f"retrieved" for u in gap]


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


def observe_ungrouped_clusters(cases):
    """Cases that look like one incident but carry no relevance_group.

    Reported, never asserted. The grouping check only guards clusters somebody
    remembered to tag, which Grok's third review flagged as the residual: it
    cannot discover a cluster that was never tagged. Asserting on
    (as_of, signature) would be wrong, because a01 and g01 legitimately differ
    on the same bound and host when the evidence in view differs. So this
    surfaces candidates for a human to judge rather than deciding for them.
    """
    seen = {}
    for case in cases:
        if not case["expect"].get("relevant"):
            continue
        key = (str(case["as_of"])[:10], case["signature"])
        seen.setdefault(key, []).append(case)
    out = []
    for (bound, signature), members in sorted(seen.items()):
        if len(members) < 2:
            continue
        groups = {c.get("relevance_group") for c in members}
        sets = {tuple(sorted(c["expect"]["relevant"])) for c in members}
        if len(sets) > 1 and (None in groups or len(groups) > 1):
            out.append(f"{signature} at {bound}: "
                       + ", ".join(f"{c['id']}"
                                   f"{'' if c.get('relevance_group') else ' (untagged)'}"
                                   for c in members))
    return out


def observe_hit_coverage(cases):
    """Reported, never asserted. See the module docstring: this is the number
    the runner measures, and enforcing it here would let a retrieval failure
    be repaired by editing the ground truth."""
    # Every case with relevant documents, including a04 whose canonical query
    # is the reported symptom used whole and clears the floor zero times.
    #
    # a04 was excluded here, on the reasoning that a probe designed to retrieve
    # nothing should not be mixed with probes designed to retrieve. That was
    # the same fitting move this dataset spent four review rounds removing
    # elsewhere: a (case, document) pair goes uncounted because the query
    # cannot reach it, and the published figure rises without retrieval
    # improving. Its five misses are real misses of a real query. The
    # iterative reviewer endorsed the exclusion four times because the review
    # thread carried the justification for it; the pre-merge gate, reading
    # cold, called it what it was.
    scored = [c for c in cases if c["expect"].get("relevant")]
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
    parser.add_argument("--repin", action="store_true",
                        help="Re-pin corpus_fingerprint to the corpus as it "
                             "is now. Do this after re-reading the judgements "
                             "a corpus change affects, not instead of it.")
    args = parser.parse_args()
    index_label = "fixed" if "fixed" in args.index else "heading"

    with open(DATASET) as handle:
        dataset = yaml.safe_load(handle)
    cases = dataset["cases"]
    corpus = load_corpus()

    if args.repin:
        repin(DATASET, corpus)
        print(f"re-pinned to {fingerprint(corpus)[:16]}, "
              f"{len(corpus)} documents")
        return 0

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
        for problem in check_corpus_fingerprint(dataset, corpus):
            print(f"  FAIL  corpus: {problem}")
        if check_corpus_fingerprint(dataset, corpus):
            failures += 1

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
            problems += check_covering_procedure(case, corpus)
            problems += check_coverage(case)
            problems += check_scoring(case, index_label)
            problems += check_floor(case, index_label)
            problems += check_candidates(case)
            problems += check_must_be_retrieved(case)
            problems += check_barred_is_guarded(case)
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

        for problem in check_relevance_groups(cases):
            print(f"  FAIL  {problem}")
            failures += 1

        ids = [c["id"] for c in cases]
        if len(ids) != len(set(ids)):
            print("  FAIL  composition: duplicate case ids")
            failures += 1
        if not 30 <= len(cases) <= 50:
            print(f"  FAIL  composition: {len(cases)} cases, the spec fixes "
                  f"30 to 50")
            failures += 1

        clusters = observe_ungrouped_clusters(cases)
        if clusters:
            print("\n  obs   same bound and signature, different relevant sets:")
            for line in clusters:
                print(f"          {line}")
            print("        Legitimate when the evidence in view differs. "
                  "Checked by a human, not asserted:")
            print("        the grouping check cannot discover a cluster "
                  "nobody tagged.")

        hits, total, misses = observe_hit_coverage(cases)
        print(f"\n  obs   canonical probe reaches {hits}/{total} relevant "
              f"documents at limit 8")
        if misses:
            print(f"        not reached: {', '.join(misses)}")
        print("        Observed, not asserted: this is precedent_hit_rate, "
              "the runner measures it,")
        print("        and enforcing it here would let the ground truth be "
              "edited to match a miss.")
        print("        Includes a04, whose canonical query is the reported "
              "symptom used whole and")
        print("        reaches none of its five: a deliberate demonstration of "
              "dilution, and still")
        print("        five real misses. Excluding it would be the fitting "
              "move in miniature.")

        print(f"\n{len(cases) - failures}/{len(cases)} cases intact"
              if failures else f"\n{len(cases)}/{len(cases)} cases intact")
        return 1 if failures else 0
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
