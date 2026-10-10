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


def verdict_map(verdicts):
    return {(v["case"], v["document"]): bool(v["verdict"]["supported"]) for v in verdicts}


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
        fam = family(judging.get("model"))
        if not verdicts or fam == current_family:  # guard other_family
            continue
        parties[fam] = {"at": judging.get("at", ""), "model": judging["model"],
                        "verdicts": verdict_map(verdicts)}
    return parties


def claims(record):
    """Every claim the agent offered in this record, keyed by case and document."""
    out = {}
    for per_case in record.get("per_case", []):
        for claim in (per_case.get("score") or {}).get("claims", []):
            out[(per_case["case"], claim["source_uri"])] = claim
    return out


def disagreements(record):
    """Keys on which two families with verdicts reached different answers."""
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


def entry_id(label, case, document):
    return f"{label}/{case}/{document.rsplit('/', 1)[-1]}"


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
        for case, document in disagreements(record):
            claim = offered.get((case, document))
            if claim is None:  # guard verdict_without_claim
                sys.exit(f"{name}: a verdict on {case} {document} has no claim in per_case")
            ident = entry_id(label, case, document)
            kept = existing.get(ident, {})
            entries.append({
                "id": ident,
                "record": name,
                "case": case,
                "document": document,
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
    return yaml.safe_load(sheet.read_text()) or []


def passages_for(entry, cited, indexes=INDEXES, chunker_of=None):
    """The cited passages, whole, from the index the record was scored on."""
    chunker = chunker_of(entry["record"]) if chunker_of else "heading"
    index = json.loads(indexes[chunker].read_text())
    by_id = {p["passage_id"]: p for p in index.get("passages", [])}
    return [by_id.get(pid, {"passage_id": pid, "error": "not in the current index"})
            for pid in cited]


def show(number, sheet=SHEET, results=RESULTS):
    entries = load_sheet(sheet)
    if not 1 <= number <= len(entries):
        sys.exit(f"the sheet has {len(entries)} entries")
    entry = entries[number - 1]
    by_name = dict(records(results))
    chunkers = {name: record.get("chunker", "heading") for name, record in by_name.items()}
    claim = claims(by_name[entry["record"]]).get((entry["case"], entry["document"]))
    if claim is None:
        sys.exit(f"{entry['id']}: no such claim in {entry['record']}; run --check")
    print(f"[{number}] {entry['id']}   offered: {claim.get('offered')}   label: {entry['label']}")
    print("\nCLAIM (every field is the agent's; the prior-record half is what the passages must support)")
    for key, value in (claim.get("offered_claim") or {}).items():
        print(f"  {key}: {value}")
    print("\nCITED PASSAGES, whole, as the archive holds them")
    for passage in passages_for(entry, claim.get("grounded_in") or [],
                                chunker_of=lambda name: chunkers.get(name, "heading")):
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
        claim = claims(record).get((entry.get("case"), entry.get("document")))
        if claim is None:  # guard claim
            failures.append(f"{ident}: no such claim in the record")
            continue
        if ident != entry_id(record.get("label") or entry["record"], entry["case"], entry["document"]):  # guard id
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
        wanted |= {entry_id(label, case, document) for case, document in disagreements(record)}
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
    """Each judging round with verdicts, against the labels.

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
                judged = [(e, info["verdicts"][(e["case"], e["document"])]) for e in subset
                          if (e["case"], e["document"]) in info["verdicts"]]
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
    """Drive every branch on a synthetic record, since the real sheet starts unlabelled."""
    def verdict(case, doc, supported):
        return {"case": case, "document": doc, "verdict": {"supported": supported}}

    def record(label, **over):
        # The shape the records actually have: `scorer` is a fingerprint of
        # the scoring code with no model in it, `judged` is the current
        # verdict set, and `rejudged_at` names the round that produced it.
        base = {
            "label": label, "chunker": "heading",
            "scorer": {"fingerprint": "abc", "path": "evals/judgement.py"},
            "rejudged_at": "2026-08-22T00:30:00Z",
            "per_case": [{"case": "a01", "score": {"claims": [
                {"source_uri": "corpus://incidents/INC-1", "offered": "partial",
                 "offered_claim": {"divergence": "the record shows no daemon"},
                 "grounded_in": ["p-1", "p-2"]},
                {"source_uri": "corpus://incidents/INC-2", "offered": "applies",
                 "offered_claim": {"divergence": "same host class"},
                 "grounded_in": ["p-3"]},
                {"source_uri": "corpus://incidents/INC-3", "offered": "applies",
                 "offered_claim": {"divergence": "same window"},
                 "grounded_in": ["p-4"]},
                {"source_uri": "corpus://incidents/INC-4", "offered": "applies",
                 "offered_claim": {"divergence": "same tier"},
                 "grounded_in": ["p-5"]}]}}],
            # INC-1: the published verdict and the other family disagree.
            # INC-2: they agree. INC-3: only a stale round of the current
            # family disagrees with `judged`, which supersedes it. INC-4: the
            # published verdict disagrees with the other family while an
            # earlier round of its own family agreed with them; what is
            # published is what counts. The sheet must carry INC-1 and INC-4.
            # The rejudge that produced `judged` is not among the rounds,
            # which is the shape the real records have.
            "judged": {"model": "claude-opus-4-6", "groundedness_judge": {"verdicts": [
                verdict("a01", "corpus://incidents/INC-1", True),
                verdict("a01", "corpus://incidents/INC-2", True),
                verdict("a01", "corpus://incidents/INC-3", False),
                verdict("a01", "corpus://incidents/INC-4", True)]}},
            "judgings": [
                {"at": "2026-08-20T00:00:00Z", "model": "cursor-grok-4.6-high",
                 "groundedness_judge": {"value": 0.5}},
                {"at": "2026-08-21T00:00:00Z", "model": "cursor-grok-4.6-high",
                 "groundedness_judge": {"verdicts": [
                     verdict("a01", "corpus://incidents/INC-1", False),
                     verdict("a01", "corpus://incidents/INC-2", True),
                     verdict("a01", "corpus://incidents/INC-3", False),
                     verdict("a01", "corpus://incidents/INC-4", False)]}},
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
    def case(name, ok, detail=""):
        nonlocal failures
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f": {detail}" if not ok and detail else ""))

    def expect_exit(name, call, reason):
        """A guard that stops the run is a case too, and a crash is a FAIL
        line rather than the end of the suite."""
        try:
            call()
        except SystemExit as exc:
            case(name, reason in str(exc), str(exc))
        except Exception as exc:  # noqa: BLE001
            case(name, False, f"raised {exc!r}")
        else:
            case(name, False, "returned instead of stopping")

    with tempfile.TemporaryDirectory() as tmp:
        results = Path(tmp) / "results"; results.mkdir()
        sheet = Path(tmp) / "anchor.yaml"
        (results / "judgement-one-20260820T000000Z.json").write_text(json.dumps(record("judgement-one")))

        out = io.StringIO()
        with redirect_stdout(out):
            entries = extract(results, sheet)
        case("extract selects the published verdicts against the other family, and not a "
             "stale round of the publishing family",
             [e["id"] for e in entries] == ["judgement-one/a01/INC-1", "judgement-one/a01/INC-4"],
             str([e["id"] for e in entries]))
        parties = rounds_with_verdicts(record("judgement-one"))
        case("the current family is judged.model with the published verdicts and rejudged_at",
             set(parties) == {"claude", "cursor"} and parties["claude"]["at"] == "2026-08-22T00:30:00Z"
             and parties["claude"]["verdicts"][("a01", "corpus://incidents/INC-3")] is False, str(parties))
        orphan = record("judgement-orphan"); del orphan["judged"]["model"]
        expect_exit("a record whose published verdicts name no model stops the run",
                    lambda: disagreements(orphan), "names no model")
        stray = record("judgement-stray")
        stray["judgings"][1]["groundedness_judge"]["verdicts"].append(verdict("a01", "corpus://incidents/INC-9", False))
        stray["judged"]["groundedness_judge"]["verdicts"].append(verdict("a01", "corpus://incidents/INC-9", True))
        (results / "judgement-stray-20260820T000001Z.json").write_text(json.dumps(stray))
        with redirect_stdout(out):
            expect_exit("a verdict with no claim behind it stops extraction",
                        lambda: extract(results, sheet), "has no claim in per_case")
        (results / "judgement-stray-20260820T000001Z.json").unlink()
        keys = {k for e in yaml.safe_load(sheet.read_text()) for k in e}
        case("extract writes no verdict and no claim text into the sheet",
             not keys & {"verdict", "verdicts", "judge", "supported", "claim", "cited"}, str(keys))
        case("extract leaves label and absence unset", entries[0]["label"] is None and entries[0]["asserts_absence"] is None)

        rows = yaml.safe_load(sheet.read_text())
        rows[0]["label"] = "supported"; rows[0]["asserts_absence"] = True; rows[0]["note"] = "mine"
        sheet.write_text(yaml.safe_dump(rows, sort_keys=False))
        with redirect_stdout(out):
            entries = extract(results, sheet)
        case("extract keeps a label already given", entries[0]["label"] == "supported" and entries[0]["note"] == "mine")

        with redirect_stdout(out):
            case("check passes a sheet that matches its record", not check(sheet, results))

        # One drift per guard, each asserting its own reason.
        base_rows = yaml.safe_load(sheet.read_text())
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
            rows = copy.deepcopy(base_rows); mutate(rows)
            sheet.write_text(yaml.safe_dump(rows, sort_keys=False))
            with redirect_stdout(out):
                found = check(sheet, results)
            case(f"check rejects {name}", any(reason in f for f in found), str(found))
        sheet.write_text(yaml.safe_dump(base_rows, sort_keys=False))

        with redirect_stdout(out):
            rows = score(sheet, results)
        by_judge = {(r["judge"], r["asserts_absence"]): r for r in rows}
        grok = by_judge.get(("cursor-grok-4.6-high", True)); opus = by_judge.get(("claude-opus-4-6", True))
        case("score counts the over-flag against the key", grok is not None and grok["over_flagged"] == 1 and grok["agree"] == 0, str(grok))
        case("score counts the agreement", opus is not None and opus["agree"] == 1 and opus["over_flagged"] == 0, str(opus))
        case("score uses the latest round with verdicts, not the rate-only one", grok is not None and grok["round"] == "2026-08-21T00:00:00Z")

        # A record with one family cannot disagree with itself.
        lone = record("judgement-lone"); lone["judgings"] = lone["judgings"][2:]  # the publishing family only
        case("one family yields no disagreement", disagreements(lone) == [])

        # Both words of the vocabulary pass the check, not only the one the
        # scoring cases happen to use.
        for word in LABELS:
            rows = copy.deepcopy(base_rows); rows[0]["label"] = word
            sheet.write_text(yaml.safe_dump(rows, sort_keys=False))
            with redirect_stdout(out):
                case(f"check accepts the label {word}", not check(sheet, results))
        sheet.write_text(yaml.safe_dump(base_rows, sort_keys=False))

        # The label is unsupported and the judge agrees: no flag either way.
        base_rows[0]["label"] = "unsupported"
        sheet.write_text(yaml.safe_dump(base_rows, sort_keys=False))
        with redirect_stdout(out):
            rows = score(sheet, results)
        grok = {(r["judge"], r["asserts_absence"]): r for r in rows}[("cursor-grok-4.6-high", True)]
        case("score counts under-flagging the other way", grok["agree"] == 1 and grok["under_flagged"] == 0)
        opus = {(r["judge"], r["asserts_absence"]): r for r in rows}[("claude-opus-4-6", True)]
        case("score marks a supported verdict on an unsupported label as under-flagged", opus["under_flagged"] == 1)

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
