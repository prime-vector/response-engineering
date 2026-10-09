#!/usr/bin/env python3
"""Compute per-run service level indicators from agent traces, as JSON.

Reads the sink's spans.jsonl through checks/agent_traces.py, so one parser and
one abandoned-attempt rule serve both, and writes one record per stage attempt
plus named indicators. Every indicator carries its source: `agent traces` for
what a span can prove (that a tool was called, what verdict a stage ended with,
how long it took), `check` for what checks/agent_traces.py reported against the
driver's expectations, and `driver` for the driver's own exit status, which is
where every check about content lives, the filing digest included. Spans prove
that, never what.
"""
import argparse
import io
import json
import math
import re
import sys
import tempfile

import yaml
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from checks.agent_traces import VERDICTS, canned, provider_failure, read_spans  # noqa: E402

SCHEMA = "agent-traces-sli/1"
OVERRIDES = ("none", "system", "user", "both")
# Only these two are a claim about a spec rather than about the runner: the
# Precedent Analyst's prompt requires coverage_describe before any search, and
# the tool names are the precedent_archive surface's (interfaces/PRECEDENT.md).
RECALL_STAGE = ("precedent-analyst", "recall")
COVERAGE_TOOL, SEARCH_TOOL = "coverage_describe", "precedent_search"
USAGE_KEYS = ("gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens")
# Which source each indicator carries. A test holds indicators() to this, so
# moving one is a deliberate edit here and not a drift there.
INDICATOR_SOURCES = {
    "stage_check": "check", "driver": "driver", "attempts_with_verdict": "agent traces",
    "validation_skipped": "agent traces", "sandbox_not_declared": "agent traces",
    "nonconformant_without_override": "agent traces", "blocked_recorded_as_prevented": "agent traces",
    "tool_calls": "agent traces", "recall_coverage_first": "agent traces", "model_usage": "agent traces",
}
SOURCES = {
    "agent traces": "computed from span metadata: that a call was made and how it ended, never what it carried",
    "check": "what checks/agent_traces.py reported for this run against the expectations the driver mode set",
    "driver": "the driver's own exit status, which folds in every check about content: outputs parsed, citations verified against the adapter log, and the filed timeline matching its receipt",
}


def ms(nanos):
    return nanos // 1_000_000


def attempt(trace, members):
    roots = [s for s in members if s["parent_span_id"] == ""]
    if len(roots) != 1:  # guard root
        return None, f"trace {trace}: expected one root span, found {len(roots)}"
    root = roots[0]
    a = root["attributes"]
    spec, task, override, verdict = (a.get(k) for k in (
        "oa.spec.name", "oa.task.name", "oa.prompt.override", "oa.conformance.status"))
    if not isinstance(spec, str) or not spec or not isinstance(task, str) or not task or override not in OVERRIDES or verdict not in VERDICTS:  # guard stage_metadata
        return None, f"trace {trace}: missing or invalid stage metadata"
    for span in members:
        start, end = span.get("start_time_unix_nano"), span.get("end_time_unix_nano")
        if type(start) is not int or type(end) is not int:  # guard times_type
            return None, f"trace {trace}: span {span['name']!r} has non-integer timestamps"
        if start < 0 or end < start:  # guard times
            return None, f"trace {trace}: span {span['name']!r} has invalid timestamps"
    reason = a.get("oa.conformance.reason", "")
    if not isinstance(reason, str):  # guard reason
        return None, f"trace {trace}: conformance reason must be a string"
    ordered = sorted(members, key=lambda s: (s["start_time_unix_nano"], s["span_id"]))
    model_calls, tools, validation, contract = [], [], {}, None
    sandbox = {"allowed": 0, "blocked": 0}
    for span in ordered:
        name, attrs = span["name"], span["attributes"]
        duration = ms(span["end_time_unix_nano"] - span["start_time_unix_nano"])
        if name.startswith("chat "):
            usage = {}
            for key in USAGE_KEYS:
                value = attrs.get(key)
                if value is not None and type(value) is not int:  # guard usage_bool
                    return None, f"trace {trace}: {key} must be an integer"
                if value is not None and value < 0:  # guard usage
                    return None, f"trace {trace}: {key} must be a non-negative integer"
                usage[key.rsplit(".", 1)[1]] = value
            cost = attrs.get("oa.usage.estimated_cost_usd")
            if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int, float))):  # guard cost_bool
                return None, f"trace {trace}: oa.usage.estimated_cost_usd must be a number"
            if cost is not None and (cost < 0 or not math.isfinite(cost)):  # guard cost+cost_infinite
                return None, f"trace {trace}: oa.usage.estimated_cost_usd must be a non-negative number"
            model_calls.append({"model": attrs.get("gen_ai.request.model"),
                                "status": "error" if span["status_code"] == 2 else "ok",
                                "duration_ms": duration, "estimated_cost_usd": cost, **usage})
        elif name.startswith("execute_tool "):
            tool = attrs.get("gen_ai.tool.name", name.removeprefix("execute_tool "))
            if not isinstance(tool, str) or not tool:  # guard tool_metadata
                return None, f"trace {trace}: missing or invalid tool name"
            # The same three outcomes checks/agent_traces.py reports.
            outcome = "blocked" if attrs.get("oa.tool.result") == "blocked" else (
                "error" if span["status_code"] == 2 else "success")
            tools.append({"name": tool, "outcome": outcome, "duration_ms": duration})
        elif name == "oa.sandbox.decision":
            result = attrs.get("oa.sandbox.result")
            if result not in sandbox:  # guard sandbox_result
                return None, f"trace {trace}: sandbox decision must be allowed or blocked"
            sandbox[result] = sandbox.get(result, 0) + 1
        elif name == "oa.validation":
            kind, result = attrs.get("oa.validation.kind"), attrs.get("oa.validation.result")
            if not isinstance(kind, str) or not kind or not isinstance(result, str) or not result:  # guard validation
                return None, f"trace {trace}: validation span without kind and result"
            validation[kind] = result
        elif name == "oa.contract.evaluate":
            result = attrs.get("oa.contract.result")
            if not isinstance(result, str) or not result:  # guard contract
                return None, f"trace {trace}: contract span without a result"
            contract = result
    return {
        "trace_id": trace, "spec": spec, "task": task, "prompt_override": override,
        "stage": f"{spec}:{task}:{override}", "verdict": verdict, "reason": reason,
        "attempt": "ended_before_verdict" if provider_failure(root, verdict, reason, members) else "completed",
        "spec_hash": a.get("oa.spec.hash"),
        "start_unix_nano": root["start_time_unix_nano"], "end_unix_nano": root["end_time_unix_nano"],
        "duration_ms": ms(root["end_time_unix_nano"] - root["start_time_unix_nano"]),
        "model_calls": model_calls, "tools": tools, "sandbox_decisions": sandbox,
        "validation": validation, "contract": contract,
        "input_tokens": sum(c["input_tokens"] or 0 for c in model_calls),
        "output_tokens": sum(c["output_tokens"] or 0 for c in model_calls),
        "estimated_cost_usd": round(sum(c["estimated_cost_usd"] or 0 for c in model_calls), 6),
    }, None


