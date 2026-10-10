#!/usr/bin/env python3
"""An anchor set for the judged metrics: hand labels a judge is measured against.

`groundedness_judge` is readable as a comparison and not as a score, because
the same claims score about forty points apart depending on which model
family judges them and nothing in the repository can say which family is
right. The remedy is not more judges. It is a key: claims labelled by a
person, against the passages they cite, that each judge is then measured
against. The report becomes "this judge over-flags absence claims by N"
instead of "the judges disagree".

    python3 evals/anchor.py --extract          # write the labelling sheet
    python3 evals/anchor.py --show 3           # one claim with its passages
    python3 evals/anchor.py --score            # each judge against the labels
    python3 evals/anchor.py --check            # CI: the sheet still matches the records
    python3 evals/anchor.py --self-test

The sheet is `evals/anchor.yaml`. `--extract` selects the claims on which the
judge families disagreed, because that is where the rubric is ambiguous: the
record's published verdicts (`judged`, produced by the round `rejudged_at`
names) against the latest round with verdicts from every other family. A
split between two rounds of one family is not a family disagreement and is
not selected. It writes them with `label` and `asserts_absence` unset. It never writes a
judge's verdict into the sheet: a labeller shown who said what inherits a
conclusion instead of reaching one, which is the anchoring failure this
repository exists to demonstrate. The labels are a person's, and the code
cannot tell a person's label from a copied verdict; what it can do is keep
the sheet honest against the records, which is what `--check` is for.
"""

import argparse
import copy
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evals" / "results"
SHEET = ROOT / "evals" / "anchor.yaml"
INDEXES = {"heading": ROOT / "corpus" / "index.json",
           "fixed": ROOT / "corpus" / "index.fixed.json"}
LABELS = ("supported", "unsupported")


def records(results=RESULTS):
    """Every judgement record, oldest first, by file name."""
    found = sorted(results.glob("judgement-*.json"))
    if not found:
        sys.exit(f"no judgement records under {results}")
    return [(path.name, json.loads(path.read_text())) for path in found]


def family(model):
    """The model family a judging round belongs to, from the id it recorded."""
    return model.split("-")[0] if model else "unknown"


def current(record):
    """The verdicts the record publishes, and the model that produced them.

    `judged` is the verdict set the tables are generated from and it names
    its own model; `judged.model` is that family. The `scorer` block is a
    fingerprint of the scoring code and names no model, so reading one from
    it keys the current verdicts as nobody's, which is how a first version
    counted the Opus block against an earlier Opus round and called the
    split a family disagreement. The round that produced `judged` is not
    necessarily in `judgings` at all: a rejudge stamps `rejudged_at` on the
    record, and the last listed round can be an hour older than it.
    """
    judged = record.get("judged") or {}
    model = judged.get("model")
    if not model:  # guard current_model
        sys.exit(f"{record.get('label')}: judged names no model, so the "
                 f"published verdicts have no family")
    return {"at": record.get("rejudged_at") or record.get("recorded_at", ""),
            "model": model,
            "verdicts": verdict_map((judged.get("groundedness_judge") or {}).get("verdicts") or [])}


def keyed(items, case_of, document_of):
    """Key each item by (case, document, ordinal), the ordinal counting items
    on the same case and document in list order.

    A record can hold two claims on one document, two headings of the same
    runbook, and the judge then records two verdicts for them in the same
    order. Keyed by case and document alone the second overwrites the first
    on both sides, a disagreement on the first claim is lost behind the
    second's agreement, and `--show` would present the survivor. The heading
    record already has that shape on b04.
    """
    out, seen = {}, {}
    for item in items:
        pair = (case_of(item), document_of(item))
        n = seen.get(pair, 0)
        seen[pair] = n + 1
        out[(pair[0], pair[1], n)] = item
    return out


def verdict_map(verdicts):
    return {key: bool(v["verdict"]["supported"]) for key, v in
            keyed(verdicts, lambda v: v["case"], lambda v: v["document"]).items()}


def rounds_with_verdicts(record):
    """The parties to a disagreement: the current family's published verdicts,
    and the latest round with verdicts from every other family.

    The current family is represented by `judged` alone. Its earlier rounds
    are superseded by it, and a split between two rounds of the same family
    is not a family disagreement, which is the only kind the sheet is for.
    A round that recorded only a rate is a number with no claims behind it
    and is not a party to anything.
    """
    published = current(record)
    current_family = family(published["model"])
    parties = {current_family: published}
    for judging in record.get("judgings", []):
        verdicts = (judging.get("groundedness_judge") or {}).get("verdicts")
        if not verdicts:  # guard rate_only
            continue
        fam = family(judging.get("model"))
        if fam == current_family:  # guard other_family
            continue
        parties[fam] = {"at": judging.get("at", ""), "model": judging["model"],
                        "verdicts": verdict_map(verdicts)}
    return parties


