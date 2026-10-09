#!/usr/bin/env python3
"""Render agent traces indicators as self-contained pages: one run (sli.json),
or the baseline across runs with its objectives (--baseline on an aggregate).

No scripts, no fonts, no network: the page is a record and opens anywhere.
Every figure on it is formatted from a field in sli.json: this file rounds
cost to cents, converts milliseconds to seconds and ratios to percent, places
bars by start and duration, and counts failed model calls from their recorded
status. It computes no indicator of its own, so what the page can claim is
what checks/agent_traces_sli.py computed, with the source each entry carries.
"""
import argparse
import html
import json
import sys
from pathlib import Path

SCHEMA = "agent-traces-sli/1"
VERDICT_CLASS = {"conformant": "v-ok", "violation_prevented": "v-prevented",
                 "nonconformant": "v-non", "indeterminate": "v-ind"}
CSS = """
:root{color-scheme:light;--bg:#fcfcfb;--panel:#f3f2ee;--line:#d9d8d2;--ink:#0b0b0b;--ink2:#52514e;--ink3:#7a7975;
--ok:#0ca30c;--prevented:#2a78d6;--non:#ec835a;--ind:#d03b3b;--none:#9c9b95}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;--bg:#1a1a19;--panel:#242422;--line:#3a3936;--ink:#fff;--ink2:#c3c2b7;--ink3:#8f8e88;--prevented:#3987e5}}
:root[data-theme=dark]{color-scheme:dark;--bg:#1a1a19;--panel:#242422;--line:#3a3936;--ink:#fff;--ink2:#c3c2b7;--ink3:#8f8e88;--prevented:#3987e5}
*{box-sizing:border-box}body{margin:0;padding:24px 16px;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto}h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 10px}
.sub{color:var(--ink2);margin:0 0 16px}.mono{font-family:ui-monospace,monospace;font-size:13px}
.badges span{display:inline-block;border:1px solid var(--line);border-radius:4px;padding:2px 8px;margin:0 6px 6px 0;font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px}
.tile .k{font-size:12px;color:var(--ink2);text-transform:uppercase;letter-spacing:.03em}
.tile .v{font-size:26px;font-weight:600;margin:2px 0}.tile .t{font-size:12px;color:var(--ink3)}.tile .n{font-size:12px;color:var(--ink2);margin-top:6px}
.src{font-size:11px;border-radius:3px;padding:1px 6px;background:var(--line);color:var(--ink);margin-left:6px;vertical-align:middle}
.gantt{display:grid;grid-template-columns:minmax(180px,auto) 1fr;gap:6px 12px;align-items:center}
.gantt .lane{position:relative;height:22px;background:var(--panel);border-radius:4px}
.gantt .bar{position:absolute;top:3px;height:16px;border-radius:4px;min-width:3px}
.gantt .lab{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.met{color:var(--ok);font-weight:600}.missed{color:var(--ind);font-weight:600}.unm{color:var(--ink3)}
.spark{vertical-align:middle}
.v-ok{background:var(--ok)}.v-prevented{background:var(--prevented)}.v-non{background:var(--non)}.v-ind{background:var(--ind)}
.ended{background:repeating-linear-gradient(135deg,var(--none) 0 4px,transparent 4px 8px)}
.chip{display:inline-block;border-radius:3px;padding:0 6px;font-size:12px;color:#fff}.chip.v-prevented{color:#fff}
.key span{display:inline-block;margin:0 14px 6px 0;font-size:13px}.key i{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:4px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;vertical-align:top;padding:6px 8px;border-bottom:1px solid var(--line)}th{color:var(--ink2);font-weight:600}
pre{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px;overflow-x:auto;font-size:12px}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 12px}dt{font-weight:600}dd{margin:0;color:var(--ink2)}
@media (max-width:600px){.gantt{grid-template-columns:1fr}.gantt .lab{order:-1}dl{grid-template-columns:1fr}}
"""


def esc(value):
    return html.escape(str(value), quote=True)


def seconds(ms):
    return f"{ms / 1000:.1f}s"


def status_badge(label, status):
    if status is None:
        return f"<span>{label}: not recorded</span>"
    return f"<span>{label}: exit {esc(status)} ({'pass' if status == 0 else 'fail'})</span>"


