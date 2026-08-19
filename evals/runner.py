#!/usr/bin/env python3
"""
Retrieval measurement for the Precedent Analyst.

    python3 evals/runner.py --config evals/config.yaml
    python3 evals/runner.py --index corpus/index.json --label heading-aware
    python3 evals/runner.py --compare evals/results/a.json evals/results/b.json

Two modes, and the split is what keeps this affordable. Retrieval metrics come
from the surface with no model in the loop, so a re-run costs nothing and they
are the numbers Phase 5's chunker comparison turns on. The judgement metrics
(false_precedent_rate, no_precedent_accuracy, false_refusal_rate,
groundedness, divergence_quality) need a live `oa run` per case, an API key and
the patches/ provider patch, and they score the agent on the queries it chose
rather than on this dataset's canonical probe. They are not written yet. Every
one of them appears in the results table as unmeasured rather than being left
out, because a table that lists only what was measured reads as a full result.

Stdlib plus PyYAML, same as evals/validate.py, which this borrows the corpus
fingerprint from so a results file records the corpus it was measured against.

Definitions, because the metric names are shorter than the decisions in them:

  precedent_hit_rate@k   Of every (case, relevant document) pair, the fraction
                         where the document is among the first k distinct
                         documents the surface returns. Micro-averaged over
                         pairs, so a case with five relevant documents carries
                         five times the weight of a case with one. Ground truth
                         names documents, not passages, for the reason
                         evals/README.md gives: the two chunkers share no
                         passage id, and the baseline has to be comparable
                         across them.

  ceiling@k              What that fraction could reach at this k. A case with
                         five relevant documents cannot contribute more than
                         three at k=3, so the raw rate has a ceiling below 1
                         and printing it alone makes a good run look broken.

  attainment@k           hit_rate divided by ceiling. How much of what k allows
                         was actually reached.

  mrr@k                  Mean reciprocal rank of the first relevant document,
                         over cases that have one, zero when none lands in k.

Ranking is over distinct documents, by the position of a document's first
returned passage. The search that derives it is issued at a passage limit high
enough that nothing truncates: the surface's per-source cap only ever drops a
document's third passage, never a document, so the ordering is complete.
That is plumbing, not the measurement. k is the bound the numbers are read at.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate import fingerprint, load_corpus  # noqa: E402

DATASET = "evals/dataset.yaml"
RESULTS = "evals/results"

# Neither validate.py's 8527 nor corpus/eval.py's 8526, and not the adapter's
# own 8426: a local run of one must not have to wait on another.
DEFAULT_PORT = 8528

# High enough that neither the passage limit nor the surface's per-source cap
# truncates the document ranking. The cap removes a document's third passage,
# never a document, so first-appearance order is unaffected by it.
RANK_LIMIT = 1000

# The passage budget the agent is actually given: what demos/investigate.sh
# and the governance demos pass, and what evals/validate.py's observation is
# measured at. Overridable in config as run_limit, but changing it makes a
# results file incomparable with every earlier one, which is why it is
# recorded in the file rather than assumed by the reader.
RUN_LIMIT = 8

DEFAULTS = {
    "index": "corpus/index.fixed.json",
    "chunker": "fixed",
    "reranker": "none",
    "k": [1, 3, 5, 8],
    "port": DEFAULT_PORT,
    "run_limit": RUN_LIMIT,
    "label": "baseline-fixed",
}

# Named here rather than in the table writer so an unimplemented metric cannot
# quietly stop being listed. Each states what it needs, not just that it is
# missing: "not measured" alone reads as an oversight.
JUDGEMENT_METRICS = [
    ("false_precedent_rate",
     "judgement mode: one live oa run per case, scored against expect.applicability"),
    ("no_precedent_accuracy",
     "judgement mode: 13 no-precedent cases, scored on no_applicable_precedent"),
    ("false_refusal_rate",
     "judgement mode: 25 answerable cases, scored on the same field"),
    ("groundedness",
     "judgement mode plus a judge prompt at temperature 0, which is not written"),
    ("divergence_quality",
     "judgement mode: 7 near-miss cases, scored against expect.divergence_names"),
    ("cost_per_recall_usd",
     "judgement mode: no model runs in retrieval mode, so the cost is zero and "
     "measures nothing"),
]


# --------------------------------------------------------------------------
# The surface
# --------------------------------------------------------------------------

def rpc(port, name, args):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": args}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}", data=body,
                                 headers={"Content-Type": "application/json"})
    payload = json.loads(urllib.request.urlopen(req, timeout=20).read())
    result = payload["result"]
    text = result["content"][0]["text"]
    if result.get("isError"):
        raise SystemExit(f"surface fault on {name}: {text}")
    return json.loads(text)


def start_adapter(index, port):
    proc = subprocess.Popen(
        [sys.executable, "mock/adapter.py", "--surface", "precedent_archive",
         "--port", str(port), "--index", index],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            rpc(port, "coverage_describe", {"before": "2026-03-17"})
            return proc
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.1)
    proc.terminate()
    raise SystemExit("adapter did not come up")


def ranked_documents(passages):
    """Distinct source_uris in returned order, first appearance wins."""
    seen, out = set(), []
    for passage in passages:
        uri = passage["source_uri"]
        if uri not in seen:
            seen.add(uri)
            out.append(uri)
    return out


def probe(port, case, limit):
    """The canonical query, timed. One query per case, which is the floor the
    agent is measured above rather than a model of how it is told to search:
    the spec tells it to issue several, and a case probing one axis of a
    multi-axis incident is counted here as missing what its other axis
    reaches. See evals/README.md."""
    started = time.perf_counter()
    result = rpc(port, "precedent_search", {"symptom_text": case["query"],
                                            "before": case["as_of"],
                                            "limit": limit})
    return result, (time.perf_counter() - started) * 1000


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def score_case(case, ranked, ks):
    """Per-k hits, ceiling and reciprocal rank for one case."""
    relevant = list(case["expect"].get("relevant") or [])
    position = {uri: i + 1 for i, uri in enumerate(ranked)}
    first = min((position[uri] for uri in relevant if uri in position),
                default=None)
    out = {"relevant": len(relevant), "found_at": {}, "per_k": {}}
    for uri in relevant:
        out["found_at"][uri] = position.get(uri)
    for k in ks:
        hits = sum(1 for uri in relevant if position.get(uri, 10 ** 6) <= k)
        out["per_k"][k] = {
            "hits": hits,
            # A case cannot contribute more pairs than k allows, however good
            # the retriever is.
            "ceiling": min(k, len(relevant)),
            "rr": 1.0 / first if first is not None and first <= k else 0.0,
        }
    return out


def aggregate(scored, ks):
    """Micro over (case, document) pairs for the rates, macro over cases for
    mrr. Two averages on purpose: a rate about documents is a document
    question, and a rank is a per-query one."""
    pairs = sum(s["relevant"] for s in scored.values())
    out = {}
    for k in ks:
        hits = sum(s["per_k"][k]["hits"] for s in scored.values())
        ceiling = sum(s["per_k"][k]["ceiling"] for s in scored.values())
        rrs = [s["per_k"][k]["rr"] for s in scored.values()]
        out[str(k)] = {
            "hits": hits,
            "pairs": pairs,
            "ceiling": ceiling,
            "precedent_hit_rate": round(hits / pairs, 4) if pairs else None,
            "ceiling_rate": round(ceiling / pairs, 4) if pairs else None,
            "attainment": round(hits / ceiling, 4) if ceiling else None,
            "mrr": round(sum(rrs) / len(rrs), 4) if rrs else None,
        }
    return out


def by_group(cases, scored, k):
    out = {}
    for case in cases:
        if case["id"] not in scored:
            continue
        row = out.setdefault(case["group"], {"cases": 0, "hits": 0,
                                             "pairs": 0, "ceiling": 0})
        entry = scored[case["id"]]
        row["cases"] += 1
        row["pairs"] += entry["relevant"]
        row["hits"] += entry["per_k"][k]["hits"]
        row["ceiling"] += entry["per_k"][k]["ceiling"]
    for row in out.values():
        row["precedent_hit_rate"] = (round(row["hits"] / row["pairs"], 4)
                                     if row["pairs"] else None)
    return out


def floor_silence(port, cases, run_limit):
    """The retrieval half of refusal, and only the half.

    Whether the agent refuses is judgement mode. What the surface hands it is
    measurable now: on a no-precedent case, does the canonical probe return
    nothing at all above the floor. A case that returns something is one where
    the refusal has to come from the agent's judgement rather than from the
    floor, which the dataset allows only for documents it names must_not_cite.
    """
    novel = [c for c in cases if not c["expect"]["precedent_exists"]]
    silent, returning = 0, []
    for case in novel:
        result, _ = probe(port, case, run_limit)
        returned = ranked_documents(result.get("passages") or [])
        if not returned:
            silent += 1
        else:
            returning.append({"case": case["id"], "documents": returned})
    return {
        "novel_cases": len(novel),
        "silent_at_the_floor": silent,
        "rate": round(silent / len(novel), 4) if novel else None,
        "returning": returning,
    }


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------

def run(config, stamp):
    with open(DATASET) as handle:
        dataset = yaml.safe_load(handle)
    cases = dataset["cases"]
    corpus = load_corpus()

    got = fingerprint(corpus)
    if got != dataset.get("corpus_fingerprint"):
        raise SystemExit(
            "corpus fingerprint does not match the dataset pin, so this "
            "ground truth was judged against different documents. Run "
            "python3 evals/validate.py first; a baseline recorded against an "
            "unpinned corpus is not comparable to anything.")

    with open(config["index"]) as handle:
        index = json.load(handle)
    if index.get("chunker") != config["chunker"]:
        raise SystemExit(
            f"config says chunker {config['chunker']}, {config['index']} was "
            f"built with {index.get('chunker')}. Recording a baseline against "
            f"the wrong index is the one mistake that makes Phase 5's "
            f"comparison meaningless.")

    ks = sorted(config["k"])
    port = config["port"]
    proc = start_adapter(config["index"], port)
    try:
        scored, latencies = {}, []
        at_limit_hits, at_limit_misses = 0, []
        for case in cases:
            if not case["expect"].get("relevant"):
                continue
            result, ms = probe(port, case, RANK_LIMIT)
            latencies.append(ms)
            ranked = ranked_documents(result.get("passages") or [])
            scored[case["id"]] = score_case(case, ranked, ks)

            # The second measurement, and not a footnote to the first. The
            # ranking above is chunker-neutral by construction: it asks which
            # documents the surface orders highest with nothing truncating.
            # This one asks what the agent is handed inside a fixed passage
            # budget, where chunk size decides how many distinct documents
            # fit. On this corpus that is the only place the two chunkers
            # differ at all, so a comparison that reported only the ranking
            # would conclude chunking does not matter.
            budgeted, ms = probe(port, case, config["run_limit"])
            latencies.append(ms)
            at_limit = set(ranked_documents(budgeted.get("passages") or []))
            for uri in case["expect"]["relevant"]:
                if uri in at_limit:
                    at_limit_hits += 1
                else:
                    at_limit_misses.append(
                        f"{case['id']}:{uri.replace('corpus://', '')}")

        silence = floor_silence(port, cases, config["run_limit"])
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    pairs = sum(s["relevant"] for s in scored.values())
    return {
        "recorded_at": stamp,
        "label": config["label"],
        "mode": "retrieval",
        "index": config["index"],
        "chunker": config["chunker"],
        "reranker": config["reranker"],
        "k": ks,
        "corpus": {"documents": len(corpus), "fingerprint": got},
        "dataset": {
            "cases": len(cases),
            "scored_cases": len(scored),
            "pairs": pairs,
            "path": DATASET,
        },
        "retrieval": aggregate(scored, ks),
        "by_group": {str(k): by_group(cases, scored, k) for k in ks},
        "floor_silence": silence,
        "at_run_limit": {
            "limit": config["run_limit"],
            "hits": at_limit_hits,
            "pairs": pairs,
            "precedent_hit_rate": round(at_limit_hits / pairs, 4) if pairs
            else None,
            "misses": at_limit_misses,
            "note": "a passage budget, not a document ranking: how many "
                    "relevant documents survive inside the limit the agent is "
                    "run at. The same figure evals/validate.py reports as an "
                    "observation.",
        },
        "latency_ms": {
            "calls": len(latencies),
            "p50": round(statistics.median(latencies), 2),
            "p95": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2),
            "note": "the mock surface over loopback JSON-RPC. It measures this "
                    "repo's fixture retriever, not a vector store, and is not "
                    "a latency claim about anything deployable.",
        },
        "not_measured": {name: why for name, why in JUDGEMENT_METRICS},
        "per_case": scored,
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def pct(value):
    return "-" if value is None else f"{value * 100:.1f}%"


def markdown(result):
    ks = result["k"]
    lines = [
        "# Precedent Analyst, retrieval baseline",
        "",
        "Generated by `evals/runner.py`. Do not hand-edit: re-run it.",
        "",
        f"- Run `{result['label']}`",
        f"- Index `{result['index']}`, chunker {result['chunker']}, "
        f"reranker {result['reranker']}",
        f"- Corpus {result['corpus']['documents']} documents, fingerprint "
        f"`{result['corpus']['fingerprint'][:16]}`",
        f"- Dataset {result['dataset']['cases']} cases, "
        f"{result['dataset']['scored_cases']} with relevant documents, "
        f"{result['dataset']['pairs']} (case, document) pairs",
        f"- Mode retrieval, no model in the loop, one canonical query per "
        f"case, passage budget {result['at_run_limit']['limit']}",
        "",
        "## Two measurements, and they answer different questions",
        "",
        "`precedent_hit_rate@k` ranks **documents** with nothing truncating: "
        "which prior records does the surface order highest. "
        "`precedent_hit_rate@limit` counts what survives inside the **passage "
        "budget the agent is actually run at**, where chunk size decides how "
        "many distinct documents fit. The first is a property of the ranking, "
        "the second of the ranking and the chunker together. Phase 5's "
        "chunker comparison turns on the second, because on this corpus the "
        "first cannot tell the two chunkers apart at all.",
        "",
        f"**At the run limit of {result['at_run_limit']['limit']} passages: "
        f"{pct(result['at_run_limit']['precedent_hit_rate'])} "
        f"({result['at_run_limit']['hits']}/{result['at_run_limit']['pairs']} "
        f"relevant documents reached).** This is the figure "
        f"`evals/validate.py` prints as an observation, recorded here so the "
        f"two are one number rather than two of unstated provenance.",
        "",
        "## Retrieval, by document rank",
        "",
        "| k | precedent_hit_rate@k | ceiling@k | attainment | mrr@k |",
        "| --- | --- | --- | --- | --- |",
    ]
    for k in ks:
        row = result["retrieval"][str(k)]
        lines.append(
            f"| {k} | {pct(row['precedent_hit_rate'])} "
            f"({row['hits']}/{row['pairs']}) | {pct(row['ceiling_rate'])} "
            f"({row['ceiling']}/{row['pairs']}) | {pct(row['attainment'])} | "
            f"{row['mrr']:.3f} |")

    lines += [
        "",
        "Read the ceiling before the rate. Ground truth names every document "
        "relevant to an incident, so a case with five of them cannot "
        "contribute more than three pairs at k=3. Attainment is the rate "
        "against what k allows.",
        "",
        "## By group, at k=5",
        "",
        "| group | cases | pairs | precedent_hit_rate@5 |",
        "| --- | --- | --- | --- |",
    ]
    groups = result["by_group"].get("5") or result["by_group"][str(ks[-1])]
    for name in sorted(groups):
        row = groups[name]
        lines.append(f"| {name} | {row['cases']} | {row['pairs']} | "
                     f"{pct(row['precedent_hit_rate'])} "
                     f"({row['hits']}/{row['pairs']}) |")

    lines += [
        "",
        "Only cases with relevant documents are scored, so the counts here "
        "are below the dataset's group sizes: the 13 no-precedent cases have "
        "nothing to hit and are measured in the next section instead.",
    ]

    silence = result["floor_silence"]
    lines += [
        "",
        "## The floor, on cases with no applicable precedent",
        "",
        f"{silence['silent_at_the_floor']} of {silence['novel_cases']} "
        f"no-precedent cases return nothing at all above the relevance floor "
        f"on the canonical probe ({pct(silence['rate'])}).",
        "",
        "This is the retrieval half of refusal and only that half. Whether "
        "the agent refuses is `no_precedent_accuracy`, which needs judgement "
        "mode. What is measured here is what the surface hands it.",
    ]
    if silence["returning"]:
        for entry in silence["returning"]:
            names = ", ".join(u.replace("corpus://", "")
                              for u in entry["documents"])
            lines.append(f"- `{entry['case']}` is handed {names}, so its "
                         f"refusal has to come from record status rather than "
                         f"from the floor")

    lines += [
        "",
        "## What this run does not measure",
        "",
        "| Metric | Why not |",
        "| --- | --- |",
    ]
    for name, why in JUDGEMENT_METRICS:
        lines.append(f"| `{name}` | {why} |")

    lines += [
        "",
        "Three limits that survive judgement mode being written:",
        "",
        "- **Section-level citation is unmeasured, not mitigated.** Ground "
        "truth names documents, so nothing here distinguishes a citation of "
        "the right document's `Resolution` from its `Gaps`. Adapter-log "
        "groundedness would not either: it proves only that a cited passage "
        "was in the returned set. See `evals/README.md`.",
        "- **One query per case.** The spec tells the agent to issue several, "
        "so a case probing one axis of a multi-axis incident is counted here "
        "as missing what its other axis would reach. These numbers are a "
        "floor on the surface, not an estimate of the agent.",
        f"- **The document ranking is chunker-blind on this corpus.** Run "
        f"against both indexes it produces identical hits at every k, and one "
        f"document differing by a single rank. The two chunkers differ only "
        f"inside the passage budget, which is where "
        f"`precedent_hit_rate@limit` measures them. A Phase 5 comparison "
        f"reported on the ranking alone would conclude that chunking does not "
        f"matter, and it would be an artefact of the metric. Measured, not "
        f"asserted: `--compare` over the two results files beside this one.",
        "",
        "This table is a function of the dataset, the corpus and the config "
        "named above, and nothing else. It carries no timestamp and no "
        "latency figure for that reason: `python3 evals/runner.py --config "
        "evals/config.yaml --check` regenerates it and fails if it has "
        "drifted, the same way the fixtures and the corpus index are checked. "
        "When a run was recorded, what the surface took, and the per-case "
        "detail are in the timestamped JSON beside this file. That latency is "
        "the mock over loopback: it measures this repo's fixture retriever, "
        "not a vector store.",
        "",
    ]
    return "\n".join(lines)


def compare(path_a, path_b):
    with open(path_a) as handle:
        a = json.load(handle)
    with open(path_b) as handle:
        b = json.load(handle)

    if a["corpus"]["fingerprint"] != b["corpus"]["fingerprint"]:
        print("FAIL  these runs measured different corpora, so the delta is "
              "the documents changing and not retrieval improving:")
        print(f"        {path_a}  {a['corpus']['fingerprint'][:16]}")
        print(f"        {path_b}  {b['corpus']['fingerprint'][:16]}")
        return 1

    print(f"{a['label']} ({a['chunker']}, reranker {a['reranker']})  ->  "
          f"{b['label']} ({b['chunker']}, reranker {b['reranker']})\n")
    ks = [k for k in a["k"] if str(k) in b["retrieval"]]
    print("  k    hit_rate@k              mrr@k")
    for k in ks:
        ra, rb = a["retrieval"][str(k)], b["retrieval"][str(k)]
        delta = rb["precedent_hit_rate"] - ra["precedent_hit_rate"]
        dmrr = rb["mrr"] - ra["mrr"]
        print(f"  {k:<4} {pct(ra['precedent_hit_rate']):>6} -> "
              f"{pct(rb['precedent_hit_rate']):>6}  {delta * 100:+5.1f}pp     "
              f"{ra['mrr']:.3f} -> {rb['mrr']:.3f}  {dmrr:+.3f}")

    la, lb = a["at_run_limit"], b["at_run_limit"]
    if la["limit"] != lb["limit"]:
        print(f"\n  FAIL  different passage budgets, {la['limit']} against "
              f"{lb['limit']}: the run-limit figures are not comparable")
        return 1
    print(f"\n  @limit {la['limit']}  {pct(la['precedent_hit_rate'])} -> "
          f"{pct(lb['precedent_hit_rate'])}  "
          f"{(lb['precedent_hit_rate'] - la['precedent_hit_rate']) * 100:+.1f}pp"
          f"   ({la['hits']}/{la['pairs']} -> {lb['hits']}/{lb['pairs']})")
    print("          The passage budget is where chunking shows. The document "
          "ranking above is chunker-blind on this corpus.")

    print()
    for label, key in (("p50", "p50"), ("p95", "p95")):
        print(f"  {label}   {a['latency_ms'][key]}ms -> "
              f"{b['latency_ms'][key]}ms")

    missing = sorted(set(a["not_measured"]) & set(b["not_measured"]))
    if missing:
        print(f"\n  Unmeasured in both, so the comparison says nothing about "
              f"them: {', '.join(missing)}")
    return 0


def load_config(path, overrides):
    config = dict(DEFAULTS)
    if path:
        with open(path) as handle:
            config.update(yaml.safe_load(handle) or {})
    config.update({k: v for k, v in overrides.items() if v is not None})
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    parser.add_argument("--index", default=None)
    parser.add_argument("--chunker", default=None)
    parser.add_argument("--label", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--stamp", default=None,
                        help="UTC timestamp for the record. Defaults to now; "
                             "pass one to reproduce a results file byte for "
                             "byte.")
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"))
    parser.add_argument("--check", action="store_true",
                        help="Regenerate latest.md and fail if it differs. "
                             "Writes nothing, so CI can run it.")
    parser.add_argument("--mode", default="retrieval",
                        choices=["retrieval", "judgement"])
    args = parser.parse_args()

    if args.compare:
        return compare(*args.compare)

    if args.mode == "judgement":
        print("judgement mode is not implemented. It needs a live oa run per "
              "case, an API key and the patches/ provider patch, and it "
              "scores the agent on the queries it recorded in "
              "search_coverage.queries_issued rather than on this dataset's "
              "canonical probe. evals/README.md holds the design.")
        return 2

    config = load_config(args.config, {"index": args.index,
                                       "chunker": args.chunker,
                                       "label": args.label,
                                       "port": args.port})
    stamp = args.stamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result = run(config, stamp)
    table = markdown(result)
    latest = os.path.join(RESULTS, "latest.md")

    if args.check:
        current = open(latest).read() if os.path.exists(latest) else ""
        if current == table:
            print(f"{latest} is current for {config['label']}")
            return 0
        print(f"{latest} does not match a fresh run of {config['label']}. "
              f"The corpus, the dataset or the config has moved under it. "
              f"Re-record it:\n"
              f"  python3 evals/runner.py --config evals/config.yaml")
        return 1

    os.makedirs(RESULTS, exist_ok=True)
    slug = stamp.replace(":", "").replace("-", "")
    out = os.path.join(RESULTS, f"{config['label']}-{slug}.json")
    with open(out, "w") as handle:
        json.dump(result, handle, indent=2, sort_keys=False)
        handle.write("\n")
    with open(latest, "w") as handle:
        handle.write(table)

    top = result["retrieval"][str(sorted(config["k"])[-1])]
    print(f"{result['label']}: {result['dataset']['scored_cases']} scored "
          f"cases, {result['dataset']['pairs']} pairs, index "
          f"{result['index']}")
    for k in sorted(config["k"]):
        row = result["retrieval"][str(k)]
        print(f"  hit_rate@{k:<2} {pct(row['precedent_hit_rate']):>6} "
              f"({row['hits']}/{row['pairs']}), ceiling "
              f"{pct(row['ceiling_rate'])}, mrr {row['mrr']:.3f}")
    limit = result["at_run_limit"]
    print(f"  hit_rate@limit{limit['limit']} "
          f"{pct(limit['precedent_hit_rate']):>6} "
          f"({limit['hits']}/{limit['pairs']}), the passage budget the agent "
          f"is run at")
    print(f"  floor silence {result['floor_silence']['silent_at_the_floor']}/"
          f"{result['floor_silence']['novel_cases']} no-precedent cases")
    print(f"\nwrote {out}")
    print(f"wrote {latest}")
    return 0 if top["pairs"] else 1


if __name__ == "__main__":
    sys.exit(main())