def ratio(numerator, denominator):
    return {"value": (numerator / denominator) if denominator else None,
            "numerator": numerator, "denominator": denominator}


def coverage_first(record):
    """Coverage described before the first search, or described and never searched."""
    names = [t["name"] for t in record["tools"]]
    if COVERAGE_TOOL not in names:
        return False
    if SEARCH_TOOL not in names:
        return True
    return names.index(COVERAGE_TOOL) < names.index(SEARCH_TOOL)


def indicators(attempts, driver_status, check_status):
    completed = [r for r in attempts if r["attempt"] == "completed"]
    blocked = [r for r in attempts if r["sandbox_decisions"]["blocked"]]
    recalls = [r for r in completed if (r["spec"], r["task"]) == RECALL_STAGE]
    outcomes = {"success": 0, "error": 0, "blocked": 0}
    for r in attempts:
        for t in r["tools"]:
            outcomes[t["outcome"]] += 1
    result = {
        "stage_check": {
            "source": "check", "status": check_status,
            "value": None if check_status is None else check_status == 0,
            "note": "Handoff integrity: every stage the mode expects present, with its expected verdict, each listing matched once. Not computed here; reported by the check."},
        "driver": {
            "source": "driver", "status": driver_status,
            "value": None if driver_status is None else driver_status == 0,
            "note": "The driver's verdict on content. Filing integrity, grounding and output parsing are in here and are not separable from this file."},
        "attempts_with_verdict": {
            "source": "agent traces", **ratio(len(completed), len(attempts)),
            "note": "Attempts that reached a verdict. The remainder ended on a failed model call, which is how OA 1.6.2 records a transport failure and equally a rejected key; the drivers retry a transport failure once, and only on a stage that does not write."},
        "validation_skipped": {
            "source": "agent traces", "value": sum(1 for r in attempts if r["verdict"] == "indeterminate" and r["reason"] == "validation_skipped"),
            "note": "Stages whose output never reached schema or contract validation: the truncated-JSON fail-open."},
        "sandbox_not_declared": {
            "source": "agent traces", "value": sum(1 for r in attempts if r["verdict"] == "indeterminate" and r["reason"] == "sandbox_not_declared"),
            "note": "Stages that ran a task with no sandbox, which is allow-all."},
        "nonconformant_without_override": {
            "source": "agent traces", "value": sum(1 for r in completed if r["verdict"] == "nonconformant" and r["prompt_override"] == "none"),
            "note": "Nonconformant stages that ran the spec's own prompt. The governance reject paths run under a system override, so these are outside them. Whether one was expected is the check's call."},
        "blocked_recorded_as_prevented": {
            "source": "agent traces", **ratio(sum(1 for r in blocked if r["verdict"] == "violation_prevented"), len(blocked)),
            "note": "Stages with a blocked sandbox decision that ended violation_prevented."},
        "tool_calls": {
            "source": "agent traces", **outcomes,
            "note": "Tool spans by outcome. Success means the call did not raise; what it returned is in the adapter log."},
        "recall_coverage_first": {
            "source": "agent traces", **ratio(sum(1 for r in recalls if coverage_first(r)), len(recalls)),
            "note": "Completed recall stages that called coverage_describe before any precedent_search, by span start order. Whether the search was bounded is an argument, and arguments are not in spans."},
        "model_usage": {
            "source": "agent traces",
            "model_calls": sum(len(r["model_calls"]) for r in attempts),
            "input_tokens": sum(r["input_tokens"] for r in attempts),
            "output_tokens": sum(r["output_tokens"] for r in attempts),
            "estimated_cost_usd": round(sum(r["estimated_cost_usd"] for r in attempts), 6),
            "note": "As the runner recorded them. The CLI's usage mapper keeps input and output tokens and drops the cache fields, so cached input is absent from the count and from the runner's estimate."},
    }
    return result


def compute(spans, path, driver_status=None, check_status=None, check_output=None):
    traces = {}
    for span in spans:
        traces.setdefault(span["trace_id"], []).append(span)
    attempts, errors = [], []
    for trace, members in traces.items():
        record, error = attempt(trace, members)
        if error:
            errors.append(error)
        else:
            attempts.append(record)
    if errors:
        return None, errors
    attempts.sort(key=lambda r: (r["start_unix_nano"], r["trace_id"]))
    # From the recorded nanoseconds, not from the truncated duration: a
    # window rebuilt from milliseconds is short by the part each one dropped.
    starts = [r["start_unix_nano"] for r in attempts]
    ends = [r["end_unix_nano"] for r in attempts]
    window = {"source": "agent traces", "start_unix_nano": min(starts), "end_unix_nano": max(ends),
              "duration_ms": ms(max(ends) - min(starts)),
              "note": "First root span start to last root span end, so it includes the driver's own work between stages and nothing before the first stage or after the last."}
    return {
        "schema": SCHEMA, "spans": str(Path(path)), "span_count": len(spans),
        "window": window, "driver_status": driver_status, "check_status": check_status,
        "check_output": check_output, "attempts": attempts,
        "indicators": indicators(attempts, driver_status, check_status),
        "sources": SOURCES,
    }, []


