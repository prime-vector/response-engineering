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
rather than on this dataset's canonical probe. They live in evals/judgement.py.
Every one of them still appears in this mode's results table as unmeasured,
with where it is measured instead, because a table that lists only what it
measured reads as a full result.

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
import hashlib
import json
import math
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

# An eval parameter, and not the agent's budget however much it wants to be.
# Nothing binds the agent to it: the surface defaults to 5, the spec tells the
# agent to ask for breadth without naming a number, and no demo passes one. So
# this measures the surface under a fixed budget, which is a real question
# about the retriever and not an estimate of what the agent is handed. What
# the agent actually requests is recorded in queries_issued and belongs to
# judgement mode. Overridable in config as run_limit; changing it makes a
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
    "cross_check": [
        {"index": "corpus/index.fixed.json", "chunker": "fixed",
         "label": "fixed"},
        {"index": "corpus/index.json", "chunker": "heading",
         "label": "heading-aware"},
    ],
}

# Named here rather than in the table writer so an unimplemented metric cannot
# quietly stop being listed. Each states what it needs, not just that it is
# missing: "not measured" alone reads as an oversight.
JUDGEMENT_METRICS = [
    ("false_precedent_rate",
     "evals/judgement.py: one live oa run per case, scored against "
     "expect.applicability"),
    ("no_precedent_accuracy",
     "evals/judgement.py: {no_precedent} no-precedent cases, scored on "
     "no_applicable_precedent"),
    ("false_refusal_rate",
     "evals/judgement.py: {answerable} answerable cases, scored on the same "
     "field"),
    ("groundedness_log",
     "evals/judgement.py: read from the adapter's audit log, which retrieval "
     "mode has no reason to consult because it issues the calls itself"),
    ("groundedness_judge",
     "evals/judgement.py plus the judge named in evals/config.judgement.yaml, "
     "prompts committed in evals/judges/. Its level is judge-relative: read "
     "it as a comparison between arms, not as a score"),
    ("divergence_quality",
     "evals/judgement.py: {near_miss} near-miss cases, scored against "
     "expect.divergence_names"),
    ("agent_reach",
     "evals/judgement.py: retrieval across the queries the agent chose, which "
     "this mode cannot see because it issues one canonical probe per case"),
    ("cost_per_recall_usd",
     "unmeasured in either mode: no model runs here, and oa reports no token "
     "usage there"),
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


def answering(port):
    try:
        rpc(port, "coverage_describe", {"before": "2026-03-17"})
        return True
    except (urllib.error.URLError, ConnectionError, OSError):
        return False


def start_adapter(index, port, log_path=None):
    """Start the surface, and prove it is the one we asked for.

    Two failures this closes, both of which produce numbers rather than an
    error. A process left over from an earlier run answers on the port and is
    serving a different index, so the table's header names one index while the
    figures come from another. And a spawn that fails after something else has
    claimed the port looks exactly like a healthy start.

    A passage id encodes the chunker name, so resolving one taken from the
    index file we intended proves which index is actually being served. That
    is the only check here that a leftover process cannot pass.

    log_path captures the adapter's audit lines. Retrieval mode discards them:
    it issues the calls itself and already knows what came back. Judgement
    mode cannot, because the caller there is a model and its output claims
    tool use it cannot prove, so the log is the only record of what the
    surface actually returned to it.
    """
    if answering(port):
        raise SystemExit(
            f"something is already serving on port {port}. Retrieval figures "
            f"from an adapter this run did not start are not figures about "
            f"{index}: stop it, or pass --port.")

    sink = open(log_path, "w") if log_path else subprocess.DEVNULL
    proc = subprocess.Popen(
        [sys.executable, "mock/adapter.py", "--surface", "precedent_archive",
         "--port", str(port), "--index", index],
        stdout=sink, stderr=subprocess.STDOUT if log_path else sink)
    if log_path:
        # The child holds its own descriptor from here; ours would otherwise
        # stay open for the life of a sweep.
        sink.close()
    for _ in range(50):
        if answering(port):
            break
        time.sleep(0.1)
    else:
        proc.terminate()
        raise SystemExit("adapter did not come up")

    with open(index) as handle:
        want = json.load(handle)["passages"][0]["passage_id"]
    try:
        got = rpc(port, "passage_get", {"passage_id": want})
    except SystemExit:
        got = {}
    if got.get("passage_id") != want:
        proc.terminate()
        raise SystemExit(
            f"the surface on port {port} does not resolve a passage id from "
            f"{index}, so it is serving a different index")
    return proc


def check_corpus_pin(dataset):
    """Refuse to measure ground truth judged against different documents.

    Both modes need this and only one had it. --cross-check loaded the cases
    directly, so it could write a checked-looking comparison from a dataset
    whose judgements no longer describe the corpus, which is the failure the
    refusal in the other mode exists to stop.
    """
    corpus = load_corpus()
    got = fingerprint(corpus)
    if got != dataset.get("corpus_fingerprint"):
        raise SystemExit(
            "corpus fingerprint does not match the dataset pin, so this "
            "ground truth was judged against different documents. Run "
            "python3 evals/validate.py first; figures recorded against an "
            "unpinned corpus are not comparable to anything.")
    return corpus, got


def file_fingerprint(path):
    """sha256 of a file's bytes.

    Used for the index actually served. The corpus pin is over the manifest,
    which is a different artefact: an index can be edited, or left stale,
    while the manifest and every document still hash to what the dataset was
    pinned against. Recording this ties a result to what was measured rather
    than to what the manifest says exists.
    """
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def dataset_fingerprint(path):
    """The ground truth these figures were scored against, by content.

    The corpus pin says the documents have not moved. It says nothing about
    the judgements over them, and a comparison across two datasets is the
    truth moving rather than retrieval improving, which is the same lie the
    corpus refusal exists to stop.

    Over the parsed structure rather than the file's bytes, deliberately. The
    byte version moved when a comment in dataset.yaml was corrected, and the
    remedy this pin prescribes is a fresh sweep: an expensive check that fires
    on prose is one that gets worked around. The scorer pin is byte-level for
    the opposite reason, that its remedy is free. What is pinned here is the
    ground truth, which is the data.
    """
    with open(path) as handle:
        content = yaml.safe_load(handle)
    return hashlib.sha256(
        json.dumps(content, sort_keys=True).encode()).hexdigest()


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
    corpus, got = check_corpus_pin(dataset)

    with open(config["index"]) as handle:
        index = json.load(handle)
    if index.get("chunker") != config["chunker"]:
        raise SystemExit(
            f"config says chunker {config['chunker']}, {config['index']} was "
            f"built with {index.get('chunker')}. Recording a baseline against "
            f"the wrong index is the one mistake that makes Phase 5's "
            f"comparison meaningless.")

    # Recorded in every result and, until now, never checked against anything.
    # There is no reranker here to configure: the mock ranks by term overlap
    # and nothing else. A results file claiming one would be a checked
    # artefact asserting a configuration that did not exist, which is worse
    # than not recording it. Accept only what can be true.
    if config["reranker"] != "none":
        raise SystemExit(
            f"config declares reranker {config['reranker']!r}, and this "
            f"runner can configure none. The mock surface ranks by term "
            f"overlap and takes no reranker, so recording that value would "
            f"put a configuration in a results file that nothing produced. "
            f"Wire one before declaring one.")

    ks = sorted(config["k"])
    port = config["port"]
    composition = {
        "by_group": {},
        "no_precedent": sum(1 for c in cases
                            if not c["expect"]["precedent_exists"]),
        "near_miss": sum(1 for c in cases if c["group"] == "near_miss"),
        "answerable": sum(1 for c in cases if c["expect"]["precedent_exists"]),
    }
    for case in cases:
        composition["by_group"][case["group"]] = (
            composition["by_group"].get(case["group"], 0) + 1)

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
            # ranking above asks which documents the surface orders highest
            # with nothing truncating. This one asks what the agent is handed
            # inside a fixed passage budget, where chunk size decides how many
            # distinct documents fit. They are different questions and the
            # chunkers answer them differently, which --cross-check measures
            # at every k rather than at the four this config reads.
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

        # The floor is a property of the surface, configurable on the adapter
        # and invisible in the figures it produces. Two runs at different
        # floors are two experiments, and nothing else in this record would
        # say so.
        sample, _ = probe(port, cases[0], 1)
        floor = sample.get("floor_applied")
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    pairs = sum(s["relevant"] for s in scored.values())
    return {
        "recorded_at": stamp,
        "label": config["label"],
        "mode": "retrieval",
        "index": config["index"],
        "index_fingerprint": file_fingerprint(config["index"]),
        "chunker": config["chunker"],
        "reranker": config["reranker"],
        "k": ks,
        "corpus": {"documents": len(corpus), "fingerprint": got},
        "dataset": {
            "cases": len(cases),
            "scored_cases": len(scored),
            "pairs": pairs,
            "path": DATASET,
            "fingerprint": dataset_fingerprint(DATASET),
            "composition": composition,
        },
        "surface": {"floor_applied": floor, "rank_limit": RANK_LIMIT},
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
                    "relevant documents survive inside a fixed limit. An eval "
                    "parameter, not the agent's: the surface defaults to 5 "
                    "and nothing binds the agent to this number. The same "
                    "figure evals/validate.py reports as an observation.",
        },
        "latency_ms": {
            "calls": len(latencies),
            "p50": round(statistics.median(latencies), 2),
            # Nearest rank, ceiling not truncation: int() puts p95 of 50
            # calls on the 47th value rather than the 48th.
            "p95": round(sorted(latencies)[math.ceil(len(latencies) * 0.95) - 1],
                         2),
            "note": "the mock surface over loopback JSON-RPC, and a mixture of "
                    "two probes per case at two different passage limits. It "
                    "measures this repo's fixture retriever, not a vector "
                    "store, and is not a latency claim about anything "
                    "deployable.",
        },
        "not_measured": {name: why.format(**composition)
                         for name, why in JUDGEMENT_METRICS},
        "per_case": scored,
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def pct(value):
    return "-" if value is None else f"{value * 100:.1f}%"


def markdown(result):
    ks = result["k"]
    # 5 is the k docs/precedent-analyst.md fixes for the Phase 5 comparison.
    # Falling back to the largest k rather than failing kept the heading and
    # the column disagreeing about which k they showed.
    group_k = 5 if 5 in ks else ks[-1]
    composition = result["dataset"]["composition"]
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
        "`precedent_hit_rate@limit` counts what survives inside a **fixed "
        "passage budget**, where chunk size decides how many distinct "
        "documents fit. The first is a property of the ranking, "
        "the second of the ranking and the chunker together. How two chunkers "
        "differ on either, and at which k, is measured in "
        "`chunker-comparison.md` beside this file, which scores both indexes "
        "on both. A single-index run cannot see any of that, so this table "
        "does not claim it: the budget figure below is this index alone.",
        "",
        f"The budget is an eval parameter. Nothing binds the agent to it: "
        f"the surface defaults to 5 passages, `.agents/precedent-analyst.yaml` "
        f"tells the agent to ask for breadth without naming a number, and no "
        f"demo passes one. So this is the surface measured under a fixed "
        f"budget, which is a real question about the retriever, and it is not "
        f"an estimate of what the agent is handed. What the agent actually "
        f"asks for is in the adapter's audit log, and judgement mode scores "
        f"it there as `agent_reach`, because an output reporting its own "
        f"queries is the agent's account of its own conduct.",
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
        f"## By group, at k={group_k}",
        "",
        f"| group | cases | pairs | precedent_hit_rate@{group_k} |",
        "| --- | --- | --- | --- |",
    ]
    groups = result["by_group"][str(group_k)]
    for name in sorted(groups):
        row = groups[name]
        lines.append(f"| {name} | {row['cases']} | {row['pairs']} | "
                     f"{pct(row['precedent_hit_rate'])} "
                     f"({row['hits']}/{row['pairs']}) |")

    lines += [
        "",
        f"Only cases with relevant documents are scored, so the counts here "
        f"are below the dataset's group sizes: the "
        f"{composition['no_precedent']} no-precedent cases have nothing to "
        f"hit and are measured in the next section instead.",
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
        "the agent refuses is `no_precedent_accuracy`, which is measured in "
        "judgement mode. What is measured here is what the surface hands it.",
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
        lines.append(f"| `{name}` | {why.format(**composition)} |")
    lines += [
        "",
        "Every one of those is now written and lives in the other mode. They "
        "stay listed here because this table would otherwise read as the "
        "whole measurement: what the surface hands an agent is not what the "
        "agent does with it.",
    ]

    limits = [
        "- **Section-level citation is unmeasured, not mitigated.** Ground "
        "truth names documents, so nothing here distinguishes a citation of "
        "the right document's `Resolution` from its `Gaps`. Adapter-log "
        "groundedness would not either: it proves only that a cited passage "
        "was in the returned set. See `evals/README.md`.",
        "- **One query per case.** The spec tells the agent to issue several, "
        "so a case probing one axis of a multi-axis incident is counted here "
        "as missing what its other axis would reach. These numbers are a "
        "floor on the surface, not an estimate of the agent. Judgement mode "
        "measures the other thing, on the queries the agent chose, and the "
        "two are not comparable: nothing truncates a rank there.",
        "- **This table is one index.** Whether a chunker changes retrieval "
        "is not visible from it at all, and a sentence here saying so would "
        "be regenerated identically whatever the other index did. "
        "`chunker-comparison.md` measures that, and CI checks it.",
    ]

    lines += [
        "",
        f"{len(limits)} limits that judgement mode does not close:",
        "",
        *limits,
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


# --------------------------------------------------------------------------
# Cross-index comparison
# --------------------------------------------------------------------------

def cross_check(config):
    """Whether the chunker moves the document ranking, measured at every k.

    This exists because the claim it settles used to be a sentence in the
    baseline table. A single-index run cannot see the other index, so that
    sentence was regenerated identically whatever the other index did, and the
    --check certifying the table could not falsify it. The claim was also
    wrong: the ranking is identical at k in {1,3,5,8} and differs at k=2,
    which is the gap the configured grid happens to straddle.

    So the grid is not a parameter here. Every k from 1 to the deepest rank
    any relevant document reaches is scored, and the k values where the two
    disagree are reported rather than chosen.
    """
    with open(DATASET) as handle:
        dataset = yaml.safe_load(handle)
    check_corpus_pin(dataset)
    scored_cases = [c for c in dataset["cases"]
                    if c["expect"].get("relevant")]

    ranks, budget, served = {}, {}, {}
    for entry in config["cross_check"]:
        with open(entry["index"]) as handle:
            index = json.load(handle)
        if index.get("chunker") != entry["chunker"]:
            raise SystemExit(
                f"cross_check says chunker {entry['chunker']}, "
                f"{entry['index']} was built with {index.get('chunker')}")
        served[entry["label"]] = file_fingerprint(entry["index"])
        proc = start_adapter(entry["index"], config["port"])
        try:
            found, kept = {}, {}
            for case in scored_cases:
                result, _ = probe(config["port"], case, RANK_LIMIT)
                position = {uri: i + 1 for i, uri in
                            enumerate(ranked_documents(result.get("passages")
                                                       or []))}
                for uri in case["expect"]["relevant"]:
                    found[f"{case['id']}|{uri}"] = position.get(uri)

                # The other half of the comparison, and the half that was
                # hand-maintained in three documents. latest.md measures the
                # passage budget for the baseline index only, so the other
                # index's figure lived in prose that no check could falsify:
                # the same defect as a ranking claim in a single-index table,
                # in the measurement that claim was contrasted against.
                budgeted, _ = probe(config["port"], case, config["run_limit"])
                at_limit = set(ranked_documents(budgeted.get("passages") or []))
                for uri in case["expect"]["relevant"]:
                    kept[f"{case['id']}|{uri}"] = uri in at_limit
            ranks[entry["label"]] = found
            budget[entry["label"]] = kept
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    labels = [e["label"] for e in config["cross_check"]]
    a, b = ranks[labels[0]], ranks[labels[1]]
    pairs = sorted(a)

    def rows(keys, left, right):
        out = []
        for key in keys:
            case, uri = key.split("|")
            out.append({"case": case,
                        "document": uri.replace("corpus://", ""),
                        labels[0]: left[key], labels[1]: right[key]})
        return out

    moved_keys = [key for key in pairs if a[key] != b[key]]
    moved = rows(moved_keys, a, b)

    # Which pairs the budget keeps, not how many. The claim this file used to
    # make, that the budget difference is a different difference from the
    # ranking movement, cannot be read off two totals: offsetting changes
    # produce the same totals as no changes. It is a statement about which
    # pairs, so it needs the pairs.
    ba, bb = budget[labels[0]], budget[labels[1]]
    budget_keys = [key for key in pairs if ba[key] != bb[key]]
    budget_moved = rows(budget_keys, ba, bb)
    shared = sorted(set(moved_keys) & set(budget_keys))

    depth = max((r for r in list(a.values()) + list(b.values())
                 if r is not None), default=0)
    curve, disagree = [], []
    for k in range(1, depth + 1):
        ha = sum(1 for key in pairs if a[key] is not None and a[key] <= k)
        hb = sum(1 for key in pairs if b[key] is not None and b[key] <= k)
        curve.append({"k": k, labels[0]: ha, labels[1]: hb})
        if ha != hb:
            disagree.append(k)

    return {"labels": labels, "pairs": len(pairs), "depth": depth,
            "moved": moved, "curve": curve, "disagree_at": disagree,
            "at_run_limit": {
                "limit": config["run_limit"],
                "hits": {label: sum(1 for v in budget[label].values() if v)
                         for label in labels},
                "moved": budget_moved,
                "shared_with_ranking": [k.replace("corpus://", "")
                                        for k in shared],
            },
            "dataset_fingerprint": dataset_fingerprint(DATASET),
            "corpus_fingerprint": fingerprint(load_corpus()),
            "index_fingerprints": served,
            "rank_limit": RANK_LIMIT}


def budget_claim(result, a, b):
    """What the budget difference is, stated from the pairs behind it.

    This sentence used to read "the difference is not the same one" off two
    totals, which cannot support it: the same pair moving could produce both
    differences, and offsetting pairs could hide a difference in either. It is
    a claim about which pairs, so it is answered with the pairs.
    """
    limit = result["at_run_limit"]
    moved = limit["moved"]
    if not moved:
        return ("No pair is kept by one chunker's budget and dropped by the "
                "other, so the budget separates these two indexes no more "
                "than the ranking does.")

    names = ", ".join(f"`{row['case']}`:{row['document']}" for row in moved)
    shared = limit["shared_with_ranking"]
    if not shared:
        return (f"{len(moved)} pair(s) survive one budget and not the other: "
                f"{names}. No relevant document's rank moved for any of them, "
                f"so the budget difference is not a re-ranking of the "
                f"documents this dataset scores. What it is instead is not "
                f"measured here: a document ahead of them contributing two "
                f"passages under one chunker and one under the other would "
                f"produce it, and so would a distractor moving, and neither "
                f"appears in the table above. Read this as the two effects "
                f"being distinct in the ranking of relevant documents, not as "
                f"the budget being independent of ordering.")
    return (f"{len(moved)} pair(s) survive one budget and not the other: "
            f"{names}. {len(shared)} of them also changed rank, so the two "
            f"differences are not independent and the budget figure should "
            f"not be read as measuring something the ranking does not.")


def cross_markdown(result):
    a, b = result["labels"]
    lines = [
        "# Does the chunker move the document ranking?",
        "",
        "Generated by `evals/runner.py --cross-check`. Do not hand-edit.",
        "",
        f"Both indexes scored against the same {result['pairs']} (case, "
        f"document) pairs, at every k from 1 to {result['depth']}, which is "
        f"the deepest rank any relevant document reaches. The k values are "
        f"not chosen here: choosing them is how this was got wrong the first "
        f"time.",
        "",
    ]
    moved_n = len(result["moved"])
    if result["disagree_at"]:
        ks = ", ".join(str(k) for k in result["disagree_at"])
        lines += [
            f"**The two disagree at k = {ks}**, and "
            f"{moved_n} of {result['pairs']} pairs land at a different rank. "
            f"They agree at every other k, which is why a grid that skips "
            f"these values reports them as identical.",
        ]
    elif moved_n:
        lines += [
            f"**{moved_n} of {result['pairs']} pairs land at a different "
            f"rank, and the hit counts are identical at every k anyway.** The "
            f"movements offset. No grid of any resolution would separate "
            f"these two indexes, and documents are still moving underneath: "
            f"the table below is the measurement, the counts are not.",
        ]
    else:
        lines += [
            "**No relevant document lands at a different rank under either "
            "chunker**, so the hit counts are identical at every k. Both "
            "facts are measured here: equal counts alone would not establish "
            "the first, because movements can offset.",
        ]

    lines += [
        "",
        "## Relevant documents whose rank moved",
        "",
        f"| case | document | {a} | {b} |",
        "| --- | --- | --- | --- |",
    ]
    if result["moved"]:
        for row in result["moved"]:
            lines.append(f"| `{row['case']}` | {row['document']} | "
                         f"{row[a]} | {row[b]} |")
    else:
        lines.append("| _none_ | | | |")

    limit = result["at_run_limit"]
    ha, hb = limit["hits"][a], limit["hits"][b]
    lines += [
        "",
        f"## At the passage budget of {limit['limit']}",
        "",
        f"| index | relevant documents reached |",
        "| --- | --- |",
        f"| {a} | {ha}/{result['pairs']} |",
        f"| {b} | {hb}/{result['pairs']} |",
        "",
        budget_claim(result, a, b),
        "",
        "Both figures are measured by this file. `latest.md` reports the "
        "budget for the baseline index only, so quoting the other one from it "
        "would be quoting something it does not contain.",
        "",
        "## Hits at every k",
        "",
        f"| k | {a} | {b} |",
        "| --- | --- | --- |",
    ]
    for row in result["curve"]:
        mark = "  **differs**" if row["k"] in result["disagree_at"] else ""
        lines.append(f"| {row['k']} | {row[a]}/{result['pairs']} | "
                     f"{row[b]}/{result['pairs']}{mark} |")

    lines += [
        "",
        "Hits over (case, document) pairs, ranked over distinct documents "
        "with nothing truncating. This is the ranking alone: what each "
        "chunker delivers inside a fixed passage budget is "
        "`precedent_hit_rate@limit` in `latest.md`, and the two answer "
        "different questions.",
        "",
        f"Corpus `{result['corpus_fingerprint'][:16]}`, ground truth "
        f"`{result['dataset_fingerprint'][:16]}`, index {a} "
        f"`{result['index_fingerprints'][a][:16]}`, index {b} "
        f"`{result['index_fingerprints'][b][:16]}`. Either index changing "
        f"under this comparison fails the check rather than moving the "
        f"figures quietly. Regenerate and diff with "
        f"`python3 evals/runner.py --config evals/config.yaml --cross-check "
        f"--check`.",
        "",
    ]
    return "\n".join(lines)


def compare(path_a, path_b):
    with open(path_a) as handle:
        a = json.load(handle)
    with open(path_b) as handle:
        b = json.load(handle)

    modes = {a.get("mode"), b.get("mode")}
    if modes == {"judgement"}:
        return compare_judgement(path_a, a, path_b, b)
    if len(modes) > 1:
        print(f"FAIL  these are different modes ({a.get('mode')} and "
              f"{b.get('mode')}). Retrieval measures the surface on one "
              f"canonical query per case; judgement measures the agent on "
              f"the queries it chose. Nothing lines up between them.")
        return 1

    # Everything a delta silently absorbs if it moved between two runs. The
    # corpus was checked from the start; the rest were not, and each of them
    # produces a plausible number rather than an error.
    for label, path, get in (
            ("corpus", "corpus.fingerprint",
             lambda r: r["corpus"]["fingerprint"]),
            ("ground truth", "dataset.fingerprint",
             lambda r: r.get("dataset", {}).get("fingerprint")),
            ("relevance floor", "surface.floor_applied",
             lambda r: r.get("surface", {}).get("floor_applied")),
            ("passage budget", "at_run_limit.limit",
             lambda r: r["at_run_limit"]["limit"]),
            # A constant today, which is the argument for checking it: a
            # constant that moves is the one nobody re-reads. Truncating the
            # ranking moves both hit rate and mrr.
            ("ranking limit", "surface.rank_limit",
             lambda r: r.get("surface", {}).get("rank_limit")),
            ("k list", "k", lambda r: r["k"])):
        va, vb = get(a), get(b)
        if va != vb:
            print(f"FAIL  these runs used a different {label}, so the delta "
                  f"is that changing and not retrieval improving:")
            print(f"        {path_a}  {path} = {va}")
            print(f"        {path_b}  {path} = {vb}")
            return 1
        if va is None:
            print(f"FAIL  neither run records its {label} ({path}). A record "
                  f"written before that was recorded cannot be compared: "
                  f"re-run both.")
            return 1

    fa = a.get("index_fingerprint")
    fb = b.get("index_fingerprint")
    if a["index"] == b["index"] and a["chunker"] == b["chunker"] and fa != fb:
        print(f"FAIL  both runs name {a['index']}, and the file differed "
              f"between them:")
        print(f"        {path_a}  index_fingerprint = {fa}")
        print(f"        {path_b}  index_fingerprint = {fb}")
        print("        One index under one name, changed underneath. The "
              "delta is that change.")
        return 1

    print(f"{a['label']} ({a['chunker']}, reranker {a['reranker']}, "
          f"index {str(fa)[:12]})  ->  "
          f"{b['label']} ({b['chunker']}, reranker {b['reranker']}, "
          f"index {str(fb)[:12]})\n")
    ks = a["k"]
    print("  k    hit_rate@k              mrr@k")
    for k in ks:
        ra, rb = a["retrieval"][str(k)], b["retrieval"][str(k)]
        delta = rb["precedent_hit_rate"] - ra["precedent_hit_rate"]
        dmrr = rb["mrr"] - ra["mrr"]
        print(f"  {k:<4} {pct(ra['precedent_hit_rate']):>6} -> "
              f"{pct(rb['precedent_hit_rate']):>6}  {delta * 100:+5.1f}pp     "
              f"{ra['mrr']:.3f} -> {rb['mrr']:.3f}  {dmrr:+.3f}")

    la, lb = a["at_run_limit"], b["at_run_limit"]
    print(f"\n  @limit {la['limit']}  {pct(la['precedent_hit_rate'])} -> "
          f"{pct(lb['precedent_hit_rate'])}  "
          f"{(lb['precedent_hit_rate'] - la['precedent_hit_rate']) * 100:+.1f}pp"
          f"   ({la['hits']}/{la['pairs']} -> {lb['hits']}/{lb['pairs']})")
    # This used to end "the document ranking above is chunker-blind on this
    # corpus", which is a claim about k values the caller did not necessarily
    # ask for. Two runs on a grid that skips the k where they differ print
    # zeroes, and the sentence turned that into a finding.
    flat = all(a["retrieval"][str(k)]["precedent_hit_rate"] ==
               b["retrieval"][str(k)]["precedent_hit_rate"] for k in ks)
    if flat:
        print(f"          Identical at k = "
              f"{', '.join(str(k) for k in ks)}, which is this run's grid and "
              f"not every k. --cross-check scores every k and reports where "
              f"they part.")

    print()
    for label, key in (("p50", "p50"), ("p95", "p95")):
        print(f"  {label}   {a['latency_ms'][key]}ms -> "
              f"{b['latency_ms'][key]}ms")

    missing = sorted(set(a["not_measured"]) & set(b["not_measured"]))
    if missing:
        print(f"\n  Unmeasured in both, so the comparison says nothing about "
              f"them: {', '.join(missing)}")
    return 0


# What must match before two judgement records can appear in one delta or one
# published grid. One list, two callers: the grid used to check three of these
# and --compare eleven, so CI could approve a table comparing records --compare
# would refuse. Sol found that at the gate.
JUDGEMENT_PINS = [
    ("corpus", "corpus.fingerprint", lambda r: r["corpus"]["fingerprint"]),
    ("ground truth", "dataset.fingerprint",
     lambda r: r["dataset"]["fingerprint"]),
    ("case set", "dataset.ids", lambda r: r["dataset"]["ids"]),
    ("relevance floor", "surface.floor_applied",
     lambda r: r["surface"]["floor_applied"]),
    ("agent spec", "agent.spec_fingerprint",
     lambda r: r["agent"]["spec_fingerprint"]),
    ("agent model", "agent.model", lambda r: r["agent"]["model"]),
    ("agent task", "agent.task", lambda r: r["agent"].get("task")),
    # What ran the agent, by CLI version and by the content of the provider
    # module the patch edits in place. Two installs reporting one version
    # behave differently when only one is patched, and tool calling is the
    # whole task. Records made before this was pinned carry None, which
    # compares equal to each other and refuses against a pinned one.
    ("agent runtime", "agent.runtime",
     lambda r: (r["agent"].get("runtime") or {}).get("cli_version")),
    ("provider module", "agent.runtime.provider_fingerprint",
     lambda r: (r["agent"].get("runtime") or {}).get("provider_fingerprint")),
    ("scorer", "scorer.fingerprint",
     lambda r: (r.get("scorer") or {}).get("fingerprint")),
    ("judge model", "judged.model",
     lambda r: (r.get("judged") or {}).get("model")),
    ("judge transport", "judged.transport",
     lambda r: (r.get("judged") or {}).get("transport", "anthropic")),
    # Recorded since the transport switch and compared nowhere, so two cursor
    # runs on different CLI builds or different efforts read as one judge.
    ("judge CLI", "judged.cli_version",
     lambda r: (r.get("judged") or {}).get("cli_version")),
    ("judge effort", "judged.effort",
     lambda r: (r.get("judged") or {}).get("effort")),
    ("judge sampling", "judged.sampling",
     lambda r: (r.get("judged") or {}).get("sampling")),
    ("judge temperature", "judged.temperature",
     lambda r: (r.get("judged") or {}).get("temperature")),
    # Truncation decides whether a verdict is a judge error or a scored
    # claim, so it moves a denominator without moving a prompt or a model.
    ("judge token limit", "judged.max_tokens",
     lambda r: (r.get("judged") or {}).get("max_tokens")),
    ("judge scorer", "judged.scorer_fingerprint",
     lambda r: (r.get("judged") or {}).get("scorer_fingerprint")),
    ("groundedness judge prompt", "judged.prompts.groundedness.fingerprint",
     lambda r: ((r.get("judged") or {}).get("prompts") or {})
     .get("groundedness", {}).get("fingerprint")),
    ("divergence judge prompt", "judged.prompts.divergence.fingerprint",
     lambda r: ((r.get("judged") or {}).get("prompts") or {})
     .get("divergence", {}).get("fingerprint")),
]


def judgement_index_mismatch(records):
    """Two records naming one index that was not the same file.

    Not a flat pin: the chunker arms name different indexes on purpose. What
    cannot happen is two records naming the same path whose contents differ,
    because then a delta credited to a prompt also contains a rebuilt index.
    Sol found this at the gate: index_fingerprint was recorded and compared
    only in retrieval mode.
    """
    by_path = {}
    for record in records:
        by_path.setdefault(record["index"], set()).add(
            record.get("index_fingerprint"))
    for path, fingerprints in by_path.items():
        if len(fingerprints) > 1:
            return path, sorted(str(f)[:16] for f in fingerprints)
    return None


def judgement_mismatch(records):
    """The first pin two of these records disagree on, or None.

    Returns (label, path, [(record label, value), ...]) so a caller can say
    which records parted and on what, rather than that something did.
    """
    for label, path, get in JUDGEMENT_PINS:
        seen = [(r.get("label"), get(r)) for r in records]
        values = [v for _, v in seen]
        if any(v != values[0] for v in values):
            return label, path, seen
    return None


def compare_judgement(path_a, a, path_b, b):
    """Two live sweeps, and what may legitimately differ between them.

    The retrieval comparison refuses when an input moved because the delta
    would be that input rather than retrieval. Here there is a second reason
    to be strict: a judgement sweep is one sample of a stochastic system, so
    a delta small enough to be the model having a different day must not be
    dressed up as a result. This prints the deltas and says that plainly; it
    does not test significance, and 38 cases would not support much of one.
    """
    for label, path, get in JUDGEMENT_PINS:
        va, vb = get(a), get(b)
        if va != vb:
            print(f"FAIL  these sweeps used a different {label}, so the delta "
                  f"is that changing and not the arm:")
            print(f"        {path_a}  {path} = "
                  f"{va if label != 'case set' else str(va)[:80]}")
            print(f"        {path_b}  {path} = "
                  f"{vb if label != 'case set' else str(vb)[:80]}")
            return 1

    clash = judgement_index_mismatch([a, b])
    if clash:
        path, fingerprints = clash
        print(f"FAIL  both runs name {path} and the file differed between "
              f"them: {', '.join(fingerprints)}. One index under one name, "
              f"rebuilt underneath, so the delta contains a retrieval change "
              f"as well as an arm change.")
        return 1

    changed = [name for name, get in (
        ("index", lambda r: r["arm"]["index"]),
        ("system prompt", lambda r: r["arm"]["system_prompt"]))
        if get(a) != get(b)]
    if len(changed) > 1:
        print(f"FAIL  these arms differ in {' and '.join(changed)}. Two "
              f"changes at once produce one delta that belongs to neither: "
              f"record an arm that changes one of them.")
        return 1
    if not changed:
        print(f"FAIL  these two arms are the same configuration, so the "
              f"delta is the run-to-run variance of a live model rather "
              f"than an experiment. That is a real number and this is not "
              f"the tool that reports it.")
        return 1

    print(f"{a['label']} -> {b['label']}, {changed[0]} changed\n")
    print(f"  {a['label']:<24} {a['arm'][changed[0].replace(' ', '_')]}")
    print(f"  {b['label']:<24} {b['arm'][changed[0].replace(' ', '_')]}\n")

    def show(name, block_a, block_b, lower_is_better=False,
             denominator_is_an_outcome=False):
        if not block_a or not block_b or block_a.get("value") is None \
                or block_b.get("value") is None:
            print(f"  {name:<22} {'-':>7}    {'-':>7}          not scored in "
                  f"both runs")
            return
        delta = (block_b["value"] - block_a["value"]) * 100
        # Some rates are scored over what the run itself produced. An arm that
        # retrieved fewer documents that apply has fewer of them to omit, so
        # its omission rate improves by doing less, and calling that better
        # would be the fitting move in miniature. The judged rates are the
        # same shape and were missed on the first pass: groundedness_judge is
        # scored over claims offered, so making fewer and easier ones raises
        # it, and divergence_quality is scored over near-miss precedents
        # offered, so failing to offer the diverging record at all improves
        # it. Grok found that on the second round of PR #17.
        moved = (denominator_is_an_outcome
                 and block_a["denominator"] != block_b["denominator"])
        direction = ""
        if abs(delta) >= 0.05 and not moved:
            better = (delta < 0) if lower_is_better else (delta > 0)
            direction = "  better" if better else "  worse"
        elif moved:
            direction = "  denominators differ"
        print(f"  {name:<22} {pct(block_a['value']):>7} -> "
              f"{pct(block_b['value']):>7}  {delta:+6.1f}pp{direction}"
              f"   ({block_a['numerator']}/{block_a['denominator']} -> "
              f"{block_b['numerator']}/{block_b['denominator']})")

    da, db = a["deterministic"], b["deterministic"]
    print("  Measured by code")
    show("false_precedent_rate", da["false_precedent_rate"],
         db["false_precedent_rate"], lower_is_better=True)
    show("applies_omission_rate", da.get("applies_omission_rate"),
         db.get("applies_omission_rate"), lower_is_better=True,
         denominator_is_an_outcome=True)
    show("no_precedent_accuracy", da["no_precedent_accuracy"],
         db["no_precedent_accuracy"])
    show("false_refusal_rate", da["false_refusal_rate"],
         db["false_refusal_rate"], lower_is_better=True)
    show("groundedness_log", da["groundedness_log"], db["groundedness_log"])
    show("agent_reach", da["agent_reach"], db["agent_reach"])

    ja, jb = a.get("judged"), b.get("judged")
    print("\n  Judged by a model")
    if ja and jb and ja["model"] != jb["model"]:
        print(f"        judged by different models ({ja['model']} and "
              f"{jb['model']}), so these two rows are not a delta")
    else:
        show("groundedness_judge", (ja or {}).get("groundedness_judge"),
             (jb or {}).get("groundedness_judge"),
             denominator_is_an_outcome=True)
        show("divergence_quality", (ja or {}).get("divergence_quality"),
             (jb or {}).get("divergence_quality"),
             denominator_is_an_outcome=True)
        print("        Both judged rates are scored over what the run "
              "offered: fewer claims, or a diverging record never offered, "
              "raise them. Read the counts, not the percentage.")

    print(f"\n  failures               "
          f"{da['failures']['total']}/{da['cases']} -> "
          f"{db['failures']['total']}/{db['cases']}")
    for key in ("p50", "p95"):
        print(f"  {key:<22} {da['latency_ms'][key] / 1000:7.1f}s -> "
              f"{db['latency_ms'][key] / 1000:7.1f}s")

    words_a = da.get("applicability_offered") or {}
    words_b = db.get("applicability_offered") or {}
    if words_a or words_b:
        print(f"\n  applicability offered   "
              f"{words_a or 'none'}  ->  {words_b or 'none'}")
        if not words_a.get("applies") and not words_b.get("applies"):
            print("        Neither run used `applies`, so the false "
                  "precedent rate above is zero over a word the agent never "
                  "reached for. Read applies_omission_rate instead.")

    print(f"\n  One sweep each, {len(a['dataset']['ids'])} cases, a model at "
          f"temperature {a['agent']['temperature']} on both sides. A few "
          f"points either way is what the same arm does twice; read the "
          f"named failures in each table, not the third decimal.")
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
                        help="UTC timestamp for the record, and the name of "
                             "the file. Defaults to now. It does not make a "
                             "record reproducible byte for byte: the JSON "
                             "carries measured latency, which varies per run. "
                             "latest.md is the artefact with that property, "
                             "and it is why no latency figure is in it.")
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"))
    parser.add_argument("--cross-check", action="store_true",
                        help="Score both indexes in config.cross_check at "
                             "every k and write chunker-comparison.md.")
    parser.add_argument("--check", action="store_true",
                        help="Regenerate latest.md and fail if it differs. "
                             "Writes nothing, so CI can run it.")
    parser.add_argument("--mode", default="retrieval",
                        choices=["retrieval", "judgement"])
    # Everything after -- goes to evals/judgement.py, which has flags this
    # parser has no business knowing about (--arm, --cases, --no-judge,
    # --dry-run). Passing them through beats mirroring them here and letting
    # the two drift.
    argv = sys.argv[1:]
    judgement_extras = []
    if "--" in argv:
        cut = argv.index("--")
        argv, judgement_extras = argv[:cut], argv[cut + 1:]
    args = parser.parse_args(argv)

    if args.compare:
        return compare(*args.compare)

    if args.mode == "judgement":
        # Its own module, and its own config: judgement mode needs a live oa
        # run per case, an API key and the patches/ provider patch, and it
        # produces a record of one run rather than a regenerable artefact.
        # Nothing it writes is checked for drift, which is the opposite of
        # every rule this file is built on.
        import judgement
        argv = ["--config", args.config or "evals/config.judgement.yaml"]
        if args.label:
            argv += ["--arm", args.label]
        if args.stamp:
            argv += ["--stamp", args.stamp]
        sys.argv = [judgement.__file__] + argv + judgement_extras
        return judgement.main()

    config = load_config(args.config, {"index": args.index,
                                       "chunker": args.chunker,
                                       "label": args.label,
                                       "port": args.port})

    if args.cross_check:
        result = cross_check(config)
        table = cross_markdown(result)
        path = os.path.join(RESULTS, "chunker-comparison.md")
        if args.check:
            current = open(path).read() if os.path.exists(path) else ""
            if current == table:
                print(f"{path} is current")
                return 0
            print(f"{path} does not match a fresh cross-check. Re-record it:\n"
                  f"  python3 evals/runner.py --config evals/config.yaml "
                  f"--cross-check")
            return 1
        os.makedirs(RESULTS, exist_ok=True)
        with open(path, "w") as handle:
            handle.write(table)
        where = (f"k = {', '.join(str(k) for k in result['disagree_at'])}"
                 if result["disagree_at"] else "no k")
        la, lb = result["labels"]
        hits = result["at_run_limit"]["hits"]
        print(f"{la} against {lb}: {len(result['moved'])} of "
              f"{result['pairs']} pairs moved rank, hits differ at {where}")
        print(f"  at the passage budget of "
              f"{result['at_run_limit']['limit']}: {hits[la]}/"
              f"{result['pairs']} against {hits[lb]}/{result['pairs']}")
        print(f"wrote {path}")
        return 0

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

    # latest.md is the committed baseline table, so only the baseline run may
    # write it. An exploratory --index run used to overwrite it silently, and
    # the next --check reported drift that was the scratch run rather than the
    # corpus.
    if args.config:
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
          f"({limit['hits']}/{limit['pairs']}), at a fixed passage budget")
    print(f"  floor silence {result['floor_silence']['silent_at_the_floor']}/"
          f"{result['floor_silence']['novel_cases']} no-precedent cases")
    print(f"\nwrote {out}")
    if args.config:
        print(f"wrote {latest}")
    else:
        print(f"left {latest} alone: it is the baseline table, and this run "
              f"did not use --config")
    return 0 if top["pairs"] else 1


if __name__ == "__main__":
    sys.exit(main())