def judged_ids(per_case, claim):
    """The cited ids the judge was actually handed: those among the surface's
    hits for the case. The builder drops the rest before calling passage_get,
    so a claim citing one returned passage and one that was never returned
    was judged against one, and showing both would put evidence in front of
    the labeller that the judge never saw."""
    hits = (per_case.get("surface") or {}).get("hits") or {}
    return [pid for pid in claim.get("grounded_in") or [] if pid in hits]


def judged_claim(per_case, claim):
    """Whether the judge was given this claim at all.

    The judge builder in `evals/judgement.py` skips a claim none of whose
    cited ids the archive returned, so the verdict list is a subsequence of
    the claim list. Ordinals have to be counted over the claims the judge
    saw, or a skipped first claim on a document leaves the second claim's
    verdict at ordinal 0 against the first claim's text. The rule is the
    builder's, restated here because the record does not carry it.
    """
    return bool(judged_ids(per_case, claim))


def claims(record, with_ids=False):
    """Every claim the judge was given, keyed by case, document and ordinal
    among judged claims on that pair; the same numbering as the verdicts.
    With `with_ids`, each value is (claim, the cited ids the judge saw)."""
    flat = [(per_case["case"], claim, judged_ids(per_case, claim))
            for per_case in record.get("per_case", [])
            if not per_case.get("failure")
            for claim in (per_case.get("score") or {}).get("claims", [])
            if judged_claim(per_case, claim)]  # guard judged_only
    return {key: ((claim, ids) if with_ids else claim) for key, (case, claim, ids) in
            keyed(flat, lambda t: t[0], lambda t: t[1]["source_uri"]).items()}


def aligned(record):
    """Stop if the published verdicts do not number the judged claims pair for
    pair: then the ordinal is two list positions and not one claim, and no
    sheet drawn from it names anything."""
    counts = {}
    for case, document, _ in claims(record):
        counts[(case, document)] = counts.get((case, document), 0) + 1
    seen = {}
    for case, document, _ in current(record)["verdicts"]:
        seen[(case, document)] = seen.get((case, document), 0) + 1
    for pair in sorted(set(counts) | set(seen)):
        if counts.get(pair, 0) != seen.get(pair, 0):  # guard aligned
            sys.exit(f"{record.get('label')}: {pair[0]} {pair[1]} has "
                     f"{counts.get(pair, 0)} judged claim(s) and "
                     f"{seen.get(pair, 0)} published verdict(s); the ordinal "
                     f"cannot name a claim")


def disagreements(record):
    """Keys on which two families with verdicts reached different answers."""
    aligned(record)
    families = rounds_with_verdicts(record)
    keys = set()
    for fam in families.values():
        keys |= set(fam["verdicts"])
    found = []
    for key in sorted(keys):
        answers = {fam["verdicts"][key] for fam in families.values() if key in fam["verdicts"]}
        if len(answers) > 1:  # guard disagreement
            found.append(key)
    return found


def entry_id(label, case, document, ordinal=0):
    # The first claim on a pair keeps the bare id, so the sheet's existing
    # ids do not move; a second claim on the same document carries its
    # ordinal.
    suffix = f"#{ordinal + 1}" if ordinal else ""
    return f"{label}/{case}/{document.rsplit('/', 1)[-1]}{suffix}"


def extract(results=RESULTS, sheet=SHEET):
    """Write the sheet, keeping any entry already labelled.

    A labelled entry is a person's work and is never regenerated under them:
    the label travels with the id. The sheet carries no claim text and no
    passage ids, only the key that names the claim in its record: the claim
    is model output and belongs in `evals/results/` byte for byte, and a
    copy here would be a second record under a style rule it cannot follow.
    `--show` reads the claim from the record every time.
    """
    existing = {}
    if sheet.exists():
        for entry in yaml.safe_load(sheet.read_text()) or []:
            existing[entry["id"]] = entry
    entries = []
    for name, record in records(results):
        label = record.get("label") or name
        offered = claims(record)
        for case, document, ordinal in disagreements(record):
            claim = offered[(case, document, ordinal)]
            # `aligned` has already held every pair's verdict count to its
            # judged claim count, so a missing claim here is impossible.
            ident = entry_id(label, case, document, ordinal)
            kept = existing.get(ident, {})
            entries.append({
                "id": ident,
                "record": name,
                "case": case,
                "document": document,
                "ordinal": ordinal,
                "label": kept.get("label"),
                "asserts_absence": kept.get("asserts_absence"),
                "unsupported_elements": kept.get("unsupported_elements") or [],
                "note": kept.get("note") or "",
            })
    header = ("# Hand-labelled key for groundedness_judge. Generated by\n"
              "# `python3 evals/anchor.py --extract` from the judgement records: the\n"
              "# claims on which the record's published verdicts and the other judge\n"
              "# family's latest verdicts disagree, which is where the rubric is\n"
              "# ambiguous. Fill `label` (supported | unsupported) and\n"
              "# `asserts_absence` (true | false: does the claim say the prior record\n"
              "# lacks something?) by reading the claim against its cited passages,\n"
              "# `python3 evals/anchor.py --show <n>`. No judge's verdict and no claim\n"
              "# text is in this file on purpose: the claim lives in its record and the\n"
              "# labeller reads it there. `--check` holds every id to its record.\n")
    sheet.write_text(header + yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=88))
    labelled = sum(1 for e in entries if e["label"])
    print(f"{len(entries)} claims on the sheet, {labelled} labelled, {sheet.relative_to(ROOT) if sheet.is_relative_to(ROOT) else sheet}")
    return entries


