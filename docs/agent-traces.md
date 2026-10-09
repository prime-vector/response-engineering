# Agent traces: the OpenTelemetry span model

Agent traces are OpenTelemetry spans. The CLI's `--telemetry` flag turns on
an exporter inside `oa run` that emits one trace per run over OTLP, using the
OpenTelemetry SDK and the standard `OTEL_EXPORTER_OTLP_*` environment
variables, so they go wherever any other OpenTelemetry traces in an
environment already go. The attributes on model and tool spans follow the
OpenTelemetry GenAI semantic conventions (`gen_ai.*`); the attributes that
carry the runner's verdicts are the runner's own (`oa.*`). Nothing in this
repository is a tracing backend: `demos/agent_traces_sink.py` is a minimal
OTLP/HTTP receiver that keeps span metadata as JSONL so a run can be checked
and rendered with no service running, and it is one destination among any.

This document states what the spans contain, what the two checks read from
them, and the one boundary that governs every claim made on them. It is
written from the runner's `telemetry.py` in OA 1.6.2 and from live span files,
not from the OpenTelemetry documentation.

## Naming

Two words are kept apart on purpose. **Telemetry** in this repository is the
incident surface the Telemetry Analyst reads, served by the mock adapter on
port 8422 and specified in `interfaces/TELEMETRY.md`. **Agent traces** are the
runner's OpenTelemetry spans about the agents themselves. The CLI flag is
called `--telemetry` and that is the one place the word means agent traces.

## Sending them anywhere

With the `otel` extra installed, `oa run --telemetry` reads the standard
variables. The wrapper `demos/traced.sh` sets these for the local sink:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:<port>
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

Point the endpoint at an OpenTelemetry Collector, a Jaeger or Tempo instance,
or a hosted tracing platform instead and nothing here changes: the drivers add
`--telemetry` whenever the endpoint variable is set (`demos/retry.sh`), the
runner exports, and the stage check and the page keep working only against the
sink's JSONL, because that is the format they read. The resource carries
`service.name`, which defaults to `open-agent-spec` and follows
`OTEL_SERVICE_NAME`. One `oa run` is one trace until OA issue #116 lands, so a
backend shows a pipeline as five traces in a row rather than one; the wrapper
groups them by run directory.

## What a trace contains

Span names and attributes as the runner emits them, read from live files. A
child is always inside the root of its own trace.

| Span | What it is | Attributes that matter |
| --- | --- | --- |
| `invoke_agent <spec>` | the root: one `oa run` | `oa.spec.name`, `oa.spec.version`, `oa.spec.hash`, `oa.task.name`, `oa.prompt.override` (`none`, `system`, `user`, `both`), `oa.conformance.status`, `oa.conformance.reason`, `oa.sandbox.enabled`, `oa.contract.enabled`, `oa.telemetry.content_capture`, `oa.execution.result`, `error.type`, `oa.error.stage` |
| `execute_task <task>` | the task under the root | `oa.task.name`, `oa.task.declared_tools`, `oa.execution.result`, `oa.usage.estimated_cost_usd` |
| `chat <model>` | one model call | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `oa.usage.estimated_cost_usd`, `error.type` |
| `execute_tool <tool>` | one tool call | `gen_ai.operation.name`, `gen_ai.tool.name`, `gen_ai.tool.call.id`, `oa.tool.result`, `error.type` |
| `oa.sandbox.decision` | the allow list consulted before a tool call | `gen_ai.tool.name`, `oa.sandbox.result` (`allowed` or `blocked`) |
| `oa.validation` | the output checked against its schema | `oa.validation.kind`, `oa.validation.result` |
| `oa.contract.evaluate` | the behavioural contract evaluated | `oa.contract.enabled`, `oa.contract.result` |

The status code on each span is OpenTelemetry's: unset, ok or error. A tool
call that raised, a model call that failed and a run that ended in an error
all carry the error status with `error.type` naming the exception or the OA
error code.

Content capture is off and the runner's telemetry API accepts no content:
prompts, inputs, outputs, tool arguments and tool results are not accepted by
it, and `oa.telemetry.content_capture` is `false` on every root. The spec hash
is a digest of the spec file, so a trace names which version of an agent ran
without carrying the spec.

## The verdict

Every root carries `oa.conformance.status`, one of four values, and a reason
when the status needs one. The four are the runner's constants:

| Verdict | Meaning |
| --- | --- |
| `conformant` | the output passed its schema and, where declared, its contract |
| `violation_prevented` | a control fired as designed: the sandbox blocked a call (`sandbox_tool_violation`) |
| `nonconformant` | the output was rejected (`output_schema_error`, a contract violation) |
| `indeterminate` | no verdict could be reached: `validation_skipped` (the output was not a JSON object, so no schema or contract was checked), `sandbox_not_declared`, `execution_failed` (the run died before the output, with `error.type` saying how) |

The reasons named are the ones seen on live runs here and in the runner's
source; the runner may add others, and the checks treat any unknown reason as
a reason, not as a pass. `indeterminate` with `validation_skipped` is the
documented fail-open on a truncated or malformed output: the CLI exits zero
and the drivers fail closed on their own parse. The stage check rejects it on
sight, which is the second verdict agent traces were built to give.

A transport failure leaves a particular signature: root status error,
`indeterminate`, `execution_failed`, `error.type` `PROVIDER_ERROR`, and a
failed `chat` span in the same trace. A model refusal currently leaves the same
signature, because the streaming patch reports a response with no content
blocks as a cut stream; that is an open task, and until it closes a refusal
is indistinguishable from a dropped connection in the trace.

## What the checks read

`checks/agent_traces.py` reads root attributes for the stage, verdict and
reason, `execute_tool` spans for which tools were called and whether each
raised or was blocked, and `oa.sandbox.decision` spans for a block that the
root failed to record as prevented. It holds a run to the expectations the
driver mode sets and to three always-on rules. `checks/agent_traces_sli.py`
reads the same spans plus `chat` usage, `oa.validation` and
`oa.contract.evaluate` results and the timestamps, and writes one record per
stage attempt with indicators each tagged by source. Neither reads anything
that is not in the table above.

## The boundary

A span proves **that** a tool was called and whether the call raised. It does
not show **what** was filed, which passages were cited, or what the model
wrote. Those are in the adapter logs and in the outputs, and only the drivers
check one against the other. Every indicator on the per-run page says which
of the three it came from: agent traces, the stage check, or the driver. That
split is the reason the committed investigate sample under
`docs/samples/agent-traces-2026-10-08/` is kept with its stage check passing
and its driver failing: the spans said every call succeeded, and the content
check said the filed payload was not the reported one. Both were right.

## Objectives

`checks/agent_traces_slo.yaml` holds the service level objectives over
these indicators, and `checks/agent_traces_sli.py --aggregate --slo` holds a
set of runs to them. Per-run objectives are the contract indicators and must
hold on every run they can be measured on; the driver's pass rate is a rolling
rate over a window, the one objective with an error budget; latency objectives
are p95 ceilings per stage and end to end. `demos/agent_traces_baseline.sh`
renders the result as `runs/baseline.html`.

## Cost

`oa.usage.estimated_cost_usd` is the runner's estimate from its own per-model
price table and the token counts it records. Two caveats. The token counts
omit cache reads and writes, because the CLI's usage mapper drops the cache
fields, so the estimate is over uncached input. And the table in OA 1.6.2 has
no entry for `claude-sonnet-5-5`, so stages on that model carry no cost
attribute and the page shows zero for them. Estimate those from the token
counts and the published prices instead.
