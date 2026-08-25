#!/usr/bin/env python3
"""Render a committed fixture view for the walkthrough, legibly.

    python3 demos/show.py feed      # the problem feed nobody read
    python3 demos/show.py day-one   # what had actually been collected by D+1

Exists so the shots in `docs/walkthrough-script.md` are a short command rather
than a heredoc pasted into a terminal on camera, and so what appears on screen
is reproducible by anyone with the repository.

It reads committed fixtures and formats them. It computes nothing, hides
nothing, and takes no arguments that change what the numbers say: everything
here is Tier 0 in `docs/walkthrough-claims.md`, asserted by
`fixtures/generate.py` or committed to the view it reads.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def view(name):
    return json.loads((ROOT / "fixtures" / name).read_text())


def signal(v, kind):
    for s in v["signals"]:
        if s.get("type") == kind:
            return s
    return None


def table(rows, indent="  "):
    if not rows:
        return
    width = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print(indent + "  ".join(str(c).ljust(width[i]) for i, c in enumerate(r)))


def feed():
    """Thirteen problems, every one auto closed, not one acknowledged."""
    f = signal(view("composite-incident.json"), "problem_feed")
    w = f["window"]
    print(f'{f["total"]} problems   {w["from"][:10]} to {w["to"][:10]}   '
          f'{f["unacknowledged"]} unacknowledged')
    print()
    table([(p["opened_at"][:10], p["severity"],
            "auto-closed" if p["auto_closed"] else "OPEN",
            p["acknowledged_by"] or "unacknowledged")
           for p in f["problems"]])


def day_one():
    """The D+1 view: what had been collected, not what was obtainable."""
    v = view("composite-incident.d1.json")
    print(f'view as of {v["as_of"]}')
    print()
    rows = []
    for s in v["signals"]:
        kind = s.get("type")
        if kind == "problem_feed":
            rows.append(("problem feed", f'{s["total"]} problems, '
                                         f'{s["unacknowledged"]} unacknowledged'))
        elif kind == "metric_series":
            rows.append(("metric series", f'{len(s["series"])} points, {s["metric"]}'))
        else:
            rows.append((kind.replace("_", " "), s.get("source", "")))
    for key in ("evidence", "changes", "missing_evidence", "prior_hypotheses"):
        if key in v:
            rows.append((key.replace("_", " "), f'{len(v[key])} item(s)'))
    rows.append(("incident", v.get("incident_id") or "none"))
    table(rows)
    # The standing condition is the incident and is on nobody's list, so it is
    # printed rather than counted: "1 standing condition" is the wrong shot.
    for c in v["entity"].get("standing_conditions", []):
        print()
        print(f'  standing condition   {c["description"]}')
        print(f'  {"":19}  alerting: {str(c["alerting"]).lower()}   '
              f'owner: {c["owner"] or "none"}')


MODES = {"feed": feed, "day-one": day_one}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in MODES:
        sys.exit(f"usage: demos/show.py [{' | '.join(MODES)}]")
    MODES[mode]()


if __name__ == "__main__":
    main()
