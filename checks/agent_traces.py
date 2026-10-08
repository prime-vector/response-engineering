#!/usr/bin/env python3
"""Check stages in the local agent traces sink's JSONL format, without packages."""
import argparse
import copy
import io
import json
import re
from pathlib import Path
import sys
import tempfile
from contextlib import redirect_stdout

WRITE_TOOLS = {
    "record_create",
    "record_update",
    "change_draft",
}
VERDICTS = {"conformant", "violation_prevented", "nonconformant", "indeterminate"}


def read_spans(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [], [f"file {path}: unreadable spans file ({exc})"]  # guard unreadable
    if not text.strip():  # guard empty
        return [], [f"file {path}: empty spans file"]
    result = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            span = json.loads(line)
        except ValueError:
            return [], [f"file {path} line {number}: invalid JSON"]  # guard json
        # Only the sink's flattened format is supported, not OTLP JSON envelopes.
        if not isinstance(span, dict):  # guard object
            return [], [f"file {path} line {number}: span must be an object"]
        if not isinstance(span.get("trace_id"), str) or not span["trace_id"]:  # guard trace_id
            return [], [f"file {path} line {number}: missing trace id"]
        if not isinstance(span.get("parent_span_id"), str):  # guard parent
            return [], [f"trace {span['trace_id']}: parent span id must be a string"]
        if not isinstance(span.get("attributes"), dict):  # guard attributes
            return [], [f"trace {span['trace_id']}: attributes must be an object"]
        if type(span.get("status_code")) is not int or span["status_code"] not in (0, 1, 2):  # guard status
            return [], [f"trace {span['trace_id']}: status code must be 0, 1 or 2"]
        if not isinstance(span.get("name"), str):  # guard name
            return [], [f"trace {span['trace_id']}: span name must be a string"]
        result.append(span)
    return result, []


def provider_failure(root, verdict, reason):
    """The signature OA 1.6.2 leaves on a run a transport failure ended.

    Its outer handler records any error that is not a sandbox block, a
    validation failure or a bad input as indeterminate / execution_failed,
    and sets error.type to the error code. Read from a live run on
    8 Oct 2026, not inferred: the inner runner raises PROVIDER_ERROR without
    a verdict, and the outer handler is what adds one. PROVIDER_ERROR is the
    provider failing, a dropped connection or a rejected key, so the run never
    reached a verdict; the drivers retry the transport kind once. Any other
    crash, RUN_ERROR included, stays a failure.
    """
    return (root["status_code"] == 2  # condition indeterminate_without_error
            and verdict == "indeterminate"  # condition error_with_verdict
            and reason == "execution_failed"  # condition error_with_reason
            and root["attributes"].get("error.type") == "PROVIDER_ERROR")  # condition run_error


def check(spans, expected=(), expect_write=()):
    traces = {}
    for span in spans:
        traces.setdefault(span["trace_id"], []).append(span)
    failures, summaries, stages = [], [], []
    for trace, members in traces.items():
        roots = [s for s in members if s["parent_span_id"] == ""]
        if not roots:  # guard root
            failures.append(f"trace {trace}: no root span")
            continue
        if len(roots) > 1:  # guard multiple_roots
            failures.append(f"trace {trace}: multiple root spans")
            continue
        root = roots[0]
        attrs = root["attributes"]
        spec, task, override, verdict = (attrs.get(k) for k in (
            "oa.spec.name", "oa.task.name", "oa.prompt.override", "oa.conformance.status"))
        stage = f"{spec}:{task}:{override} [trace {trace}]"
        if not isinstance(spec, str) or not spec or not isinstance(task, str) or not task or override not in ("none", "system", "user", "both") or not isinstance(verdict, str) or verdict not in VERDICTS:  # guard stage_metadata
            failures.append(f"{stage}: missing or invalid stage metadata")
            continue
        reason = attrs.get("oa.conformance.reason", "")
        ended_before_verdict = provider_failure(root, verdict, reason)
        tools = [s for s in members if s["name"].startswith("execute_tool ")]
        called = []
        successful = set()
        for tool in tools:
            a = tool["attributes"]
            name = a.get("gen_ai.tool.name", tool["name"].removeprefix("execute_tool "))
            if not isinstance(name, str) or not name:  # guard tool_metadata
                failures.append(f"{stage}: missing or invalid tool name")
                continue
            outcome = "blocked" if a.get("oa.tool.result") == "blocked" else (
                "error" if tool["status_code"] == 2 else "success")
            called.append(f"{name}={outcome}")
            if tool["status_code"] != 2:
                successful.add(name)
        summaries.append(f"{stage} spec={spec} task={task} prompt_override={override} "
                         f"verdict={verdict} reason={reason or '-'} tools={','.join(called) or '-'} "
                         f"attempt={'ended_before_verdict' if ended_before_verdict else 'completed'}")
        # A transport failure has no verdict to match. It remains subject to
        # the rules below, including any sandbox decision it already made.
        if not ended_before_verdict:
            stages.append((spec, task, override, verdict, successful, stage))
        if verdict == "indeterminate" and reason == "validation_skipped":  # guard validation_skipped
            failures.append(f"{stage}: validation_skipped")
        if verdict == "indeterminate" and reason == "sandbox_not_declared":  # guard sandbox_not_declared
            failures.append(f"{stage}: sandbox_not_declared")
        blocked = any(s["name"] == "oa.sandbox.decision" and
                      s["attributes"].get("oa.sandbox.result") == "blocked" for s in members)
        if blocked and verdict != "violation_prevented":  # expectation blocked
            failures.append(f"{stage}: blocked sandbox decision without violation_prevented")
    # An expectation listed twice needs two stages: traced.sh all runs two
    # modes that each expect assess:system, and one surviving trace must not
    # satisfy both.
    wanted_by_key = {}
    for key, wanted in expected:
        wanted_by_key.setdefault(key, []).append(wanted)
    for key, wanted_list in wanted_by_key.items():
        wanted = "/".join(sorted(set(wanted_list)))
        matched = [s for s in stages if ":".join(s[:3]) == key]
        if not matched:  # expectation expected_missing
            failures.append(f"{key}: expected stage missing (wanted {wanted})")
        # Counted per verdict, not per stage: two expectations on one stage,
        # one conformant and one nonconformant, need one stage of each.
        for wanted_verdict in sorted(set(wanted_list)):
            need = wanted_list.count(wanted_verdict)
            have = sum(1 for s in matched if s[3] == wanted_verdict)
            if matched and have < need:  # guard expected_count
                failures.append(f"{key}: expected {need} {wanted_verdict} stage(s), found {have}")
        for spec, task, override, verdict, successful, stage in matched:
            if verdict not in wanted_list:  # guard expected_verdict
                failures.append(f"{stage}: expected {wanted}, got {verdict}")
    for key in expect_write:
        matched = [s for s in stages if ":".join(s[:2]) == key]
        if not matched:  # expectation write_missing
            failures.append(f"{key}: expected write stage missing")
        for spec, task, override, verdict, successful, stage in matched:
            if not successful.intersection(WRITE_TOOLS):  # expectation write_success
                failures.append(f"{stage}: no successful write tool")
    return summaries, failures


def canned(*, verdict="conformant", reason="", override="none", tool=None,
           status=1, blocked=False, trace="01", root=True, root_status=1,
           error_type=None):
    """One builder keeps cases tied to the sink's format and runner attributes."""
    def span(name, parent, attributes, code=1):
        return {"trace_id": trace, "span_id": str(len(result) + 1),
                "parent_span_id": parent, "name": name, "status_code": code,
                "start_time_unix_nano": 10, "end_time_unix_nano": 20,
                "attributes": attributes}
    result = []
    if root:
        result.append(span("invoke_agent scribe", "", {
            "oa.spec.name": "scribe", "oa.task.name": "timeline",
            "oa.prompt.override": override, "oa.conformance.status": verdict,
            "oa.conformance.reason": reason}, root_status))
        if reason is None:
            del result[0]["attributes"]["oa.conformance.reason"]
        if error_type is not None:
            result[0]["attributes"]["error.type"] = error_type
    if tool:
        result.append(span(f"execute_tool {tool}", "1", {"gen_ai.tool.name": tool}, status))
    if blocked:
        result.append(span("oa.sandbox.decision", "1", {"oa.sandbox.result": "blocked"}))
    return result


def self_test():
    cases = []
    def case(name, data=None, reason=None, expected=(), writes=(), raw=None, missing=False):
        cases.append((name, data, reason, expected, writes, raw, missing))
    case("validation_skipped", canned(verdict="indeterminate", reason="validation_skipped"), "validation_skipped")
    case("sandbox_not_declared", canned(verdict="indeterminate", reason="sandbox_not_declared"), "sandbox_not_declared")
    case("blocked", canned(blocked=True), "blocked sandbox decision without violation_prevented")
    case("write_success", canned(tool="record_update", status=2), "no successful write tool", writes=["scribe:timeline"])
    case("write_missing", canned(), "expected write stage missing", writes=["other:task"])
    case("expected_missing", canned(), "expected stage missing", expected=[("other:task:none", "conformant")])
    case("empty", raw="", reason="empty spans file")
    case("unreadable", missing=True, reason="unreadable spans file")
    case("json", raw="{", reason="invalid JSON")
    case("root", canned(root=False, tool="read"), "no root span")
    data = canned(); data.append(copy.deepcopy(data[0]))
    case("multiple_roots", data, "multiple root spans")
    case("object", raw="[]", reason="span must be an object")
    for name, field, value, reason in [
        ("trace_id", "trace_id", "", "missing trace id"),
        ("parent", "parent_span_id", None, "parent span id must be a string"),
        ("attributes", "attributes", [], "attributes must be an object"),
        ("status", "status_code", "ERROR", "status code must be 0, 1 or 2"),
        ("name", "name", None, "span name must be a string"),
    ]:
        data = canned(); data[0][field] = value
        case(name, data, reason)
    data = canned(); del data[0]["attributes"]["oa.task.name"]
    case("stage_metadata", data, "missing or invalid stage metadata")
    data = canned(tool="read"); data[1]["attributes"]["gen_ai.tool.name"] = ""
    case("tool_metadata", data, "missing or invalid tool name")
    case("host_not_write", canned(tool="selinux_setenforce"), "no successful write tool",
         writes=["scribe:timeline"])
    for tool in ("record_create", "record_update", "change_draft"):
        case(f"write_{tool}", canned(tool=tool), writes=["scribe:timeline"])
    for status in (0, 1):
        case(f"success_status_{status}", canned(tool="record_update", status=status))
    case("tool_error", canned(tool="read", status=2, verdict="indeterminate", reason="tool_error"))
    case("prevented", canned(blocked=True, verdict="violation_prevented"))
    case("normal", canned(), expected=[("scribe:timeline:none", "conformant")])
    # One input for every weakening of the count: conformant listed twice
    # (the shape traced.sh all produces) against one conformant stage, beside
    # a nonconformant listing. A per-stage count passes it (three stages, three
    # listings), so does counting each verdict once, and so does no count.
    case("expected_count",
         canned() + canned(trace="02", verdict="nonconformant")
         + canned(trace="03", verdict="nonconformant"),
         "expected 2 conformant stage(s), found 1",
         expected=[("scribe:timeline:none", "conformant")] * 2
         + [("scribe:timeline:none", "nonconformant")])
    case("expected_count_repeat", canned() + canned(trace="02", verdict="nonconformant"),
         expected=[("scribe:timeline:none", "conformant"), ("scribe:timeline:none", "nonconformant")])
    case("expected_count_met", canned() + canned(trace="02"),
         expected=[("scribe:timeline:none", "conformant")] * 2)
    for override in ("system", "user", "both"):
        case(f"override_{override}", canned(override=override, verdict="nonconformant"),
             expected=[(f"scribe:timeline:{override}", "nonconformant")])
    case("multiple_traces", canned() + canned(trace="02", override="system", verdict="nonconformant"),
         expected=[("scribe:timeline:none", "conformant"), ("scribe:timeline:system", "nonconformant")])
    case("expected_verdict", canned() + canned(trace="02", verdict="nonconformant"),
         "expected conformant, got nonconformant", expected=[("scribe:timeline:none", "conformant")])
    # A transport failure as OA 1.6.2 records it, from a live run.
    gone = dict(verdict="indeterminate", reason="execution_failed",
                root_status=2, error_type="PROVIDER_ERROR")
    case("abandoned_retry", canned(**gone) + canned(trace="02"),
         expected=[("scribe:timeline:none", "conformant")])
    case("abandoned_only_expect", canned(**gone),
         "expected stage missing", expected=[("scribe:timeline:none", "conformant")])
    case("abandoned_only_write", canned(**gone, tool="record_update"),
         "expected write stage missing", writes=["scribe:timeline"])
    # Each is the signature with one part changed, so it is a real stage and
    # meets its expectation; dropping that part of the rule hides it.
    case("indeterminate_without_error", canned(**{**gone, "root_status": 1}),
         expected=[("scribe:timeline:none", "indeterminate")])
    case("error_with_verdict", canned(**{**gone, "verdict": "conformant"}),
         expected=[("scribe:timeline:none", "conformant")])
    case("error_with_reason", canned(**{**gone, "reason": "tool_error"}),
         expected=[("scribe:timeline:none", "indeterminate")])
    case("run_error", canned(**{**gone, "error_type": "RUN_ERROR"}),
         expected=[("scribe:timeline:none", "indeterminate")])
    case("abandoned_blocked", canned(**gone, blocked=True),
         "blocked sandbox decision without violation_prevented")
    data = canned(tool="record_update"); del data[1]["attributes"]["gen_ai.tool.name"]
    case("tool_name_fallback", data)
    data = canned(tool="read", status=2, verdict="violation_prevented", blocked=True)
    data[1]["attributes"]["oa.tool.result"] = "blocked"
    case("blocked_tool_summary", data)
    data = canned(tool="read")
    data[1]["name"] = "chat model"
    other = copy.deepcopy(data[1]); other["name"] = "execute_task timeline"
    data.append(other)
    case("tool_selection", data)
    case("blank_lines", raw="\n" + json.dumps(canned()[0]) + "\n\n")
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "spans.jsonl"
        for name, data, reason, expected, writes, raw, missing in cases:
            path.unlink(missing_ok=True)
            if not missing:
                path.write_text(raw if raw is not None else "\n".join(map(json.dumps, data)), encoding="utf-8")
            try:
                spans, errors = read_spans(path)
                summaries, failures = check(spans, expected, writes) if not errors else ([], errors)
                good = (len(failures) == 1 and reason in failures[0]) if reason else not failures
                if name.startswith("success_status_"):
                    good = good and "record_update=success" in summaries[0]
                if name == "blocked_tool_summary":
                    good = good and "read=blocked" in summaries[0]
                if name == "tool_error":
                    good = good and "read=error" in summaries[0]
                if name == "tool_name_fallback":
                    good = good and "record_update=" in summaries[0]
                if name == "tool_selection":
                    good = good and "tools=- " in summaries[0]
                if name.startswith("abandoned_"):
                    good = good and "attempt=ended_before_verdict" in summaries[0]
                if name in ("error_with_reason", "indeterminate_without_error", "error_with_verdict"):
                    good = good and "attempt=completed" in summaries[0]
            except Exception as exc:
                good, failures = False, [f"crash: {exc}"]
            print(f"{'ok' if good else 'FAIL'} {name}" + (f": {failures}" if not good else ""))
            failed += not good
    print(f"Agent traces self-test: {len(cases)} cases, {failed} failures.")
    return failed


def mutation_test():
    source = Path(__file__).read_text()
    mutations = []
    lines = source.splitlines()
    for index, line in enumerate(lines):
        if not re.search(r"# guard [a-z_]+$", line):
            continue
        name = line.split("# guard ")[1]
        # Remove the rejection, retaining control flow. An invalid fixture
        # must expose a missing rule rather than crash a weakened reader.
        original = lines[index + 1] if line.lstrip().startswith("if ") else line
        indent = original[:len(original) - len(original.lstrip())]
        replacement = indent + ("return [], []" if original.lstrip().startswith("return ") else "pass")
        mutations.append((name, original, replacement))
    # Membership is a separate claim from iterating a set.
    for tool in sorted(WRITE_TOOLS):
        mutations.append((f"write_{tool}", f'\n    "{tool}",\n', "\n"))
    mutations.extend([
        ("blocked", 'if blocked and verdict != "violation_prevented":',
         'if blocked and verdict == "indeterminate":'),
        ("indeterminate_without_error", 'root["status_code"] == 2  # condition', 'True  # condition'),
        ("error_with_verdict", 'verdict == "indeterminate"  # condition', 'True  # condition'),
        ("error_with_reason", 'reason == "execution_failed"  # condition', 'True  # condition'),
        ("run_error", 'root["attributes"].get("error.type") == "PROVIDER_ERROR")  # condition', 'True)  # condition'),
        ("expected_count", "need = wanted_list.count(wanted_verdict)", "need = 1"),
        ("expected_count", "if matched and have < need:", "if matched and len(matched) < len(wanted_list):"),
        ("abandoned_only_expect", 'if not matched:  # expectation expected_missing',
         'if not matched and stages:  # expectation expected_missing'),
        ("abandoned_only_write", 'if not matched:  # expectation write_missing',
         'if not matched and stages:  # expectation write_missing'),
        ("host_not_write", 'if not successful.intersection(WRITE_TOOLS):', 'if not successful:'),
        ("abandoned_blocked", 'if blocked and verdict != "violation_prevented":',
         'if blocked and verdict != "violation_prevented" and not ended_before_verdict:'),
        ("write_success", 'if tool["status_code"] != 2:', 'if True:'),
        ("tool_error", '"error" if tool["status_code"] == 2 else "success"',
         '"error" if False else "success"'),
        ("success_status_0", '"error" if tool["status_code"] == 2 else "success"',
         '"error" if tool["status_code"] in (0, 2) else "success"'),
        ("success_status_1", '"error" if tool["status_code"] == 2 else "success"',
         '"error" if tool["status_code"] in (1, 2) else "success"'),
        ("blocked_tool_summary", 'a.get("oa.tool.result") == "blocked"', 'False'),
        ("tool_name_fallback", 'tool["name"].removeprefix("execute_tool ")', ''""''),
        ("tool_selection", 'if s["name"].startswith("execute_tool ")', 'if True'),
        ("blank_lines", 'if not line.strip():', 'if False:'),
    ])
    production, tests = source.split("def canned(", 1)
    failures = 0
    for name, original, replacement in mutations:
        assert production.count(original) == 1, name
        altered = production.replace(original, replacement, 1) + "def canned(" + tests
        assert altered != source
        namespace = {"__name__": "agent_traces_mutation", "__file__": __file__}
        capture = io.StringIO()
        try:
            with redirect_stdout(capture):
                exec(compile(altered, __file__, "exec"), namespace)
                count = namespace["self_test"]()
            lines = [line for line in capture.getvalue().splitlines() if line.startswith("FAIL ")]
            good = count == 1 and len(lines) == 1 and lines[0].startswith(f"FAIL {name}:") and "crash:" not in lines[0]
        except Exception as exc:
            good, lines = False, [f"crash: {exc}"]
        print(f"{'ok' if good else 'FAIL'} mutation {name}: " + "; ".join(lines))
        failures += not good
    print(f"Agent traces mutations: {len(mutations)} mutations, {failures} failures.")
    return failures


def expectation(value):
    key, sep, verdict = value.partition("=")
    if not sep or len(key.split(":")) != 3 or verdict not in VERDICTS:
        raise argparse.ArgumentTypeError("expected SPEC:TASK:OVERRIDE=VERDICT")
    return key, verdict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spans", nargs="?")
    parser.add_argument("--expect", action="append", type=expectation, default=[])
    parser.add_argument("--expect-write", action="append", default=[])
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--mutation-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return bool(self_test())
    if args.mutation_test:
        return bool(mutation_test())
    if not args.spans:
        parser.error("SPANS.jsonl is required")
    for key in args.expect_write:
        if len(key.split(":")) != 2 or not all(key.split(":")):
            parser.error("--expect-write requires SPEC:TASK")
    spans, failures = read_spans(args.spans)
    summaries, checked = check(spans, args.expect, args.expect_write) if not failures else ([], [])
    for summary in summaries:
        print(summary)
    for failure in failures + checked:
        print(f"FAIL {failure}", file=sys.stderr)
    return bool(failures or checked)


if __name__ == "__main__":
    sys.exit(main())