def load_sheet(sheet=SHEET):
    if not sheet.exists():
        sys.exit(f"no sheet at {sheet}: run --extract first")
    try:
        return yaml.safe_load(sheet.read_text()) or []
    except yaml.YAMLError as exc:  # guard sheet_parse
        sys.exit(f"{sheet} is not valid YAML, a partial write perhaps: {exc}")


def as_the_judge_saw_it(passage):
    """A passage in the representation `passage_get` returns.

    The judge was handed the adapter's response, not the index entry: the
    document-level fields renamed for their scope (`document_cause_claimed`,
    `document_superseded_by`), `claim_scope` added, the signature dropped.
    A labeller reading the raw index entry would be labelling against
    evidence the judge never saw, and a key built that way measures the
    judges against a different surface. So the adapter's own function
    renders it, imported rather than copied.
    """
    sys.path.insert(0, str(ROOT / "mock"))
    from adapter import _cite  # noqa: E402
    return _cite(passage)


def passages_for(record, cited, indexes=INDEXES):
    """The cited passages, as the archive returned them, from the index the
    record was scored on."""
    index = json.loads(indexes[record.get("chunker", "heading")].read_text())
    by_id = {p["passage_id"]: p for p in index.get("passages", [])}
    return [as_the_judge_saw_it(by_id[pid]) if pid in by_id
            else {"passage_id": pid, "error": "not in the current index"}
            for pid in cited]


def show(number, sheet=SHEET, results=RESULTS, indexes=INDEXES):
    entries = load_sheet(sheet)
    if not 1 <= number <= len(entries):  # guard show_range
        sys.exit(f"the sheet has {len(entries)} entries")
    entry = entries[number - 1]
    by_name = dict(records(results))
    record = by_name.get(entry["record"])
    found = claims(record, with_ids=True).get((entry["case"], entry["document"], entry.get("ordinal", 0))) if record else None
    if found is None:  # guard show_claim
        sys.exit(f"{entry['id']}: no such claim in {entry['record']}; run --check")
    claim, cited = found
    print(f"[{number}] {entry['id']}   offered: {claim.get('offered')}   label: {entry['label']}")
    print("\nCLAIM (every field is the agent's; the prior-record half is what the passages must support)")
    for key, value in (claim.get("offered_claim") or {}).items():
        print(f"  {key}: {value}")
    unseen = [pid for pid in claim.get("grounded_in") or [] if pid not in cited]
    print("\nCITED PASSAGES, as the archive returned them to the judge"
          + (f" (the agent also cited {', '.join(unseen)}, which the archive never returned and the judge never saw)" if unseen else ""))
    for passage in passages_for(record, cited, indexes):  # guard show_judged_ids
        print(f"\n  --- {passage.get('passage_id')}  {passage.get('source_uri', '')}  {passage.get('heading_path', '')}")
        for key, value in passage.items():
            if key not in ("passage_id", "source_uri", "heading_path", "text"):
                print(f"  {key}: {value}")
        print()
        for line in str(passage.get("text", passage.get("error", ""))).splitlines():
            print(f"    {line}")