def fmt_value(name, ind):
    if name == "tool_calls":
        return f"{ind['success']} / {ind['error']} / {ind['blocked']}", "success / error / blocked"
    if name == "model_usage":
        return f"${ind['estimated_cost_usd']:.2f}", (f"{ind['model_calls']} calls, {ind['input_tokens']:,} in, "
                                                      f"{ind['output_tokens']:,} out tokens")
    value = ind.get("value")
    if "numerator" in ind:
        shown = "n/a" if value is None else f"{value * 100:.0f}%"
        return shown, f"{ind['numerator']} of {ind['denominator']}"
    if "status" in ind:
        shown = "not recorded" if value is None else ("pass" if value else "fail")
        return shown, "" if ind["status"] is None else f"exit {ind['status']}"
    return str(value), ""


def tiles(indicators):
    out = []
    for name, ind in indicators.items():
        shown, detail = fmt_value(name, ind)
        target = ind.get("target")
        if target is not None:
            detail = (detail + " · " if detail else "") + "target " + (f"{target * 100:.0f}%" if isinstance(target, float) else str(target))
        out.append(f'<div class="tile"><div class="k">{esc(name.replace("_", " "))}'
                   f'<span class="src">{esc(ind["source"])}</span></div><div class="v">{esc(shown)}</div>'
                   f'<div class="t">{esc(detail)}</div><div class="n">{esc(ind["note"])}</div></div>')
    return "\n".join(out)


def gantt(run):
    window = run["window"]
    # Nanoseconds throughout: a bar placed by the truncated millisecond
    # figures can overrun a short window or vanish inside one.
    span = max(window["end_unix_nano"] - window["start_unix_nano"], 1)
    rows = []
    for a in run["attempts"]:
        left = (a["start_unix_nano"] - window["start_unix_nano"]) / span * 100
        width = (a["end_unix_nano"] - a["start_unix_nano"]) / span * 100
        ended = a["attempt"] == "ended_before_verdict"
        cls = "ended" if ended else VERDICT_CLASS[a["verdict"]]
        title = f"{a['stage']}: {a['verdict']}" + (f" ({a['reason']})" if a["reason"] else "") + f", {seconds(a['duration_ms'])}"
        rows.append(f'<div class="lab">{esc(a["stage"])} <span class="chip {cls}">{esc("ended before verdict" if ended else a["verdict"])}</span></div>'
                    f'<div class="lane"><div class="bar {cls}" style="left:{left:.2f}%;width:{width:.2f}%" title="{esc(title)}"></div></div>')
    return "\n".join(rows)