def percentile(values, p):
    """Nearest rank, so a reported value is one that occurred."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def aggregate(runs, slo=None, slo_path=None):
    """A baseline across runs: latency and verdicts per stage, pass rates per run."""
    stages, windows = {}, []
    for run in runs:
        windows.append(run["window"]["duration_ms"])
        for r in run["attempts"]:
            entry = stages.setdefault(r["stage"], {"attempts": 0, "verdicts": {}, "durations_ms": []})
            entry["attempts"] += 1
            entry["verdicts"][r["verdict"]] = entry["verdicts"].get(r["verdict"], 0) + 1
            if r["attempt"] == "completed":
                entry["durations_ms"].append(r["duration_ms"])
    out = {"schema": SCHEMA + "/aggregate", "runs": len(runs), "stages": {}}
    for key, entry in sorted(stages.items()):
        d = entry.pop("durations_ms")
        entry["completed"] = len(d)
        entry["duration_ms"] = {"p50": percentile(d, 50), "p95": percentile(d, 95), "max": max(d)} if d else None
        out["stages"][key] = entry
    out["window_ms"] = {"p50": percentile(windows, 50), "p95": percentile(windows, 95), "max": max(windows),
                        "note": "Over every run, abandoned attempts included: a run's window is its first start to its last end whatever happened between."}
    for name in ("stage_check", "driver"):
        known = [run["indicators"][name]["value"] for run in runs if run["indicators"][name]["value"] is not None]
        out[name] = {"source": name if name == "driver" else "check", **ratio(sum(known), len(known)),
                     "note": "Runs that passed, over runs whose status was recorded."}
    # One row per run, in start order, so a page can show the sequence
    # without re-reading every sli.json.
    out["per_run"] = [{
        "spans": r["spans"], "start_unix_nano": r["window"]["start_unix_nano"],
        "duration_ms": r["window"]["duration_ms"], "driver_status": r["driver_status"],
        "check_status": r["check_status"], "attempts": len(r["attempts"]),
        "validation_skipped": r["indicators"]["validation_skipped"]["value"],
        "ended_before_verdict": PER_RUN_DERIVED["attempts_ended_before_verdict"](r["indicators"]),
        # Every completed attempt, in start order: a run may hold a stage
        # twice (governance all runs assess:system in two modes), and the p95
        # walked all of them, so the series drawn against it must too.
        "stages": stage_series(r),
    } for r in sorted(runs, key=lambda r: (r["window"]["start_unix_nano"], r["spans"]))]
    if slo is not None:
        out["slo"] = {"source": str(slo_path), **evaluate_slo(runs, slo, out)}
    return out


PER_RUN_DERIVED = {
    # Targets name indicators; this one is a difference of two counts on one.
    "attempts_ended_before_verdict": lambda i: i["attempts_with_verdict"]["denominator"] - i["attempts_with_verdict"]["numerator"],
}


def per_run_value(indicators, name):
    """What a per-run target is held to. None means the run is not counted."""
    if name in PER_RUN_DERIVED:
        return PER_RUN_DERIVED[name](indicators)
    if name not in indicators:  # guard slo_unknown_indicator
        raise ValueError(f"target names an indicator no run carries: {name}")
    return indicators.get(name, {"value": None})["value"]


def stage_series(run):
    series = {}
    for a in run["attempts"]:
        if a["attempt"] == "completed":
            series.setdefault(a["stage"], []).append(a["duration_ms"])
    return series


def evaluate_slo(runs, targets, agg):
    """Hold the runs to the targets file. Unmeasurable is never met."""
    ordered = sorted(runs, key=lambda r: (r["window"]["start_unix_nano"], r["spans"]))
    out = {"runs": len(ordered), "per_run": {}, "rolling": {}, "latency_p95_ms": {"stages": {}}}
    for name, target in (targets.get("per_run") or {}).items():
        wanted = target["equals"]
        counted, met, missed = 0, 0, []
        for r in ordered:
            value = per_run_value(r["indicators"], name)
            if value is None:
                continue
            counted += 1
            if value == wanted:
                met += 1
            else:
                missed.append(r["spans"])
        out["per_run"][name] = {"target": wanted, "runs_counted": counted, "runs_met": met,
                                "met": (met == counted) if counted else None, "missed": missed,
                                "note": target.get("note", "")}
    for name, target in (targets.get("rolling") or {}).items():
        window = ordered[-target["window"]:]
        known = [per_run_value(r["indicators"], name) for r in window]
        known = [v for v in known if v is not None]
        value = (sum(1 for v in known if v) / len(known)) if known else None
        out["rolling"][name] = {"target": target["at_least"], "window": target["window"],
                                "runs_in_window": len(known), "value": value,
                                "met": (value >= target["at_least"]) if value is not None else None,
                                "note": target.get("note", "")}
    latency = targets.get("latency_p95_ms") or {}
    for key, target in (latency.get("stages") or {}).items():
        stage = agg["stages"].get(key)
        p95 = stage["duration_ms"]["p95"] if stage and stage["duration_ms"] else None
        out["latency_p95_ms"]["stages"][key] = {"target": target, "p95": p95,
                                                "met": (p95 <= target) if p95 is not None else None}
    if "end_to_end" in latency:
        p95 = agg["window_ms"]["p95"]
        out["latency_p95_ms"]["end_to_end"] = {"target": latency["end_to_end"], "p95": p95,
                                               "met": p95 <= latency["end_to_end"]}
    verdicts = ([v["met"] for v in out["per_run"].values()] + [v["met"] for v in out["rolling"].values()]
                + [v["met"] for v in out["latency_p95_ms"]["stages"].values()]
                + ([out["latency_p95_ms"]["end_to_end"]["met"]] if "end_to_end" in out["latency_p95_ms"] else []))
    out["unmeasured"] = sum(1 for v in verdicts if v is None)
    out["met"] = all(v is True for v in verdicts)
    return out


def load_status(path):
    """driver=N and check=N lines, as demos/traced.sh writes them."""
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if not sep or key not in ("driver", "check"):  # guard status_key+status_nosep
            raise ValueError(f"status file {path}: expected a driver= or check= line, got {line!r}")
        if not re.fullmatch(r"[0-9]+", value):  # guard status_line
            raise ValueError(f"status file {path}: expected an exit status, got {line!r}")
        values[key] = int(value, 10)
    return values.get("driver"), values.get("check")


def self_test():
    cases = []

    def case(name, data, error=None, check=None, status=(None, None), output=None):
        cases.append((name, data, error, check, status, output))

    def rec(result, trace="01"):
        return next(r for r in result["attempts"] if r["trace_id"] == trace)

    ok = canned(tool="record_update")
    case("normal", ok, check=lambda r: rec(r)["stage"] == "scribe:timeline:none" and rec(r)["attempt"] == "completed"
         and rec(r)["tools"] == [{"name": "record_update", "outcome": "success", "duration_ms": 0}]
         and r["indicators"]["tool_calls"]["success"] == 1 and r["window"]["duration_ms"] == 0)
    data = canned(); data.append(dict(data[0], span_id="9"))
    case("root", data, "expected one root span, found 2")
    data = canned(); data[0]["attributes"]["oa.prompt.override"] = "all"
    case("stage_metadata", data, "missing or invalid stage metadata")
    data = canned(); data[0]["end_time_unix_nano"] = 5
    case("times", data, "invalid timestamps")
    data = canned(); data[0]["start_time_unix_nano"] = 10.5
    case("times_type", data, "non-integer timestamps")
    data = canned(reason=None); data[0]["attributes"]["oa.conformance.reason"] = 3
    case("reason", data, "conformance reason must be a string")
    data = canned(chat_status=1); data[1]["attributes"]["gen_ai.usage.input_tokens"] = -1
    case("usage", data, "must be a non-negative integer")
    data = canned(chat_status=1); data[1]["attributes"]["gen_ai.usage.output_tokens"] = True
    case("usage_bool", data, "must be an integer")
    data = canned(chat_status=1); data[1]["attributes"]["oa.usage.estimated_cost_usd"] = -0.5
    case("cost", data, "must be a non-negative number")
    data = canned(chat_status=1); data[1]["attributes"]["oa.usage.estimated_cost_usd"] = 1e309
    case("cost_infinite", data, "must be a non-negative number")
    data = canned(chat_status=1); data[1]["attributes"]["oa.usage.estimated_cost_usd"] = True
    case("cost_bool", data, "must be a number")
    data = canned(tool="read"); data[1]["attributes"]["gen_ai.tool.name"] = ""
    case("tool_metadata", data, "missing or invalid tool name")
    data = canned(blocked=True); data[1]["attributes"]["oa.sandbox.result"] = "denied"
    case("sandbox_result", data, "must be allowed or blocked")
    data = canned(); data.append({**data[0], "span_id": "2", "parent_span_id": "1", "name": "oa.validation",
                                  "attributes": {"oa.validation.kind": "output_schema"}})
    case("validation", data, "validation span without kind and result")
    data = canned(); data.append({**data[0], "span_id": "2", "parent_span_id": "1", "name": "oa.contract.evaluate",
                                  "attributes": {"oa.contract.enabled": True}})
    case("contract", data, "contract span without a result")
    # Each indicator, from the shape that moves it.
    data = canned(chat_status=1)
    data[1]["attributes"].update({"gen_ai.usage.input_tokens": 10, "gen_ai.usage.output_tokens": 5,
                                  "oa.usage.estimated_cost_usd": 0.25, "gen_ai.request.model": "m"})
    data[1]["end_time_unix_nano"] = 2_000_010
    case("model_usage", data, check=lambda r: r["indicators"]["model_usage"] == {
        "source": "agent traces", "model_calls": 1, "input_tokens": 10, "output_tokens": 5,
        "estimated_cost_usd": 0.25, "note": r["indicators"]["model_usage"]["note"]}
        and rec(r)["model_calls"][0]["duration_ms"] == 2 and rec(r)["model_calls"][0]["status"] == "ok")
    case("model_call_error", canned(chat_status=2), check=lambda r: rec(r)["model_calls"][0]["status"] == "error")
    gone = dict(verdict="indeterminate", reason="execution_failed", root_status=2,
                error_type="PROVIDER_ERROR", chat_status=2)
    case("ended_before_verdict", canned(**gone) + canned(trace="02"),
         check=lambda r: r["indicators"]["attempts_with_verdict"] == {"source": "agent traces", "value": 0.5, "numerator": 1, "denominator": 2, "note": r["indicators"]["attempts_with_verdict"]["note"]}
         and rec(r)["attempt"] == "ended_before_verdict")
    # Each reason is one input: the other reason's count staying zero is what
    # catches a widening, so a widening fails the other reason's case.
    case("reason_validation_skipped", canned(verdict="indeterminate", reason="validation_skipped"),
         check=lambda r: r["indicators"]["validation_skipped"]["value"] == 1 and r["indicators"]["sandbox_not_declared"]["value"] == 0)
    case("reason_sandbox_not_declared", canned(verdict="indeterminate", reason="sandbox_not_declared"),
         check=lambda r: r["indicators"]["sandbox_not_declared"]["value"] == 1 and r["indicators"]["validation_skipped"]["value"] == 0)
    case("nonconformant_without_override", canned(verdict="nonconformant") + canned(trace="02", verdict="nonconformant", override="system"),
         check=lambda r: r["indicators"]["nonconformant_without_override"]["value"] == 1)
    case("blocked_prevented", canned(blocked=True, verdict="violation_prevented") + canned(trace="02", blocked=True),
         check=lambda r: r["indicators"]["blocked_recorded_as_prevented"]["value"] == 0.5 and rec(r)["sandbox_decisions"] == {"allowed": 0, "blocked": 1})
    case("blocked_none", canned(), check=lambda r: r["indicators"]["blocked_recorded_as_prevented"]["value"] is None)
    data = canned(tool="read", status=2, verdict="violation_prevented", blocked=True)
    data[1]["attributes"]["oa.tool.result"] = "blocked"
    case("tool_outcomes", data + canned(trace="02", tool="read", status=2) + canned(trace="03", tool="read"),
         check=lambda r: {k: r["indicators"]["tool_calls"][k] for k in ("success", "error", "blocked")} == {"success": 1, "error": 1, "blocked": 1})

    def recall(trace, *names, **kw):
        data = canned(trace=trace, **kw)
        data[0]["attributes"].update({"oa.spec.name": "precedent-analyst", "oa.task.name": "recall"})
        for offset, name in enumerate(names, 1):
            data.append({"trace_id": trace, "span_id": f"t{offset}", "parent_span_id": "1",
                         "name": f"execute_tool {name}", "status_code": 1,
                         "start_time_unix_nano": 10 + offset, "end_time_unix_nano": 10 + offset,
                         "attributes": {"gen_ai.tool.name": name}})
        return data
    case("recall_coverage_first",
         recall("01", COVERAGE_TOOL, SEARCH_TOOL) + recall("02", SEARCH_TOOL, COVERAGE_TOOL)
         + recall("03", COVERAGE_TOOL) + recall("04", SEARCH_TOOL) + recall("05"),
         check=lambda r: r["indicators"]["recall_coverage_first"]["numerator"] == 2
         and r["indicators"]["recall_coverage_first"]["denominator"] == 5)
    case("recall_abandoned_excluded", recall("01", COVERAGE_TOOL, SEARCH_TOOL, **gone),
         check=lambda r: r["indicators"]["recall_coverage_first"]["denominator"] == 0)
    # Span order is start time, not file order: a search written first but
    # started later is still after coverage.
    data = recall("01", SEARCH_TOOL, COVERAGE_TOOL)
    data[1]["start_time_unix_nano"] = data[1]["end_time_unix_nano"] = 13
    case("recall_order_by_start", data, check=lambda r: r["indicators"]["recall_coverage_first"]["numerator"] == 1)
    case("statuses", canned(), status=(1, 0), output=["x"],
         check=lambda r: r["indicators"]["driver"]["value"] is False and r["indicators"]["stage_check"]["value"] is True
         and r["driver_status"] == 1 and r["check_status"] == 0 and r["check_output"] == ["x"])
    case("statuses_unknown", canned(), check=lambda r: r["indicators"]["driver"]["value"] is None and r["indicators"]["stage_check"]["value"] is None)
    case("sources", canned(), check=lambda r: {k: v["source"] for k, v in r["indicators"].items()} == INDICATOR_SOURCES
         and set(INDICATOR_SOURCES.values()) == set(SOURCES) == {"agent traces", "check", "driver"}
         and r["window"]["source"] == "agent traces" and set(r["sources"]) == set(SOURCES))
    # 5: the forms the parser accepts that no sample exercises.
    for override in ("user", "both"):
        case(f"override_{override}", canned(override=override), check=lambda r, o=override: rec(r)["prompt_override"] == o and rec(r)["stage"].endswith(":" + o))
    case("tool_status_unset", canned(tool="record_update", status=0), check=lambda r: rec(r)["tools"][0]["outcome"] == "success")
    late = canned(trace="02"); late[0]["start_time_unix_nano"], late[0]["end_time_unix_nano"] = 5_000_000, 9_000_000
    case("window_and_order", canned() + late,
         check=lambda r: r["window"] == {"source": "agent traces", "start_unix_nano": 10, "end_unix_nano": 9_000_000, "duration_ms": 8, "note": r["window"]["note"]}
         and [a["trace_id"] for a in r["attempts"]] == ["01", "02"])
    # Endpoints off the millisecond grid: the last stage ends 0.9 ms after a
    # whole millisecond, and the window must end where the span ended.
    odd = canned(); odd[0]["start_time_unix_nano"], odd[0]["end_time_unix_nano"] = 100_000, 4_900_000
    case("window_sub_millisecond", odd,
         check=lambda r: rec(r)["end_unix_nano"] == 4_900_000 and rec(r)["duration_ms"] == 4
         and r["window"]["end_unix_nano"] == 4_900_000 and r["window"]["duration_ms"] == 4)

    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "spans.jsonl"
        for name, data, error, check, status, output in cases:
            path.write_text("\n".join(map(json.dumps, data)), encoding="utf-8")
            try:
                spans, errors = read_spans(path)
                result, errors = compute(spans, path, *status, output) if not errors else (None, errors)
                if error:
                    good = len(errors) == 1 and error in errors[0]
                else:
                    good = not errors and (check is None or bool(check(result)))
                    if good:
                        json.dumps(result)
            except Exception as exc:
                good, errors = False, [f"crash: {exc}"]
            print(f"{'ok' if good else 'FAIL'} {name}" + (f": {errors}" if not good else ""))
            failed += not good
        # The status file, both halves, and the aggregate on known inputs.
        def status_of(text):
            Path(tmp, "s").write_text(text, encoding="utf-8")
            return load_status(Path(tmp, "s"))
        extra = [("status_file", lambda: status_of("driver=1\ncheck=0\n") == (1, 0)),
                 ("status_partial", lambda: status_of("check=2\n") == (None, 2)),
                 ("status_partial_check", lambda: status_of("driver=1\n") == (1, None)),
                 ("status_line", lambda: rejects(lambda: status_of("driver=ok\n"), "expected an exit status")),
                 ("status_key", lambda: rejects(lambda: status_of("report=0\n"), "expected a driver= or check= line")),
                 ("status_nosep", lambda: rejects(lambda: status_of("driver\n"), "expected a driver= or check= line")),
                 ("percentile", lambda: (percentile([30, 10, 20], 50), percentile([30, 10, 20], 95), percentile([7], 95)) == (20, 30, 7)),
                 ("aggregate", lambda: aggregate_case()),
                 ("slo_per_run", lambda: slo_case("per_run")),
                 ("slo_rolling", lambda: slo_case("rolling")),
                 ("slo_latency", lambda: slo_case("latency")),
                 ("slo_end_to_end", lambda: slo_case("end_to_end")),
                 ("slo_overall", lambda: slo_case("overall")),
                 ("slo_unknown_indicator", lambda: slo_case("unknown")),
                 ("slo_file", lambda: slo_case("file")),
                 ("slo_rolling_none", lambda: slo_case("rolling_none")),
                 ("slo_stage_series", lambda: slo_case("stage_series")),
                 ("slo_per_run_order", lambda: slo_case("per_run_order"))]
        for name, probe in extra:
            try:
                good = bool(probe())
            except Exception as exc:
                good = False
                print(f"crash: {exc}")
            print(f"{'ok' if good else 'FAIL'} {name}")
            failed += not good
    print(f"Agent traces SLI self-test: {len(cases) + len(extra)} cases, {failed} failures.")
    return failed


def rejects(call, message):
    """A rejection with this check's own message: int() raising on the same input is not the guard."""
    try:
        call()
    except ValueError as exc:
        return message in str(exc)
    return False


