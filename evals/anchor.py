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
judge families disagreed, because that is where the rubric is ambiguous, and
writes them with `label` and `asserts_absence` unset. It never writes a
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


def rounds_with_verdicts(record):
    """The latest judging round per family that kept its verdicts.

    A round that recorded only a rate is a number with no claims behind it,
    so it cannot be measured against a key and is not a party to any
    disagreement. The record's own `judged` block is the current verdict set
    and is included as the family that produced it.
    """
    latest = {}
    for judging in record.get("judgings", []):
        verdicts = (judging.get("groundedness_judge") or {}).get("verdicts")
        if verdicts:
            latest[family(judging.get("model"))] = (judging.get("at", ""), judging.get("model"), verdicts)
    current = (record.get("judged") or {}).get("groundedness_judge") or {}
    model = ((record.get("scorer") or {}).get("model")) or ""
    if current.get("verdicts") and family(model) not in latest:
        latest[family(model)] = (record.get("rejudged_at", ""), model, current["verdicts"])
    return {fam: {"at": at, "model": model, "verdicts": {
        (v["case"], v["document"]): bool(v["verdict"]["supported"]) for v in verdicts}}
        for fam, (at, model, verdicts) in latest.items()}


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
    if len(families) < 2:  # guard one_family
        return []
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
              "# claims on which the judge families disagreed, which is where the\n"
              "# rubric is ambiguous. Fill `label` (supported | unsupported) and\n"
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
        base = {
            "label": label, "chunker": "heading",
            "scorer": {"model": "claude-opus-4-6"},
            "rejudged_at": "2026-08-22T00:00:00Z",
            "per_case": [{"case": "a01", "score": {"claims": [
                {"source_uri": "corpus://incidents/INC-1", "offered": "partial",
                 "offered_claim": {"divergence": "the record shows no daemon"},
                 "grounded_in": ["p-1", "p-2"]},
                {"source_uri": "corpus://incidents/INC-2", "offered": "applies",
                 "offered_claim": {"divergence": "same host class"},
                 "grounded_in": ["p-3"]}]}}],
            "judged": {"groundedness_judge": {"verdicts": [
                verdict("a01", "corpus://incidents/INC-1", True),
                verdict("a01", "corpus://incidents/INC-2", True)]}},
            "judgings": [
                {"at": "2026-08-20T00:00:00Z", "model": "cursor-grok-4.6-high",
                 "groundedness_judge": {"value": 0.5}},
                {"at": "2026-08-21T00:00:00Z", "model": "cursor-grok-4.6-high",
                 "groundedness_judge": {"verdicts": [
                     verdict("a01", "corpus://incidents/INC-1", False),
                     verdict("a01", "corpus://incidents/INC-2", True)]}},
                {"at": "2026-08-22T00:00:00Z", "model": "claude-opus-4-6",
                 "groundedness_judge": {"verdicts": [
                     verdict("a01", "corpus://incidents/INC-1", True),
                     verdict("a01", "corpus://incidents/INC-2", True)]}}]}
        base.update(over)
        return base

    failures = 0
    def case(name, ok, detail=""):
        nonlocal failures
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f": {detail}" if not ok and detail else ""))

    with tempfile.TemporaryDirectory() as tmp:
        results = Path(tmp) / "results"; results.mkdir()
        sheet = Path(tmp) / "anchor.yaml"
        (results / "judgement-one-20260820T000000Z.json").write_text(json.dumps(record("judgement-one")))

        out = io.StringIO()
        with redirect_stdout(out):
            entries = extract(results, sheet)
        case("extract selects exactly the disagreed claim", [e["id"] for e in entries] == ["judgement-one/a01/INC-1"], str([e["id"] for e in entries]))
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
        lone = record("judgement-lone"); lone["judgings"] = lone["judgings"][2:]
        case("one family yields no disagreement", disagreements(lone) == [])

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
