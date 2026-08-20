#!/usr/bin/env python3
"""
Conformance suite for the precedent_archive surface.

Stdlib only. Starts the mock on a spare port, drives it over JSON-RPC, and
asserts the contract from interfaces/PRECEDENT.md. Exits non-zero on failure,
so it belongs in CI next to the index freshness check.

    python3 corpus/eval.py
    python3 corpus/eval.py --index corpus/index.fixed.json   # the baseline

This is not retrieval quality measurement. That is Phase 4, it needs a scored
dataset, and it belongs in evals/. What is checked here is narrower and harder
to fudge: that a claim can only rest on something citable, that the time bound
holds, and that the qualifiers which stop a passage being over-read survive
the trip. Every case here was run by hand while building the surface, which is
exactly why it is worth having a machine run them from now on.

Cases marked OBSERVED are recorded rather than asserted. They are known
limitations with a measured value, kept visible instead of tidied away.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PORT = 8526          # not 8426: never contend with a running adapter
D1_BOUND = "2026-03-03"      # act one, the D+1 view's as_of
BRIDGE_BOUND = "2026-03-17"  # act two, the D+15 bridge


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


def tools_list():
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}", data=body,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())["result"]


def uris(result):
    return {p["source_uri"] for p in result.get("passages", [])}


# Each case returns (ok, detail). Kept as functions rather than a declarative
# table because the interesting assertions are relational: what came back
# versus what the archive holds versus what the bound allowed.

def case_novel_incident():
    """A genuinely novel incident returns nothing, and says what it searched."""
    r = rpc("precedent_search", {
        "signature_terms": ["tls.certificate.expiry"],
        "symptom_text": "mutual TLS handshake failures between two brokers "
                        "after a certificate rotation",
        "before": BRIDGE_BOUND})
    ok = (r["passages"] == []
          and r["candidates_considered"] > 0
          and r["cleared_floor"] == 0
          and r["floor_applied"] > 0)
    return ok, (f"considered={r['candidates_considered']} "
                f"scored={r['total_scoring_above_zero']} "
                f"cleared={r['cleared_floor']}")


def case_near_miss():
    """The near miss comes back, carrying what makes it a near miss."""
    r = rpc("precedent_search", {
        "signature_terms": ["host.memory.exhaustion"],
        "symptom_text": "memory exhaustion on a batch integration host, swap "
                        "climbing, JVM resident",
        "before": BRIDGE_BOUND})
    hit = [p for p in r["passages"]
           if p["source_uri"] == "corpus://incidents/INC-2411"]
    ok = bool(hit) and all(p["document_cause_claimed"] and
                           p["claim_scope"] == "document" for p in hit)
    return ok, f"INC-2411 passages={len(hit)} of {len(r['passages'])}"


def case_superseded():
    """A precedent whose resolution was invalidated arrives saying so."""
    r = rpc("precedent_search", {
        "signature_terms": ["host.cpu.saturation"],
        "symptom_text": "denial analysis daemon holding CPU sustained after "
                        "denial volume rises",
        "before": BRIDGE_BOUND})
    hit = [p for p in r["passages"]
           if p["source_uri"] == "corpus://incidents/INC-2288"]
    ok = bool(hit) and any(p["document_superseded_by"] for p in hit)
    return ok, f"INC-2288 passages={len(hit)}, superseded_by carried"


def case_draft_status():
    """A passage from an unsubmitted draft cannot pass as a filed record."""
    r = rpc("precedent_search", {
        "symptom_text": "swap thrash overlapping batch windows daylight "
                        "saving schedule change",
        "before": BRIDGE_BOUND})
    drafts = [p for p in r["passages"] if p["record_status"] == "draft"]
    ok = bool(drafts)
    return ok, f"draft passages={len(drafts)} of {len(r['passages'])}"


def case_time_bound_excludes():
    """The bound removes later records and reports how many."""
    early = rpc("precedent_search", {
        "signature_terms": ["host.memory.exhaustion"],
        "symptom_text": "memory exhaustion on a batch integration host",
        "before": "2025-09-01"})
    late = rpc("precedent_search", {
        "signature_terms": ["host.memory.exhaustion"],
        "symptom_text": "memory exhaustion on a batch integration host",
        "before": BRIDGE_BOUND})
    ok = (early["excluded_by_before"] > late["excluded_by_before"]
          and early["candidates_considered"] < late["candidates_considered"]
          and "corpus://incidents/INC-2411" not in uris(early))
    return ok, (f"excluded early={early['excluded_by_before']} "
                f"late={late['excluded_by_before']}")


def case_hindsight_trap():
    """The D+8 working note is unreachable from act one.

    It is the only document recent enough to catch a search that forgets its
    bound, and it names a cause the investigation never established. If this
    passes at the D+1 bound, the archive has become a back door to a cause this
    incident never confirmed and everything else in the demo is theatre.
    """
    # Same query both times. Only the bound changes, so a difference in the
    # result is the bound and nothing else.
    query = {"signature_terms": ["host.memory.exhaustion"],
             "symptom_text": "audit denial log naming the source domain "
                             "outstanding while the incident is running"}
    d1 = rpc("precedent_search", {**query, "before": D1_BOUND})
    later = rpc("precedent_search", {**query, "before": "2026-03-31"})
    trap = "corpus://incidents/DRAFT-2601"
    ok = trap not in uris(d1) and trap in uris(later)
    return ok, (f"absent at {D1_BOUND}={trap not in uris(d1)}, "
                f"reachable at 2026-03-31={trap in uris(later)}")


def case_trap_survives_competition():
    """The trap is still reached at the bridge, under the query the spec uses.

    case_hindsight_trap proves the bound excludes it at D+1 using a long,
    targeted query. That is a property of the bound. It says nothing about
    whether an agent issuing the query the prompt actually steers it to, the
    signature type alone at the demo's limit, ever sees the record.

    It has to. SCENARIO.md's fence is explicit that the time bound alone does
    not handle this document, because it had genuinely been written by the
    time the bridge opens: retrieval must reach it and then reject it on
    record_status and the attribution guard. A trap nothing retrieves is not
    a trap, and the grounding demo's assertion about it goes vacuous without
    the demo failing.

    This case exists because that happened. Five distractors widened the tie
    band past the limit and the working note fell out of the returned set,
    while this suite stayed green.
    """
    r = rpc("precedent_search", {"signature_terms": ["host.memory.exhaustion"],
                                 "before": BRIDGE_BOUND, "limit": 8})
    docs = {u.rsplit("/", 1)[-1] for u in uris(r)}
    ok = "DRAFT-2601" in docs and "INC-2411" in docs
    return ok, (f"trap={'DRAFT-2601' in docs} near miss={'INC-2411' in docs} "
                f"in {len(docs)} documents at limit 8")


def case_before_required():
    """A search with no bound is refused, not silently unbounded."""
    r = rpc("precedent_search", {"symptom_text": "memory exhaustion"})
    ok = "_fault" in r and "before is required" in r["_fault"]
    return ok, r.get("_fault", "NOT REFUSED")[:60]


def case_citations_resolve():
    """Every passage_id a search returns round-trips, verbatim."""
    seeds = [
        {"signature_terms": ["host.memory.exhaustion"], "before": BRIDGE_BOUND},
        {"signature_terms": ["host.cpu.saturation"], "before": BRIDGE_BOUND},
        {"symptom_text": "change correlation package history onset",
         "before": BRIDGE_BOUND},
    ]
    checked = bad = 0
    for args in seeds:
        for p in rpc("precedent_search", args)["passages"]:
            got = rpc("passage_get", {"passage_id": p["passage_id"]})
            checked += 1
            if got.get("text") != p["text"] or not got.get("heading_path"):
                bad += 1
    return bad == 0 and checked > 0, f"{checked} round-tripped, {bad} bad"


def case_unresolvable_citation():
    """A passage_id that does not exist is a fault, never an empty success."""
    r = rpc("passage_get", {"passage_id": "p-notarealpassage"})
    ok = "_fault" in r
    return ok, r.get("_fault", "NOT REFUSED")[:60]


def case_identity_stripped_signature(index_path):
    """The signature type alone finds the family, without the host id.

    Phase 2 has to pass the signature type and never the entity id, so the
    surface has to work that way round. A retrieval that needs the host id to
    find anything has made identity a similarity feature.
    """
    family = {"corpus://incidents/INC-2411", "corpus://incidents/INC-2350",
              "corpus://incidents/INC-2419"}
    r = rpc("precedent_search", {
        "signature_terms": ["host.memory.exhaustion"],
        "symptom_text": "memory exhaustion recurring on a production host",
        "before": BRIDGE_BOUND})
    found = uris(r) & family
    # Family membership, not absence of the host id: at the bridge bound the
    # archive legitimately holds a record about this host, so checking for the
    # string would fail for the wrong reason.
    ok = bool(found)
    return ok, f"{len(found)} of {len(family)} family records without an entity id in the query"


def case_coverage_hides_chunker(index_path):
    """coverage.describe reports content, never implementation."""
    c = rpc("coverage_describe", {"before": BRIDGE_BOUND})
    index = json.load(open(index_path))
    leaked = [k for k in ("chunker", "store", "embedding_model") if k in c]
    ok = (not leaked
          and c["document_count"] == index["document_count"]
          and c["passage_count"] == index["passage_count"])
    return ok, f"leaked={leaked or 'nothing'} counts match index at the bridge"


def case_coverage_is_bounded():
    """Coverage describes the archive the caller was allowed to see.

    The leak this closes is specific: unbounded, corpus_current_to told a D+1
    caller the archive holds a document dated during the incident, which is
    exactly what the time bound stops search revealing. A refusal cites
    coverage as proof it looked, so coverage that describes documents the
    caller cannot retrieve makes the refusal a misdescription.
    """
    d1 = rpc("coverage_describe", {"before": D1_BOUND})
    late = rpc("coverage_describe", {"before": "2026-03-31"})
    unbounded = rpc("coverage_describe", {})
    ok = (d1["corpus_current_to"] < D1_BOUND
          and d1["document_count"] < late["document_count"]
          and late["corpus_current_to"] == "2026-03-10"
          and "_fault" in unbounded)
    return ok, (f"D+1 current_to={d1['corpus_current_to']} docs={d1['document_count']}, "
                f"late current_to={late['corpus_current_to']} docs={late['document_count']}, "
                f"unbounded refused={'_fault' in unbounded}")


def case_read_only_declared():
    """tools/list tells the truth about the surface and about the query.

    The either/or between signature_terms and symptom_text is asserted on the
    description, not on a top-level anyOf. The Anthropic tool API rejects
    anyOf at the top level of an input_schema and the runner passes the MCP
    schema through verbatim, so a schema that declares it cannot be called by
    the agent that owns the surface. What has to hold is that a caller can
    read the requirement before making the call, not the keyword it is
    written in. The top-level combinator check is part of the assertion:
    a schema that reintroduces one is unusable, however conformant it looks.
    """
    listed = tools_list()["tools"]
    annotated = all(t.get("annotations", {}).get("readOnlyHint") for t in listed)
    search = next(t for t in listed if t["name"] == "precedent_search")
    schema = search["inputSchema"]
    combinators = [k for k in ("anyOf", "oneOf", "allOf") if k in schema]
    text = (search.get("description", "") or "").lower()
    states_either_or = ("signature_terms" in text and "symptom_text" in text
                        and "at least one" in text)
    honest = ("before" in schema.get("required", [])
              and states_either_or and not combinators)
    return annotated and honest, (
        f"readOnlyHint on {len(listed)}/{len(listed)}, "
        f"before required={'before' in schema.get('required', [])}, "
        f"either/or stated={states_either_or}, "
        f"top-level combinators={combinators or 'none'}")


def case_audit_log_names_hits(log_path):
    """The log says what left the surface, by id, and never the passage text.

    This is the only thing that can check a citation. The runner does not bind
    tool results into outputs, so a passage_id in an agent's grounded_in is a
    string the model wrote, whether or not the archive ever returned it, and
    an adapter whose log names only the call leaves every citation
    self-attested. Ids, uris and counts: a log carrying passage text is a
    second copy of the archive in a file nobody is treating as one.
    """
    with open(log_path) as fh:
        fh.seek(0, 2)
        start = fh.tell()
    r = rpc("precedent_search", {
        "signature_terms": ["host.memory.exhaustion"],
        "before": BRIDGE_BOUND, "limit": 8})
    got = rpc("passage_get", {"passage_id": r["passages"][0]["passage_id"]})
    with open(log_path) as fh:
        fh.seek(start)
        log = fh.read()

    logged = re.findall(r"^\[mock-precedent_archive\] hit (\S+) (\S+)$", log, re.M)
    expected = [(p["passage_id"], f"{p['source_uri']}#{p['ordinal']}")
                for p in r["passages"]]
    expected.append((got["passage_id"], f"{got['source_uri']}#{got['ordinal']}"))
    counted = re.search(r"^\[mock-precedent_archive\] returned (\d+) passages", log, re.M)

    # A distinctive run of the passage's own words, which must not appear.
    sample = " ".join(r["passages"][0]["text"].split()[:8])
    ok = (logged == expected
          and counted and int(counted.group(1)) == len(r["passages"])
          and sample not in log)
    return ok, (f"{len(logged)} hit lines for {len(expected)} passages returned, "
                f"text logged={sample in log}")


def case_audit_log_names_arguments(log_path):
    """The log says what the caller asked for, not only what it got.

    Without this the log answers two of the three questions an audit of this
    surface has to answer: whether a call happened, and what left the
    surface. It cannot answer what was asked, and that is the question the
    identity rule turns on. An agent is required to search on the signature
    type and never the entity id, and the only other record of what it
    searched is the queries_issued field in its own output, which is the
    agent's account of its own conduct.

    Caller text, never archive text: the line reproduces the arguments, and
    the rule against a log that copies the corpus is unaffected by it.
    """
    with open(log_path) as fh:
        fh.seek(0, 2)
        start = fh.tell()
    query = {"signature_terms": ["host.memory.exhaustion"],
             "symptom_text": "audit analysis daemon memory",
             "before": BRIDGE_BOUND, "limit": 4}
    r = rpc("precedent_search", query)
    with open(log_path) as fh:
        fh.seek(start)
        log = fh.read()

    logged = re.findall(r"^\[mock-precedent_archive\] args (\S+) (.*)$",
                        log, re.M)
    ok = any(name == "precedent_search" and json.loads(blob) == query
             for name, blob in logged)
    sample = " ".join(r["passages"][0]["text"].split()[:8])
    return (ok and sample not in log,
            f"{len(logged)} args line(s), arguments reproduced={ok}, "
            f"passage text logged={sample in log}")


def observed_degenerate_query():
    """OBSERVED, not asserted: the floor is not a semantic guarantee.

    A query of ordinary English with no domain content still clears it, on a
    corpus this small, because inverse document frequency over 59 passages
    makes words like "record" look distinctive. Filtering by document
    frequency was tried and made it worse: it refused the strongest query
    (the bare signature type) while still passing this one.

    The property that holds, and the one an adapter must reproduce, is
    narrower: a query whose distinctive terms are unseen does not clear the
    floor. The number 0.35 is mock configuration, not a law.
    """
    r = rpc("precedent_search", {
        "symptom_text": "the record was written", "before": BRIDGE_BOUND})
    return None, f"{len(r['passages'])} passages returned for a content-free query"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default="corpus/index.json")
    args = parser.parse_args()

    # Captured rather than discarded: the audit lines are part of the contract
    # now, so the suite has to be able to read them back.
    log_fd, log_path = tempfile.mkstemp(prefix="precedent-archive-", suffix=".log")
    log = os.fdopen(log_fd, "w")
    proc = subprocess.Popen(
        [sys.executable, "mock/adapter.py", "--surface", "precedent_archive",
         "--port", str(PORT), "--index", args.index],
        stdout=log, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                rpc("coverage_describe", {"before": BRIDGE_BOUND})
                break
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.1)
        else:
            print("adapter did not come up")
            return 2

        cases = [
            ("novel incident refuses", case_novel_incident),
            ("near miss returned with its claim scoped", case_near_miss),
            ("superseded precedent surfaced", case_superseded),
            ("draft status survives retrieval", case_draft_status),
            ("time bound excludes and reports", case_time_bound_excludes),
            ("hindsight trap unreachable at D+1", case_hindsight_trap),
            ("hindsight trap still reached at the bridge",
             case_trap_survives_competition),
            ("before is required", case_before_required),
            ("citations round-trip verbatim", case_citations_resolve),
            ("unresolvable citation faults", case_unresolvable_citation),
            ("signature type works without entity id",
             lambda: case_identity_stripped_signature(args.index)),
            ("coverage hides implementation",
             lambda: case_coverage_hides_chunker(args.index)),
            ("coverage is bounded like search", case_coverage_is_bounded),
            ("tools/list declares read-only and the real requirements",
             case_read_only_declared),
            ("the log names every passage that left the surface",
             lambda: case_audit_log_names_hits(log_path)),
            ("the log names what the caller asked for",
             lambda: case_audit_log_names_arguments(log_path)),
        ]

        failures = 0
        print(f"precedent_archive conformance, index {args.index}\n")
        for name, fn in cases:
            ok, detail = fn()
            print(f"  {'pass' if ok else 'FAIL'}  {name}: {detail}")
            failures += 0 if ok else 1

        _, detail = observed_degenerate_query()
        print(f"\n  obs   floor is not a semantic guarantee: {detail}")

        print(f"\n{len(cases) - failures}/{len(cases)} passed")
        return 1 if failures else 0
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        log.close()
        os.unlink(log_path)


if __name__ == "__main__":
    sys.exit(main())