def aggregate_case():
    gone = dict(verdict="indeterminate", reason="execution_failed", root_status=2,
                error_type="PROVIDER_ERROR", chat_status=2)
    runs = []
    for status, data in ((0, canned()), (1, canned(**gone) + canned(trace="02")), (None, canned(verdict="nonconformant"))):
        for span in data:
            span["end_time_unix_nano"] = span["start_time_unix_nano"] + 1_000_000 * (len(runs) + 1)
        runs.append(compute(data, "x", status, status)[0])
    out = aggregate(runs)
    stage = out["stages"]["scribe:timeline:none"]
    return (out["runs"] == 3 and stage["attempts"] == 4 and stage["completed"] == 3
            and stage["verdicts"] == {"conformant": 2, "indeterminate": 1, "nonconformant": 1}
            and stage["duration_ms"] == {"p50": 2, "p95": 3, "max": 3}
            and {k: out["window_ms"][k] for k in ("p50", "p95", "max")} == {"p50": 2, "p95": 3, "max": 3}
            and out["driver"]["value"] == 0.5 and out["stage_check"]["numerator"] == 1
            and out["driver"]["source"] == "driver" and out["stage_check"]["source"] == "check")


def slo_runs():
    """Three runs: a clean one, one with a failed driver and a transport
    failure, and a slow one, so every target has a run that meets it and a
    run that does not."""
    gone = dict(verdict="indeterminate", reason="execution_failed", root_status=2,
                error_type="PROVIDER_ERROR", chat_status=2)
    runs = []
    # Driver statuses 1, 0, 0 in start order: a rolling window of two sees
    # two passes, the whole sequence sees two of three, and the reversed
    # sequence sees one of two. Names run counter to start order and the
    # list is returned out of order, so a window taken by file name or by
    # argument order sees a different pair than one taken by start time.
    specs = [((1, 0), canned(), 1_000_000, "zz-last-by-name"), ((0, 0), canned(**gone) + canned(trace="02"), 2_000_000, "mm-middle"),
             ((0, 0), canned(), 400_000_000, "aa-first-by-name")]
    for index, ((driver, check), data, length, name) in enumerate(specs):
        for span in data:
            span["start_time_unix_nano"] = 10 + index * 10_000_000_000
            span["end_time_unix_nano"] = span["start_time_unix_nano"] + length
        runs.append(compute(data, name, driver, check)[0])
    return [runs[1], runs[2], runs[0]]