def check(sheet=SHEET, results=RESULTS):
    """The sheet is still a sheet about these records, and its labels are valid."""
    entries = load_sheet(sheet)
    failures = []
    by_name = dict(records(results))
    seen = set()
    for entry in entries:
        ident = entry.get("id", "?")
        if ident in seen:  # guard duplicate
            failures.append(f"{ident}: listed twice")
        seen.add(ident)
        record = by_name.get(entry.get("record"))
        if record is None:  # guard record
            failures.append(f"{ident}: record {entry.get('record')} is not in evals/results/")
            continue
        ordinal = entry.get("ordinal", 0)
        claim = claims(record).get((entry.get("case"), entry.get("document"), ordinal))
        if claim is None:  # guard claim
            failures.append(f"{ident}: no such claim in the record")
            continue
        if ident != entry_id(record.get("label") or entry["record"], entry["case"], entry["document"], ordinal):  # guard id
            failures.append(f"{ident}: id does not name its case and document")
        label = entry.get("label")
        if label is not None and label not in LABELS:  # guard label
            failures.append(f"{ident}: label {label!r} is not one of {LABELS}")
        absence = entry.get("asserts_absence")
        if absence is not None and not isinstance(absence, bool):  # guard absence
            failures.append(f"{ident}: asserts_absence {absence!r} is not a boolean")
        if label is not None and absence is None:  # guard absence_with_label
            failures.append(f"{ident}: labelled without saying whether it asserts an absence")
    # A key must name only disagreements, or a label on an agreed claim is a
    # verdict about nothing, counted. Both directions: a sheet entry the
    # records no longer dispute, and a dispute the sheet lacks.
    wanted = set()
    for name, record in by_name.items():
        label = record.get("label") or name
        wanted |= {entry_id(label, case, document, ordinal) for case, document, ordinal in disagreements(record)}
    for ident in sorted(seen - wanted):  # guard not_disputed
        failures.append(f"{ident}: the judge families do not disagree on it")
    for ident in sorted(wanted - seen):  # guard missing_dispute
        failures.append(f"{ident}: disputed in its record and not on the sheet; run --extract")
    for failure in failures:
        print(f"  FAIL {failure}")
    labelled = sum(1 for e in entries if e.get("label"))
    if not failures:
        print(f"  ok   {len(entries)} entries match their records, {labelled} labelled")
    return failures


def score(sheet=SHEET, results=RESULTS):
    """The parties to each disagreement, against the labels.

    The published verdicts and the latest other-family round with verdicts,
    the same two sets the sheet was selected from. Earlier rounds that kept
    verdicts are not scored: a label was asked for because these two
    disagreed, and measuring a round the sheet never consulted would be a
    figure over a set it was not drawn for.

    Over-flagged: the judge said unsupported where the label says supported.
    Under-flagged: the reverse. Split by whether the claim asserts an absence,
    because that is the rule the disagreement was measured to turn on.
    """
    entries = [e for e in load_sheet(sheet) if e.get("label")]
    if not entries:
        print("nothing labelled yet; the sheet carries no key to measure against")
        return []
    rows = []
    by_name = dict(records(results))
    for name, record in by_name.items():
        mine = [e for e in entries if e["record"] == name]
        if not mine:
            continue
        for fam, info in sorted(rounds_with_verdicts(record).items()):
            for absence in (True, False):
                subset = [e for e in mine if e["asserts_absence"] is absence]
                judged = [(e, info["verdicts"][(e["case"], e["document"], e.get("ordinal", 0))]) for e in subset
                          if (e["case"], e["document"], e.get("ordinal", 0)) in info["verdicts"]]
                if not judged:
                    continue
                agree = sum(1 for e, v in judged if v == (e["label"] == "supported"))
                over = sum(1 for e, v in judged if not v and e["label"] == "supported")
                under = sum(1 for e, v in judged if v and e["label"] == "unsupported")
                rows.append({"record": record.get("label") or name, "judge": info["model"],
                             "round": info["at"], "asserts_absence": absence,
                             "labelled": len(judged), "agree": agree,
                             "over_flagged": over, "under_flagged": under})
    print("| record | judge | round | absence claims | labelled | agree | over-flagged | under-flagged |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        print(f"| {r['record']} | {r['judge']} | {r['round']} | {'yes' if r['asserts_absence'] else 'no'} "
              f"| {r['labelled']} | {r['agree']} | {r['over_flagged']} | {r['under_flagged']} |")
    print("\nOver-flagged: unsupported from the judge, supported from the key. Labels are a "
          "person's reading of the cited passages and nothing more; the sheet never saw a verdict.")
    return rows