def detail_table(run):
    rows = []
    for a in run["attempts"]:
        tools = ", ".join(f"{t['name']}={t['outcome']}" for t in a["tools"]) or "none"
        calls = a["model_calls"]
        failed = sum(1 for c in calls if c["status"] == "error")
        model = f"{len(calls)}" + (f" ({failed} failed)" if failed else "")
        validation = ", ".join(f"{k}={v}" for k, v in a["validation"].items()) or "none"
        sandbox = f"{a['sandbox_decisions']['allowed']} allowed, {a['sandbox_decisions']['blocked']} blocked"
        rows.append("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in (
            a["stage"], a["verdict"], a["reason"] or "", a["attempt"].replace("_", " "), seconds(a["duration_ms"]),
            model, f"{a['input_tokens']:,} / {a['output_tokens']:,}", f"${a['estimated_cost_usd']:.3f}",
            tools, sandbox, validation, a["contract"] or "none",
            (a["spec_hash"] or "")[:19])) + "</tr>")
    head = "".join(f"<th>{h}</th>" for h in ("stage", "verdict", "reason", "attempt", "duration", "model calls",
                                             "tokens in / out", "est. cost", "tool calls", "sandbox", "validation", "contract", "spec hash"))
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def aggregate_section(agg):
    rows = []
    for key, entry in agg["stages"].items():
        d = entry["duration_ms"]
        verdicts = ", ".join(f"{k} {v}" for k, v in sorted(entry["verdicts"].items()))
        rows.append("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in (
            key, entry["attempts"], entry["completed"], verdicts,
            seconds(d["p50"]) if d else "n/a", seconds(d["p95"]) if d else "n/a", seconds(d["max"]) if d else "n/a")) + "</tr>")
    head = "".join(f"<th>{h}</th>" for h in ("stage", "attempts", "with verdict", "verdicts", "p50", "p95", "max"))
    w = agg["window_ms"]
    return (f"<h2>Baseline across {agg['runs']} runs</h2>"
            f"<p class=\"sub\">End to end p50 {esc(seconds(w['p50']))}, p95 {esc(seconds(w['p95']))}, max {esc(seconds(w['max']))}. "
            f"Stage check passed {agg['stage_check']['numerator']} of {agg['stage_check']['denominator']} recorded; "
            f"driver passed {agg['driver']['numerator']} of {agg['driver']['denominator']} recorded. "
            "Stage percentiles are over completed attempts; the end-to-end figures are over every run. All are nearest rank, so each is a duration that occurred.</p>"
            f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>")


def verdict(met):
    if met is True:
        return '<span class="met">met</span>'
    if met is False:
        return '<span class="missed">missed</span>'
    return '<span class="unm">not measurable</span>'


def sparkline(values, target=None, width=120, height=22):
    """Durations across runs in order, as inline SVG; the target is a dashed line."""
    if not values:
        return ""
    top = max(values + ([target] if target else []))
    top = max(top, 1)
    n = len(values)
    xs = [(i * (width - 4) / max(n - 1, 1)) + 2 for i in range(n)]
    pts = " ".join(f"{x:.1f},{height - 2 - v / top * (height - 4):.1f}" for x, v in zip(xs, values))
    line = ""
    if target:
        y = height - 2 - target / top * (height - 4)
        line = f'<line x1="2" x2="{width - 2}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--ink3)" stroke-dasharray="3 2" stroke-width="1"/>'
    return (f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="durations across {n} runs">'
            f'{line}<polyline fill="none" stroke="var(--prevented)" stroke-width="2" points="{pts}"/></svg>')


def baseline_page(agg):
    slo = agg.get("slo")
    runs = agg["per_run"]
    title = f"Agent traces baseline: {agg['runs']} runs"
    rows = []
    for r in runs:
        rows.append("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in (
            Path(r["spans"]).parent.name, seconds(r["duration_ms"]), r["attempts"],
            "not recorded" if r["driver_status"] is None else ("pass" if r["driver_status"] == 0 else f"fail ({r['driver_status']})"),
            "not recorded" if r["check_status"] is None else ("pass" if r["check_status"] == 0 else f"fail ({r['check_status']})"),
            r["validation_skipped"], r["ended_before_verdict"])) + "</tr>")
    run_table = ("<table><thead><tr>" + "".join(f"<th>{h}</th>" for h in ("run", "end to end", "stages", "driver", "stage check", "validation skipped", "ended before verdict"))
                 + f"</tr></thead><tbody>{''.join(rows)}</tbody></table>")
    slo_html = ""
    if slo:
        items = []
        for name, v in slo["per_run"].items():
            items.append(f"<tr><td>{esc(name.replace('_', ' '))}<span class=\"src\">per run</span></td><td>= {esc(v['target'])}</td>"
                         f"<td>{v['runs_met']} of {v['runs_counted']} runs</td><td>{verdict(v['met'])}</td><td>{esc(v['note'])}</td></tr>")
        for name, v in slo["rolling"].items():
            shown = "n/a" if v["value"] is None else f"{v['value'] * 100:.0f}%"
            items.append(f"<tr><td>{esc(name)}<span class=\"src\">rolling {v['window']}</span></td><td>&ge; {v['target'] * 100:.0f}%</td>"
                         f"<td>{esc(shown)} over {v['runs_in_window']} runs</td><td>{verdict(v['met'])}</td><td>{esc(v['note'])}</td></tr>")
        lat = slo["latency_p95_ms"]
        for key, v in lat["stages"].items():
            series = [r["stages"][key] for r in runs if key in r["stages"]]
            items.append(f"<tr><td>{esc(key)}<span class=\"src\">p95</span></td><td>&le; {esc(seconds(v['target']))}</td>"
                         f"<td>{'n/a' if v['p95'] is None else esc(seconds(v['p95']))} {sparkline(series, v['target'])}</td><td>{verdict(v['met'])}</td><td></td></tr>")
        if "end_to_end" in lat:
            v = lat["end_to_end"]
            items.append(f"<tr><td>end to end<span class=\"src\">p95</span></td><td>&le; {esc(seconds(v['target']))}</td>"
                         f"<td>{esc(seconds(v['p95']))} {sparkline([r['duration_ms'] for r in runs], v['target'])}</td><td>{verdict(v['met'])}</td><td></td></tr>")
        head = "".join(f"<th>{h}</th>" for h in ("objective", "target", "measured", "status", "note"))
        slo_html = (f"<h2>Objectives: {'all met' if slo['met'] else 'not all met'}"
                    f"{', ' + str(slo['unmeasured']) + ' not measurable' if slo['unmeasured'] else ''}</h2>"
                    f"<p class=\"sub\">Targets from <span class=\"mono\">{esc(slo['source'])}</span>, the only place a target lives. "
                    "A per-run objective counts the runs it can be measured on; a rolling one is a rate over the most recent runs in its window; "
                    "latency is a nearest-rank p95 over completed attempts across every run here.</p>"
                    f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(items)}</tbody></table>")
    sources = ("<dl><dt>agent traces</dt><dd>computed from span metadata: that a call was made and how it ended, never what it carried</dd>"
               "<dt>check</dt><dd>what checks/agent_traces.py reported for each run against the expectations its driver mode set</dd>"
               "<dt>driver</dt><dd>the driver's exit status, which folds in every check about content</dd></dl>")
    return f"""<!doctype html>
<html lang="en-AU"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent traces baseline</title><style>{CSS}</style></head>
<body><main>
<h1>{esc(title)}</h1>
<p class="sub">Stage check passed {agg['stage_check']['numerator']} of {agg['stage_check']['denominator']} recorded; driver passed {agg['driver']['numerator']} of {agg['driver']['denominator']} recorded. End to end p50 {esc(seconds(agg['window_ms']['p50']))}, p95 {esc(seconds(agg['window_ms']['p95']))}.</p>
{slo_html}
<h2>Runs, in start order</h2>
{run_table}
{aggregate_section(agg)}
<h2>What each source can say</h2>
{sources}
<p class="sub">A span shows that a tool was called and whether the call raised. It does not show what was filed, which passages were cited, or what the model wrote. The driver holds the outputs against the adapter logs, and only its exit status carries that verdict here.</p>
</main></body></html>
"""