def slo_case(which):
    runs = slo_runs()
    # blocked_recorded_as_prevented is None on every run here (no blocked
    # call), so it must be counted on none of them rather than missed on all.
    targets = {"per_run": {"stage_check": {"equals": True}, "attempts_ended_before_verdict": {"equals": 0},
                           "blocked_recorded_as_prevented": {"equals": 1.0}},
               "rolling": {"driver": {"at_least": 0.9, "window": 2}},
               "latency_p95_ms": {"stages": {"scribe:timeline:none": 300, "other:task:none": 1}, "end_to_end": 350}}
    if which == "unknown":
        bad = {"per_run": {"no_such_indicator": {"equals": 0}}}
        return rejects(lambda: aggregate(runs, bad, "x"), "no run carries")
    if which == "file":
        targets = yaml.safe_load(Path(__file__).with_name("agent_traces_slo.yaml").read_text(encoding="utf-8"))
        s = aggregate(runs, targets, "x")["slo"]
        return ({k: v["target"] for k, v in s["per_run"].items()} == {k: v["equals"] for k, v in targets["per_run"].items()}
                and {k: (v["target"], v["window"]) for k, v in s["rolling"].items()} == {k: (v["at_least"], v["window"]) for k, v in targets["rolling"].items()}
                and {k: v["target"] for k, v in s["latency_p95_ms"]["stages"].items()} == targets["latency_p95_ms"]["stages"]
                and s["latency_p95_ms"]["end_to_end"]["target"] == targets["latency_p95_ms"]["end_to_end"])
    s = aggregate(runs, targets, "x")["slo"]
    if which == "per_run":
        return (s["per_run"]["stage_check"] == {"target": True, "runs_counted": 3, "runs_met": 3, "met": True, "missed": [], "note": ""}
                and s["per_run"]["attempts_ended_before_verdict"]["runs_met"] == 2
                and s["per_run"]["attempts_ended_before_verdict"]["missed"] == ["mm-middle"]
                and s["per_run"]["attempts_ended_before_verdict"]["met"] is False
                and s["per_run"]["blocked_recorded_as_prevented"]["runs_counted"] == 0
                and s["per_run"]["blocked_recorded_as_prevented"]["met"] is None)
    if which == "rolling":
        # Window of two is the last two runs by start, both passing.
        return s["rolling"]["driver"] == {"target": 0.9, "window": 2, "runs_in_window": 2, "value": 1.0, "met": True, "note": ""}
    if which == "latency":
        st = s["latency_p95_ms"]["stages"]
        return st["scribe:timeline:none"] == {"target": 300, "p95": 400, "met": False} and st["other:task:none"] == {"target": 1, "p95": None, "met": None}
    if which == "end_to_end":
        return s["latency_p95_ms"]["end_to_end"] == {"target": 350, "p95": 400, "met": False}
    if which == "rolling_none":
        blank = [compute(canned(trace=f"0{i}"), f"n{i}", None, None)[0] for i in range(2)]
        s = aggregate(blank, {"rolling": {"driver": {"at_least": 0.9, "window": 2}}}, "x")["slo"]
        return s["rolling"]["driver"]["value"] is None and s["rolling"]["driver"]["met"] is None and s["met"] is False and s["unmeasured"] == 1
    if which == "stage_series":
        # Two completed attempts of one stage, and an abandoned one between
        # them: the series keeps both completed durations in start order and
        # never the abandoned one, which the p95 did not count either.
        gone = dict(verdict="indeterminate", reason="execution_failed", root_status=2,
                    error_type="PROVIDER_ERROR", chat_status=2)
        twice = canned() + canned(trace="02", **gone) + canned(trace="03")
        twice[0]["end_time_unix_nano"] = 10 + 50_000_000
        for span in twice[1:-1]:
            span["start_time_unix_nano"] = 15; span["end_time_unix_nano"] = 15 + 99_000_000
        twice[-1]["start_time_unix_nano"] = 20; twice[-1]["end_time_unix_nano"] = 20 + 20_000_000
        run = compute(twice, "x", None, None)[0]
        row = aggregate([run])["per_run"][0]
        return row["stages"] == {"scribe:timeline:none": [50, 20]}
    if which == "per_run_order":
        rows = aggregate(slo_runs())["per_run"]
        return [r["spans"] for r in rows] == ["zz-last-by-name", "mm-middle", "aa-first-by-name"]
    if which == "overall":
        easy = {"per_run": {"stage_check": {"equals": True}}, "latency_p95_ms": {"end_to_end": 500}}
        ok = aggregate(runs, easy, "x")["slo"]
        unmeasured = aggregate(runs, {"latency_p95_ms": {"stages": {"other:task:none": 1}}}, "x")["slo"]
        return s["met"] is False and s["unmeasured"] == 2 and ok["met"] is True and ok["unmeasured"] == 0 and unmeasured["met"] is False and unmeasured["unmeasured"] == 1
    raise ValueError(which)


