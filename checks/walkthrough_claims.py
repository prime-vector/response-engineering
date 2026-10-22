#!/usr/bin/env python3
"""Hold the walkthrough's claim list to the checks it cites.

`docs/walkthrough-claims.md` sorts every claim a voiceover may make by what
guarantees it, and each Tier 1 row names the committed case that proves the
guarantee can fail. Those names are typed by hand into a document that nothing
executes, so they rot: a case renamed in the suite leaves a row citing evidence
that no longer exists, and the row still reads as though it were checked.

    python3 checks/walkthrough_claims.py
    python3 checks/walkthrough_claims.py --self-test

**What this does not check**, said here rather than left for a reader to
assume: whether a cited case actually proves the sentence in the row it sits
beside. That is a judgement about meaning and this is a check about names. Six
mis-sortings were found in review on 25 Aug 2026 and this would have caught
two of them; the other four were sentences that had drifted away from cases
that do exist. A row can cite a real case and still claim more than the case
proves, and nothing here notices.

No model, no network, no key.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "walkthrough-claims.md"
GOVERNANCE = ROOT / "demos" / "governance.sh"
GENERATOR = ROOT / "fixtures" / "generate.py"

sys.path.insert(0, str(ROOT / "checks"))
from contract_invariants import CASES  # noqa: E402


def section(text, heading):
    """The body under one `##` heading, up to the next one."""
    start = text.index(heading) + len(heading)
    rest = text[start:]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def rows(body):
    """Table rows as lists of cells, header and separator dropped."""
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|- "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        out.append(cells)
    return out[1:] if out else out


def governance_modes(text):
    m = re.search(r'case "\$MODE" in ([a-z|]+)\)', text)
    return set(m.group(1).split("|")) if m else set()


def feed_assertions(text):
    body = text[text.index("def assert_feed_shape"):]
    body = body[:body.index("\ndef ")]
    return re.findall(r"^\s+assert ", body, re.M)


def check(doc, case_names, modes, assertion_count, self_test_count):
    """Returns (failures, checks made). Each failure names its own reason."""
    failures = 0
    made = 0

    # Tier 1 cites cases that exist.
    for row in rows(section(doc, "## Tier 1")):
        if len(row) < 3:
            continue
        for cited in re.findall(r"`([^`]+)`", row[2]):
            made += 1
            if cited.startswith("demos/"):
                mode = cited.split()[-1]
                if mode not in modes:
                    print(f"  FAIL Tier 1 cites `{cited}`, and `{mode}` is not a "
                          f"mode {GOVERNANCE.name} accepts: {sorted(modes)}")
                    failures += 1
            elif cited not in case_names:
                print(f"  FAIL Tier 1 row \"{row[0][:44]}\" cites the case "
                      f"`{cited}`, which is not in the suite: a row whose "
                      f"evidence has been renamed still reads as checked")
                failures += 1

    # Every demo referenced anywhere in the document is runnable.
    for cited in re.findall(r"`(demos/governance\.sh [a-z]+)`", doc):
        made += 1
        mode = cited.split()[-1]
        if mode not in modes:
            print(f"  FAIL the document cites `{cited}`, which is not a mode "
                  f"{GOVERNANCE.name} accepts")
            failures += 1

    # Tier 0a has one row per assertion, so a row cannot be added without one.
    made += 1
    tier0a = len(rows(section(doc, "## Tier 0a")))
    if tier0a != assertion_count:
        print(f"  FAIL Tier 0a lists {tier0a} speakable properties against "
              f"{assertion_count} assertions in assert_feed_shape: a row with "
              f"no assertion behind it is the whole reason this tier is split")
        failures += 1

    # A count stated about a check matches the check.
    for stated in re.findall(r"(\d+) self-tests", doc):
        made += 1
        if int(stated) != self_test_count:
            print(f"  FAIL the document says {stated} self-tests against "
                  f"{self_test_count} in the suite: a number written for a "
                  f"smaller set reads as current")
            failures += 1
    return failures, made


def self_test():
    """Drive the branches, which a correct document does not reach."""
    good = """## Tier 0a: asserted
| May be spoken | The assertion |
| --- | --- |
| One | `a` |
| Two | `b` |

## Tier 1: contract
| May be spoken | Enforced by | Proven by |
| --- | --- | --- |
| A rule | a schema | `a real case` |
| Another | a sandbox | `demos/governance.sh sandbox` |

Also 9 self-tests.
"""
    names = {"a real case"}
    modes = {"sandbox", "refusal"}
    cases = [
        ("a correct document", good, 0, None),
        ("a Tier 1 row citing a case that does not exist",
         good.replace("`a real case`", "`a renamed case`"), 1,
         "is not in the suite"),
        ("a Tier 1 row citing a demo mode that does not exist",
         good.replace("governance.sh sandbox", "governance.sh teapot"), 2,
         "is not a mode"),
        ("a Tier 0a row with no assertion behind it",
         good.replace("| Two | `b` |", "| Two | `b` |\n| Three | `c` |"), 1,
         "with no assertion behind it"),
        ("a self-test count written for a smaller set",
         good.replace("9 self-tests", "4 self-tests"), 1,
         "reads as current"),
    ]
    failures = 0
    for name, doc, want, reason in cases:
        import contextlib, io
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                got, _ = check(doc, names, modes, 2, 9)
            out = buf.getvalue()
        except Exception as exc:               # a crash prints no verdicts
            got, out = None, buf.getvalue() + f"  FAIL raised {exc!r}\n"
        ok = got == want and (reason is None or reason in out)
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            print(f"       wanted {want} failure(s) saying {reason!r}, got "
                  f"{got} from:\n{out.rstrip()}")
    if failures:
        sys.exit(f"\n{failures} of {len(cases)} self-tests failed.")
    print(f"\n{len(cases)} self-tests pass: a renamed case, an unrunnable demo, "
          f"an unasserted row and a stale count each fail for their own reason.")
    return 0


def main():
    doc = DOC.read_text()
    names = {case[0] for case in CASES}
    # `all` included: the document cites it in the pre-take checklist, and
    # excluding it was a false positive this check found on its first run.
    modes = governance_modes(GOVERNANCE.read_text())
    assertions = len(feed_assertions(GENERATOR.read_text()))
    # Read out of the suite rather than typed here, so the two cannot disagree.
    import contract_invariants as ci
    self_tests = len(re.findall(r"^\s+\(\"", ci.scale_self_test.__doc__ or "")) or None
    if self_tests is None:
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ci.scale_self_test()
        self_tests = int(re.search(r"(\d+) scale self-tests pass",
                                   buf.getvalue()).group(1))
    if "--self-test" in sys.argv:
        return self_test()
    failures, made = check(doc, names, modes, assertions, self_tests)
    if failures:
        sys.exit(f"\n{failures} of {made} citations in {DOC.name} do not hold.")
    print(f"{made} citations in {DOC.name} hold: every case named is in the "
          f"suite, every demo named is runnable, Tier 0a has one row per "
          f"assertion, and the counts match. Whether a case proves the "
          f"sentence beside it is not checked.")


if __name__ == "__main__":
    main()