def render(run, aggregate=None):
    title = Path(run["spans"]).parent.name or "agent traces"
    key = "".join(f'<span><i class="{cls}"></i>{esc(v.replace("_", " "))}</span>' for v, cls in VERDICT_CLASS.items())
    key += '<span><i class="ended"></i>ended before verdict</span>'
    sources = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in run["sources"].items())
    check = "\n".join(run["check_output"]) if run.get("check_output") else "not recorded"
    return f"""<!doctype html>
<html lang="en-AU"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent traces report</title><style>{CSS}</style></head>
<body><main>
<h1>Agent traces: {esc(title)}</h1>
<p class="sub">{esc(run['span_count'])} spans, {esc(len(run['attempts']))} stage attempts, {esc(seconds(run['window']['duration_ms']))} first stage start to last stage end<span class="src">{esc(run['window']['source'])}</span>. <span class="mono">{esc(run['spans'])}</span></p>
<div class="badges">{status_badge('driver', run['driver_status'])}{status_badge('stage check', run['check_status'])}</div>
<h2>Indicators</h2>
<div class="tiles">
{tiles(run['indicators'])}
</div>
<h2>Stages</h2>
<div class="key">{key}</div>
<div class="gantt">
{gantt(run)}
</div>
<p class="sub">{esc(run['window']['note'])} One trace per <span class="mono">oa run</span> until OA issue #116 lands, so stages are grouped by this run directory and ordered by start time.</p>
<h2>Stage detail</h2>
{detail_table(run)}
<h2>What the stage check reported</h2>
<pre>{esc(check)}</pre>
{aggregate_section(aggregate) if aggregate else ''}
<h2>What each source can say</h2>
<dl>{sources}</dl>
<p class="sub">A span shows that a tool was called and whether the call raised. It does not show what was filed, which passages were cited, or what the model wrote. What the surface accepted and which passages left it are in the adapter log; what the model wrote, citations included, is its output; the driver holds the one against the other.</p>
</main></body></html>
"""


def load(path, schema):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != schema:
        sys.exit(f"FAIL: {path} is not {schema}")
    return data