def mutation_test():
    source = Path(__file__).read_text()
    mutations = []
    lines = source.splitlines()
    for index, line in enumerate(lines):
        if not re.search(r"# guard [a-z_+]+$", line):
            continue
        name = tuple(line.split("# guard ")[1].split("+"))
        original = lines[index + 1]
        indent = original[:len(original) - len(original.lstrip())]
        mutations.append((name, original, indent + "pass"))
    # A mutation names every case it must fail, and no other may. A change to
    # a classifier several indicators read fails one case per reader, and
    # the set says which readers are load-bearing.
    mutations.extend([
        ("usage_bool", "type(value) is not int", "not isinstance(value, int)"),
        ("cost_bool", "isinstance(cost, bool) or", ""),
        ("model_call_error", '"status": "error" if span["status_code"] == 2 else "ok"', '"status": "ok"'),
        (("ended_before_verdict", "recall_abandoned_excluded", "aggregate", "slo_per_run", "slo_stage_series"),
         'if provider_failure(root, verdict, reason, members) else "completed"', 'if False else "completed"'),
        ("reason_sandbox_not_declared", 'r["reason"] == "validation_skipped"', 'r["reason"] in ("validation_skipped", "sandbox_not_declared")'),
        ("reason_validation_skipped", 'r["reason"] == "sandbox_not_declared"', 'r["reason"] in ("validation_skipped", "sandbox_not_declared")'),
        ("nonconformant_without_override", 'and r["prompt_override"] == "none"', ''),
        (("blocked_none", "slo_per_run", "slo_overall"), 'blocked = [r for r in attempts if r["sandbox_decisions"]["blocked"]]', 'blocked = list(attempts)'),
        (("blocked_none", "slo_per_run", "slo_overall"), '"value": (numerator / denominator) if denominator else None', '"value": (numerator / denominator) if denominator else 1.0'),
        ("tool_outcomes", '"blocked" if attrs.get("oa.tool.result") == "blocked" else (', '"error" if attrs.get("oa.tool.result") == "blocked" else ('),
        ("recall_abandoned_excluded", "recalls = [r for r in completed if", "recalls = [r for r in attempts if"),
        ("recall_coverage_first", "    if SEARCH_TOOL not in names:\n        return True", "    if SEARCH_TOOL not in names:\n        return False"),
        ("recall_coverage_first", "return names.index(COVERAGE_TOOL) < names.index(SEARCH_TOOL)", "return True"),
        ("recall_order_by_start", 'key=lambda s: (s["start_time_unix_nano"], s["span_id"])', 'key=lambda s: s["span_id"]'),
        (("statuses", "aggregate"), '"value": None if driver_status is None else driver_status == 0', '"value": None if driver_status is None else True'),
        ("statuses_unknown", '"value": None if check_status is None else check_status == 0', '"value": check_status == 0'),
        (("window_and_order", "slo_stage_series"), 'attempts.sort(key=lambda r: (r["start_unix_nano"], r["trace_id"]))', 'attempts.sort(key=lambda r: r["trace_id"], reverse=True)'),
        (("window_and_order", "window_sub_millisecond", "aggregate", "slo_end_to_end"), '"duration_ms": ms(max(ends) - min(starts))', '"duration_ms": ms(max(starts) - min(starts))'),
        ("window_sub_millisecond", 'ends = [r["end_unix_nano"] for r in attempts]', 'ends = [r["start_unix_nano"] + r["duration_ms"] * 1_000_000 for r in attempts]'),
        ("status_partial", 'return values.get("driver"), values.get("check")', 'return values.get("driver", 0), values.get("check")'),
        ("status_partial_check", 'return values.get("driver"), values.get("check")', 'return values.get("driver"), values.get("check", 0)'),
        ("sources", '"source": "check", "status": check_status,', '"source": "agent traces", "status": check_status,'),
        ("sources", '"source": "driver", "status": driver_status,', '"source": "check", "status": driver_status,'),
        ("cost_infinite", "cost < 0 or not math.isfinite(cost)", "cost < 0"),
        ("tool_status_unset", '"error" if span["status_code"] == 2 else "success")', '"error" if span["status_code"] != 1 else "success")'),
        ("status_line", 'if not re.fullmatch(r"[0-9]+", value):', 'if not re.fullmatch(r"[0-9a-z]+", value):'),
        (("percentile", "aggregate"), "ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]", "ordered[min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)))]"),
        ("aggregate", 'if r["attempt"] == "completed":\n                entry["durations_ms"].append', 'if True:\n                entry["durations_ms"].append'),
        (("slo_per_run", "slo_overall"), "if value is None:\n                continue", "if False:\n                continue"),
        ("slo_rolling", 'window = ordered[-target["window"]:]', 'window = ordered'),
        ("slo_rolling", 'ordered = sorted(runs, key=lambda r: (r["window"]["start_unix_nano"], r["spans"]))', 'ordered = sorted(runs, key=lambda r: (r["window"]["start_unix_nano"], r["spans"]), reverse=True)'),
        ("slo_latency", 'p95 = stage["duration_ms"]["p95"] if stage and stage["duration_ms"] else None', 'p95 = stage["duration_ms"]["p50"] if stage and stage["duration_ms"] else None'),
        (("slo_overall", "slo_rolling_none"), 'out["unmeasured"] = sum(1 for v in verdicts if v is None)', 'out["unmeasured"] = 0'),
        (("slo_overall", "slo_rolling_none"), 'out["met"] = all(v is True for v in verdicts)', 'out["met"] = all(v is not False for v in verdicts)'),
        ("slo_per_run", "if value == wanted:\n                met += 1", "if True:\n                met += 1"),
        ("slo_rolling", '"met": (value >= target["at_least"]) if value is not None else None,', '"met": False if value is not None else None,'),
        ("slo_latency", '"met": (p95 <= target) if p95 is not None else None}', '"met": True if p95 is not None else None}'),
        ("slo_end_to_end", '"met": p95 <= latency["end_to_end"]}', '"met": True}'),
        ("slo_rolling_none", '"met": (value >= target["at_least"]) if value is not None else None,', '"met": (value >= target["at_least"]) if value is not None else True,'),
        ("slo_rolling", 'ordered = sorted(runs, key=lambda r: (r["window"]["start_unix_nano"], r["spans"]))', 'ordered = sorted(runs, key=lambda r: r["spans"])'),
        ("slo_rolling", 'ordered = sorted(runs, key=lambda r: (r["window"]["start_unix_nano"], r["spans"]))', 'ordered = list(runs)'),
        ("slo_stage_series", 'series.setdefault(a["stage"], []).append(a["duration_ms"])', 'series[a["stage"]] = [a["duration_ms"]]'),
        ("slo_stage_series", 'if a["attempt"] == "completed":\n            series.setdefault', 'if True:\n            series.setdefault'),
        ("slo_per_run_order", '    } for r in sorted(runs, key=lambda r: (r["window"]["start_unix_nano"], r["spans"]))]', '    } for r in runs]'),
        (("slo_file", "slo_end_to_end"), '"met": p95 <= latency["end_to_end"]}', '"met": p95 <= latency["end_to_end"]}\n        out["latency_p95_ms"]["end_to_end"]["target"] = 0'),
    ])
    production, tests = source.split("def self_test(", 1)
    failures = 0
    for names, original, replacement in mutations:
        names = (names,) if isinstance(names, str) else names
        name = "+".join(names)
        assert production.count(original) == 1, name
        altered = production.replace(original, replacement, 1) + "def self_test(" + tests
        assert altered != source
        namespace = {"__name__": "agent_traces_sli_mutation", "__file__": __file__}
        capture = io.StringIO()
        try:
            with redirect_stdout(capture):
                exec(compile(altered, __file__, "exec"), namespace)
                count = namespace["self_test"]()
            failed = [line for line in capture.getvalue().splitlines() if line.startswith("FAIL ")]
            got = sorted(line.split()[1].rstrip(":") for line in failed)
            good = count == len(names) and got == sorted(names) and "crash:" not in capture.getvalue()
        except Exception as exc:
            good, failed = False, [f"crash: {exc}"]
        print(f"{'ok' if good else 'FAIL'} mutation {name}: " + "; ".join(failed))
        failures += not good
    print(f"Agent traces SLI mutations: {len(mutations)} mutations, {failures} failures.")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spans", nargs="*", help="spans.jsonl, or sli.json files with --aggregate")
    parser.add_argument("--status-file", help="driver=N and check=N, as demos/traced.sh writes it")
    parser.add_argument("--check-output", help="what checks/agent_traces.py printed for this run")
    parser.add_argument("--aggregate", action="store_true", help="baseline across sli.json files")
    parser.add_argument("--slo", help="with --aggregate: hold the runs to this targets file")
    parser.add_argument("-o", "--output", help="write here instead of stdout")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--mutation-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return bool(self_test())
    if args.mutation_test:
        return bool(mutation_test())
    if args.aggregate:
        if not args.spans:
            parser.error("--aggregate needs at least one sli.json")
        runs = []
        for path in args.spans:
            run = json.loads(Path(path).read_text(encoding="utf-8"))
            if run.get("schema") != SCHEMA:
                sys.exit(f"FAIL: {path} is not {SCHEMA}")
            runs.append(run)
        slo = yaml.safe_load(Path(args.slo).read_text(encoding="utf-8")) if args.slo else None
        result = aggregate(runs, slo, args.slo)
    else:
        if len(args.spans) != 1:
            parser.error("one spans.jsonl is required")
        driver_status, check_status = load_status(args.status_file) if args.status_file else (None, None)
        output = Path(args.check_output).read_text(encoding="utf-8").splitlines() if args.check_output else None
        spans, errors = read_spans(args.spans[0])
        result, errors = compute(spans, args.spans[0], driver_status, check_status, output) if not errors else (None, errors)
        if errors:
            for error in errors:
                print(f"FAIL {error}", file=sys.stderr)
            return 1
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