def self_test():
    """Drive every branch on a synthetic record, since the real sheet starts unlabelled.

    Every case runs through `guarded`: a raise, a stop included, is that
    case's failure line and the suite goes on. A guard removed must print a
    FAIL and never a traceback, because a traceback has no line for anything
    reading the output to count.
    """
    def verdict(case, doc, supported):
        return {"case": case, "document": doc, "verdict": {"supported": supported}}

    def record(label, **over):
        # The shape the records actually have: `scorer` is a fingerprint of
        # the scoring code with no model in it, `judged` is the current
        # verdict set and names its model, and the rejudge that produced it
        # is not among the listed rounds.
        base = {
            "label": label, "chunker": "heading",
            "scorer": {"fingerprint": "abc", "path": "evals/judgement.py"},
            "rejudged_at": "2026-08-22T00:30:00Z",
            "per_case": [{"case": "a01", "surface": {"hits": {
                "p-1": "x", "p-2": "x", "p-3": "x", "p-4": "x", "p-5": "x", "p-6": "x", "p-7": "x"}},
              "score": {"claims": [
                # p-8 is in the index and was never returned for this case:
                # the judge was handed p-1 and p-2 only, and so is the reader.
                {"source_uri": "corpus://incidents/INC-1", "offered": "partial",
                 "offered_claim": {"divergence": "the record shows no daemon"},
                 "grounded_in": ["p-1", "p-2", "p-8"]},
                {"source_uri": "corpus://incidents/INC-2", "offered": "applies",
                 "offered_claim": {"divergence": "same host class"},
                 "grounded_in": ["p-3"]},
                {"source_uri": "corpus://incidents/INC-3", "offered": "applies",
                 "offered_claim": {"divergence": "same window"},
                 "grounded_in": ["p-4"]},
                {"source_uri": "corpus://incidents/INC-4", "offered": "applies",
                 "offered_claim": {"divergence": "same tier"},
                 "grounded_in": ["p-5"]},
                # Cited nothing the archive returned, so the judge never saw
                # it and there is no verdict for it: the verdicts on RB-1
                # start at the next claim.
                {"source_uri": "corpus://runbooks/RB-1", "offered": "partial",
                 "offered_claim": {"divergence": "ungrounded heading"},
                 "grounded_in": ["p-nowhere"]},
                {"source_uri": "corpus://runbooks/RB-1", "offered": "partial",
                 "offered_claim": {"divergence": "first heading"},
                 "grounded_in": ["p-6"]},
                {"source_uri": "corpus://runbooks/RB-1", "offered": "partial",
                 "offered_claim": {"divergence": "second heading"},
                 "grounded_in": ["p-7"]}]}},
             # A case the run failed on: the judge builder skips it whole, so
             # its claims take no ordinal and expect no verdict.
             {"case": "a02", "failure": "timed out", "surface": {"hits": {"p-1": "x"}},
              "score": {"claims": [{"source_uri": "corpus://incidents/INC-1", "offered": "applies",
                                    "offered_claim": {"divergence": "never judged"},
                                    "grounded_in": ["p-1"]}]}}],
            # INC-1: the published verdict and the other family disagree.
            # INC-2: they agree. INC-3: only a stale round of the current
            # family disagrees with `judged`, which supersedes it. INC-4: the
            # published verdict disagrees with the other family while an
            # earlier round of its own family agreed with them; what is
            # published is what counts. RB-1 carries two judged claims and
            # the families disagree on the first only. The sheet must carry
            # INC-1, INC-4 and RB-1 at ordinal 0.
            "judged": {"model": "claude-opus-4-6", "groundedness_judge": {"verdicts": [
                verdict("a01", "corpus://incidents/INC-1", True),
                verdict("a01", "corpus://incidents/INC-2", True),
                verdict("a01", "corpus://incidents/INC-3", False),
                verdict("a01", "corpus://incidents/INC-4", True),
                verdict("a01", "corpus://runbooks/RB-1", True),
                verdict("a01", "corpus://runbooks/RB-1", False)]}},
            "judgings": [
                {"at": "2026-08-20T00:00:00Z", "model": "cursor-grok-4.6-high",
                 "groundedness_judge": {"value": 0.5}},
                # An earlier other-family round that agrees with `judged` on
                # INC-1: taking the first round with verdicts instead of the
                # latest would drop INC-1 from the sheet.
                {"at": "2026-08-20T12:00:00Z", "model": "cursor-grok-4.6-high",
                 "groundedness_judge": {"verdicts": [
                     verdict("a01", "corpus://incidents/INC-1", True),
                     verdict("a01", "corpus://incidents/INC-2", True),
                     verdict("a01", "corpus://incidents/INC-3", False),
                     verdict("a01", "corpus://incidents/INC-4", True),
                     verdict("a01", "corpus://runbooks/RB-1", True),
                     verdict("a01", "corpus://runbooks/RB-1", False)]}},
                {"at": "2026-08-21T00:00:00Z", "model": "cursor-grok-4.6-high",
                 "groundedness_judge": {"verdicts": [
                     verdict("a01", "corpus://incidents/INC-1", False),
                     verdict("a01", "corpus://incidents/INC-2", True),
                     verdict("a01", "corpus://incidents/INC-3", False),
                     verdict("a01", "corpus://incidents/INC-4", False),
                     verdict("a01", "corpus://runbooks/RB-1", False),
                     verdict("a01", "corpus://runbooks/RB-1", False)]}},
                {"at": "2026-08-21T12:00:00Z", "model": "claude-opus-4-6",
                 "groundedness_judge": {"verdicts": [
                     verdict("a01", "corpus://incidents/INC-1", True),
                     verdict("a01", "corpus://incidents/INC-2", True),
                     verdict("a01", "corpus://incidents/INC-3", True),
                     verdict("a01", "corpus://incidents/INC-4", False)]}},
                {"at": "2026-08-22T00:00:00Z", "model": "claude-opus-4-6",
                 "groundedness_judge": {"verdicts": [
                     verdict("a01", "corpus://incidents/INC-1", True),
                     verdict("a01", "corpus://incidents/INC-2", True),
                     verdict("a01", "corpus://incidents/INC-3", False),
                     verdict("a01", "corpus://incidents/INC-4", True)]}}]}
        base.update(over)
        return base

    failures = 0
    out = io.StringIO()

    def guarded(name, thunk, reason=None):
        """Run one case. The thunk returns (ok, detail); when `reason` is
        given the case expects a stop carrying that text and anything else,
        a return included, is its failure."""
        nonlocal failures
        try:
            with redirect_stdout(out):
                result = thunk()
        except SystemExit as exc:
            ok, detail = (reason is not None and reason in str(exc)), str(exc)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"raised {exc!r}"
        else:
            if reason is not None:
                ok, detail = False, "returned instead of stopping"
            else:
                ok, detail = result if isinstance(result, tuple) else (bool(result), "")
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f": {detail}" if not ok and detail else ""))

    with tempfile.TemporaryDirectory() as tmp:
        results = Path(tmp) / "results"; results.mkdir()
        sheet = Path(tmp) / "anchor.yaml"
        (results / "judgement-one-20260820T000000Z.json").write_text(json.dumps(record("judgement-one")))
        state = {}

        def first_extract():
            state["entries"] = extract(results, sheet)
            ids = [e["id"] for e in state["entries"]]
            return ids == ["judgement-one/a01/INC-1", "judgement-one/a01/INC-4", "judgement-one/a01/RB-1"], str(ids)
        guarded("extract selects the published verdicts against the other family's latest round, "
                "not a stale round of either family", first_extract)
        # No early return: a case that needs the extraction and did not get it
        # fails on its own line through `guarded`, and every case that does
        # not need it still runs.
        entries = state.get("entries", [])

        guarded("two judged claims on one document are two keys, and the disputed first one is selected alone",
                lambda: ([e.get("ordinal") for e in entries if e["document"].endswith("RB-1")] == [0]
                         and not [e for e in entries if e["id"].endswith("#2")], str(entries)))
        guarded("an unjudged claim takes no ordinal, so ordinal 0 is the first claim the judge saw",
                lambda: (claims(record("judgement-one"))[("a01", "corpus://runbooks/RB-1", 0)]["offered_claim"]["divergence"] == "first heading", ""))
        guarded("a failed case's claims take no ordinal",
                lambda: (("a02", "corpus://incidents/INC-1", 0) not in claims(record("judgement-one")), ""))

        def skewed():
            r = record("judgement-skewed"); r["judged"]["groundedness_judge"]["verdicts"].pop()
            disagreements(r)
        guarded("published verdicts that do not number the judged claims stop the run", skewed, "cannot name a claim")

        def second():
            r = record("judgement-one"); rb = r["judged"]["groundedness_judge"]["verdicts"]
            rb[-2]["verdict"]["supported"], rb[-1]["verdict"]["supported"] = False, True
            found = [c for c in disagreements(r) if c[1].endswith("RB-1")]
            return (found == [("a01", "corpus://runbooks/RB-1", 1)]
                    and entry_id("x", "a01", "corpus://runbooks/RB-1", 1) == "x/a01/RB-1#2", str(found))
        guarded("a disagreement on the second claim alone is selected with its ordinal", second)

        def parties_case():
            parties = rounds_with_verdicts(record("judgement-one"))
            return (set(parties) == {"claude", "cursor"} and parties["claude"]["at"] == "2026-08-22T00:30:00Z"
                    and parties["cursor"]["at"] == "2026-08-21T00:00:00Z"
                    and parties["claude"]["verdicts"][("a01", "corpus://incidents/INC-3", 0)] is False, str(parties))
        guarded("the current family is judged.model with the published verdicts, and the other party "
                "is its latest round with verdicts", parties_case)

        def orphan():
            r = record("judgement-orphan"); del r["judged"]["model"]; disagreements(r)
        guarded("a record whose published verdicts name no model stops the run", orphan, "names no model")

        def stray():
            r = record("judgement-stray")
            r["judgings"][2]["groundedness_judge"]["verdicts"].append(verdict("a01", "corpus://incidents/INC-9", False))
            r["judged"]["groundedness_judge"]["verdicts"].append(verdict("a01", "corpus://incidents/INC-9", True))
            path = results / "judgement-stray-20260820T000001Z.json"
            path.write_text(json.dumps(r))
            try:
                extract(results, sheet)
            finally:
                path.unlink()
        guarded("a verdict with no claim behind it stops extraction", stray,
                "has 0 judged claim(s) and 1 published verdict(s)")

        guarded("extract writes no verdict and no claim text into the sheet",
                lambda: (not {k for e in yaml.safe_load(sheet.read_text()) for k in e}
                         & {"verdict", "verdicts", "judge", "supported", "claim", "cited"}, ""))
        guarded("extract leaves label and absence unset",
                lambda: (entries[0]["label"] is None and entries[0]["asserts_absence"] is None, ""))

        def keeps_label():
            rows = yaml.safe_load(sheet.read_text())
            rows[0]["label"] = "supported"; rows[0]["asserts_absence"] = True; rows[0]["note"] = "mine"
            rows[1]["label"] = "unsupported"; rows[1]["asserts_absence"] = False
            sheet.write_text(yaml.safe_dump(rows, sort_keys=False))
            kept = extract(results, sheet)
            return kept[0]["label"] == "supported" and kept[0]["note"] == "mine" and kept[1]["asserts_absence"] is False, str(kept[:2])
        guarded("extract keeps a label already given", keeps_label)

        guarded("check passes a sheet that matches its record", lambda: (not check(sheet, results), ""))

        # Shared fixtures are prepared through `guarded` too: a read or a
        # write between cases that raises would end the suite with no line
        # for it, which is the one thing this suite promises not to do.
        def read_base():
            state["base_rows"] = load_sheet(sheet)
            return True, ""
        guarded("the sheet the drift cases start from reads cleanly", read_base)
        base_rows = state.get("base_rows", [])
        for name, mutate, reason in [
            ("an id naming another claim", lambda r: r[0].__setitem__("id", "judgement-one/a01/INC-2"), "does not name its case"),
            ("an unknown label", lambda r: r[0].__setitem__("label", "maybe"), "is not one of"),
            ("a non-boolean absence flag", lambda r: r[0].__setitem__("asserts_absence", "yes"), "is not a boolean"),
            ("a label with no absence flag", lambda r: r[0].__setitem__("asserts_absence", None), "without saying whether"),
            ("a vanished claim", lambda r: r[0].__setitem__("document", "corpus://incidents/INC-9"), "no such claim"),
            ("a vanished record", lambda r: r[0].__setitem__("record", "judgement-none.json"), "is not in evals/results/"),
            ("a duplicated entry", lambda r: r.append(copy.deepcopy(r[0])), "listed twice"),
            ("an entry the families agree on",
             lambda r: r.append({**copy.deepcopy(r[0]), "id": "judgement-one/a01/INC-2",
                                 "document": "corpus://incidents/INC-2", "label": None, "asserts_absence": None}),
             "do not disagree on it"),
            ("a dispute missing from the sheet", lambda r: r.clear(), "not on the sheet"),
        ]:
            def drift(mutate=mutate, reason=reason):
                rows = copy.deepcopy(base_rows); mutate(rows)
                sheet.write_text(yaml.safe_dump(rows, sort_keys=False))
                try:
                    found = check(sheet, results)
                finally:
                    sheet.write_text(yaml.safe_dump(base_rows, sort_keys=False))
                return any(reason in f for f in found), str(found)
            guarded(f"check rejects {name}", drift)

        for word in LABELS:
            def accepts(word=word):
                rows = copy.deepcopy(base_rows); rows[0]["label"] = word
                sheet.write_text(yaml.safe_dump(rows, sort_keys=False))
                try:
                    return not check(sheet, results), ""
                finally:
                    sheet.write_text(yaml.safe_dump(base_rows, sort_keys=False))
            guarded(f"check accepts the label {word}", accepts)

        def scored():
            rows = score(sheet, results)
            by = {(r["judge"], r["asserts_absence"]): r for r in rows}
            state["by"] = by
            return set(by) == {("cursor-grok-4.6-high", True), ("claude-opus-4-6", True),
                               ("cursor-grok-4.6-high", False), ("claude-opus-4-6", False)}, str(sorted(by))
        guarded("score reports both parties, split by whether the claim asserts an absence", scored)
        by = state.get("by", {})
        guarded("score counts the over-flag against the key on an absence claim",
                lambda: ((by[("cursor-grok-4.6-high", True)]["over_flagged"], by[("cursor-grok-4.6-high", True)]["agree"]) == (1, 0), str(by)))
        guarded("score counts the agreement on an absence claim",
                lambda: ((by[("claude-opus-4-6", True)]["agree"], by[("claude-opus-4-6", True)]["over_flagged"]) == (1, 0), str(by)))
        guarded("score counts a non-absence claim on its own row: the key says unsupported, the other party agreed",
                lambda: ((by[("cursor-grok-4.6-high", False)]["agree"], by[("claude-opus-4-6", False)]["under_flagged"]) == (1, 1), str(by)))
        guarded("score names the latest round with verdicts, not the rate-only one and not the first",
                lambda: (by[("cursor-grok-4.6-high", True)]["round"] == "2026-08-21T00:00:00Z", str(by)))

        def unlabelled():
            rows = copy.deepcopy(base_rows)
            for r in rows:
                r["label"] = None; r["asserts_absence"] = None
            sheet.write_text(yaml.safe_dump(rows, sort_keys=False))
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    rows_out = score(sheet, results)
            finally:
                sheet.write_text(yaml.safe_dump(base_rows, sort_keys=False))
            return rows_out == [] and "nothing labelled" in buf.getvalue(), buf.getvalue()
        guarded("score with no labels says there is no key and measures nothing", unlabelled)

        def lone():
            r = record("judgement-lone"); r["judgings"] = r["judgings"][3:]  # the publishing family only
            return disagreements(r) == [], str(disagreements(r))
        guarded("one family yields no disagreement", lone)

        def late():
            r = record("judgement-late")
            r["judgings"].append({"at": "2026-08-23T00:00:00Z", "model": "cursor-grok-4.6-high",
                                  "groundedness_judge": {"value": 0.4}})
            parties = rounds_with_verdicts(r)
            return parties["cursor"]["at"] == "2026-08-21T00:00:00Z", str(parties.get("cursor"))
        guarded("a rate-only round after the verdict-bearing one is not the party", late)

        # --show, against a synthetic index, in the adapter's representation.
        index = Path(tmp) / "index.json"
        def write_index():
            index.write_text(json.dumps({"passages": [
            {"passage_id": "p-1", "source_uri": "corpus://incidents/INC-1", "heading_path": "INC-1 > Summary",
             "ordinal": 0, "text": "No daemon was running.", "signature": "host.x", "cause_claimed": "heap",
             "superseded_by": None, "record_status": "filed", "recorded_at": "2025-01-01"},
            {"passage_id": "p-2", "source_uri": "corpus://incidents/INC-1", "heading_path": "INC-1 > Gaps",
             "ordinal": 1, "text": "Attribution was never produced.", "signature": "host.x"},
            {"passage_id": "p-8", "source_uri": "corpus://incidents/INC-1", "heading_path": "INC-1 > Resolution",
             "ordinal": 2, "text": "NEVER RETURNED TO THE JUDGE", "signature": "host.x"}]}))
            return True, ""
        guarded("the synthetic index for show is written", write_index)
        indexes = {"heading": index, "fixed": index}

        def shown():
            buf = io.StringIO()
            with redirect_stdout(buf):
                show(1, sheet, results, indexes)
            text = buf.getvalue()
            wanted = ["the record shows no daemon", "No daemon was running.", "Attribution was never produced.",
                      "document_cause_claimed: heap", "claim_scope: document"]
            return all(w in text for w in wanted) and "signature" not in text, text
        guarded("show prints the claim and its passages as passage_get returns them, signature dropped", shown)

        def only_judged():
            buf = io.StringIO()
            with redirect_stdout(buf):
                show(1, sheet, results, indexes)
            text = buf.getvalue()
            return "NEVER RETURNED TO THE JUDGE" not in text and "also cited p-8" in text, text
        guarded("show omits a cited passage the archive never returned, and says so", only_judged)
        guarded("show refuses a number off the sheet", lambda: show(99, sheet, results, indexes), "the sheet has")

        def show_missing():
            rows = copy.deepcopy(base_rows); rows[0]["document"] = "corpus://incidents/INC-9"
            sheet.write_text(yaml.safe_dump(rows, sort_keys=False))
            try:
                show(1, sheet, results, indexes)
            finally:
                sheet.write_text(yaml.safe_dump(base_rows, sort_keys=False))
        guarded("show stops on an entry whose claim is not in its record", show_missing, "no such claim")

        empty = Path(tmp) / "empty"
        def no_records():
            empty.mkdir(exist_ok=True)
            records(empty)
        guarded("no judgement records is a stop, not an empty sheet", no_records, "no judgement records")
        garbled = Path(tmp) / "garbled.yaml"
        def partial_sheet():
            garbled.write_text("- id: x\n  label: [unterminated\n")
            load_sheet(garbled)
        guarded("a partially written sheet is a named stop for its reader, and nothing else",
                partial_sheet, "not valid YAML")
        guarded("a missing sheet is a stop that says how to make one",
                lambda: load_sheet(Path(tmp) / "nowhere.yaml"), "run --extract first")

    print(f"Anchor self-test: {failures} failure(s).")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--show", type=int, metavar="N")
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        sys.exit(bool(self_test()))
    if args.extract:
        extract()
    elif args.show:
        show(args.show)
    elif args.score:
        score()
    elif args.check:
        sys.exit(bool(check()))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