def self_test():
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from checks.agent_traces import canned
    from checks.agent_traces_sli import aggregate, compute
    gone = dict(verdict="indeterminate", reason="execution_failed", root_status=2,
                error_type="PROVIDER_ERROR", chat_status=2)
    data = canned(tool="read", status=2, verdict="violation_prevented", blocked=True)
    data[1]["attributes"]["oa.tool.result"] = "blocked"
    data += canned(trace="02", **gone) + canned(trace="03", verdict="nonconformant", override="system")
    data += canned(trace="04", verdict="indeterminate", reason="validation_skipped")
    data[-1]["start_time_unix_nano"], data[-1]["end_time_unix_nano"] = 1_000_000, 3_500_000
    run, errors = compute(data, "x/<spans>.jsonl", 1, 0, ["line <one>"])
    assert not errors, errors
    page = render(run, aggregate([json.loads(json.dumps(run)) for _ in range(2)]))
    for needle in ("driver: exit 1 (fail)", "stage check: exit 0 (pass)", "line &lt;one&gt;", "x/&lt;spans&gt;.jsonl",
                   "ended before verdict", "validation skipped", "Baseline across 2 runs", "read=blocked",
                   'class="bar v-prevented"', 'class="bar ended"', 'class="bar v-non"', 'class="bar v-ind"',
                   "target 100%", "target 0", "success / error / blocked"):
        assert needle in page, needle
    assert all("source" in run["indicators"][k] for k in run["indicators"]) and run["window"]["source"] == "agent traces"
    for forbidden in ("<script", "http", "//", "href=", "src=", "url(", "@import", "@font-face", "<link", "<iframe", "<object", "<embed"):
        assert forbidden not in page, forbidden
    tiny = canned(); tiny[0]["start_time_unix_nano"], tiny[0]["end_time_unix_nano"] = 0, 1_999_000
    late = canned(trace="02"); late[0]["start_time_unix_nano"], late[0]["end_time_unix_nano"] = 1_500_000, 1_999_000
    short, _ = compute(tiny + late, "x", None, None, None)
    bars = gantt(short)
    assert "left:75.04%;width:24.96%" in bars and "left:0.00%;width:100.00%" in bars, bars
    import yaml
    from checks.agent_traces_sli import slo_runs
    targets = yaml.safe_load(Path(__file__).resolve().parent.parent.joinpath("checks", "agent_traces_slo.yaml").read_text(encoding="utf-8"))
    agg = aggregate(slo_runs(), targets, "checks/agent_traces_slo.yaml")
    page_b = baseline_page(agg)
    for needle in ("Agent traces baseline: 3 runs", "not all met", 'class="missed">missed', 'class="met">met', "not measurable",
                   "<svg class=\"spark\"", "stroke-dasharray", "Runs, in start order", "checks/agent_traces_slo.yaml",
                   "fail (1)", "rolling 10", "per run", "p95"):
        assert needle in page_b, needle
    for forbidden in ("<script", "http", "//", "href=", "src=", "url(", "@import", "@font-face", "<link", "<iframe", "<object", "<embed"):
        assert forbidden not in page_b, forbidden
    assert page_b == baseline_page(agg)
    assert "<h2>Objectives" not in baseline_page(aggregate(slo_runs()))
    unknown, _ = compute(canned(), "x", None, None, None)
    page = render(unknown)
    assert "driver: not recorded" in page and "stage check: not recorded" in page and "<pre>not recorded</pre>" in page
    assert page == render(unknown), "render must be deterministic"
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp, "bad.json"); bad.write_text('{"schema": "other"}')
        try:
            load(bad, SCHEMA)
        except SystemExit as exc:
            assert "is not" in str(exc)
        else:
            raise AssertionError("schema mismatch accepted")
    print("Agent traces report self-test passed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sli", nargs="?", help="sli.json from checks/agent_traces_sli.py")
    parser.add_argument("-o", "--output", help="write the page here (default: report.html beside sli.json)")
    parser.add_argument("--aggregate", help="an --aggregate output to append as a baseline section")
    parser.add_argument("--baseline", action="store_true", help="render the aggregate itself as the page (sli is the aggregate file)")
    parser.add_argument("--check", action="store_true", help="non-zero if the page on disk is not what this would render")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.sli:
        parser.error("sli.json is required")
    if args.baseline:
        page = baseline_page(load(args.sli, SCHEMA + "/aggregate"))
        output = Path(args.output) if args.output else Path(args.sli).with_name("baseline.html")
    else:
        run = load(args.sli, SCHEMA)
        agg = load(args.aggregate, SCHEMA + "/aggregate") if args.aggregate else None
        page = render(run, agg)
        output = Path(args.output) if args.output else Path(args.sli).with_name("report.html")
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != page:
            print(f"FAIL: {output} is stale or missing; re-render it", file=sys.stderr)
            return 1
        print(f"{output} is current.")
        return 0
    output.write_text(page, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
