# Telemetry and Change Interfaces

**Principle: no vendor name appears inside a spec.** Specs declare capability. Adapters implement it. Swapping Dynatrace for Datadog, Prometheus or an internal platform changes one endpoint and nothing else.

The seam is MCP. Each adapter is an MCP server exposing the tool surface below over JSON-RPC 2.0 across HTTP. OAS speaks MCP natively, so no SDK and no glue code sits between the spec and the platform.

Mock first. The mock is not a throwaway: it is the conformance reference, and any vendor adapter is correct when it satisfies the same contract against the same fixtures. The mock lives at `mock/adapter.py`, stdlib only, and serves whichever fixture view it is started with.

Naming: this document uses dotted call names (`problems.list`) for readability. The MCP tool names use underscores (`problems_list`) because model-facing tool name constraints do not allow dots.

---

## `telemetry` surface

Port 8422 in development.

### `problems.list`

The most important call in the whole system, and the one most platforms bury. Returns detected problems for an entity over a window, **including auto-closed ones and including whether a human ever acknowledged them**.

The acknowledgement field is what makes fifteen days of unconsumed detection visible. Most vendor APIs expose it. Almost no workflow reads it.

Request: `entity_id`, `from`, `to`, `include_closed`.

Response, per problem: `id`, `title`, `signature` (stable across recurrences, this is what makes repetition detectable), `severity`, `opened_at`, `closed_at`, `auto_closed`, `acknowledged_by` (null means nobody looked), `affected_entities`, `root_cause_claimed` (the platform's own attribution, treated as a signal, never as evidence). Plus `total` and `unacknowledged` counts.

### `metrics.query`

Request: `entity_id`, `metric` (one of `memory.used`, `memory.total`, `cpu.utilisation`, `page_faults`, `swap.used`), `from`, `to`, `resolution`.

Response: `series` of `{t, v}` plus `unit`.

### `entity.describe`

Capacity, not utilisation. This is where standing conditions come from. Returns `capacity` (cores, memory bytes, swap bytes), `os` (family, version, security module, mode), `uptime_seconds`, `environment`, and `non_prod_equivalent` with a `build_parity` boolean.

`build_parity: false` is deliberately a first-class field. Whether non-prod can validate prod is an input to the investigation, not a discovery made two hours in.

### `processes.top`

Request: `entity_id`, `at`, `order_by`, `limit`. Returns per-process `pid`, `user`, `command`, `cpu_percent`, `memory_bytes`, `started_at`.

---

## `change_registry` surface

Port 8423 in development. Read only, permanently. Nothing in this system writes to a change registry without human authorisation.

### `changes.list`

Returns change records: `id`, `type`, `summary`, `implemented_at`, `risk`, `outcome`, `implementer_role`.

### `packages.installed`

The single cheapest correlation available in any Linux incident, and routinely the last thing anyone runs. Returns `name`, `version`, `installed_at`, `source`.

> Agents that self-update outside the package manager will not appear here with a current timestamp. Any adapter must set `self_updating_agents_not_reflected: true` on the response so the model does not treat absence from this list as absence of change. Getting this wrong produces exactly the false confidence the contract exists to prevent.

### `deployments.list`

Application deployment events where a pipeline is the source of truth rather than the OS.

---

## Adapter mapping

| Interface call | Dynatrace | Datadog | Prometheus stack |
| --- | --- | --- | --- |
| `problems.list` | Problems API v2 | Events, monitor history | Alertmanager history |
| `metrics.query` | Metrics API v2, `builtin:host.*` | Metrics query | PromQL range query |
| `entity.describe` | Entities API v2 | Host tags, infrastructure | Node exporter, plus CMDB |
| `processes.top` | Process group instances | Live processes | Process exporter |
| `changes.list` | n/a, ITSM adapter | n/a, ITSM adapter | n/a, ITSM adapter |
| `packages.installed` | n/a, host adapter | n/a, host adapter | n/a, host adapter |

Two of these have no telemetry vendor behind them, which is the point. Change history lives in the ITSM system and the host, and it is the correlation nobody automates.

---

## Sink side

Same treatment. ServiceNow, Jira Service Management or a webhook sit behind one `incident_record` surface: `record.create`, `record.update`, `change.draft`. `change.draft` produces a draft only. Submission is a human action, always.

---

## Conformance

An adapter is conformant when it satisfies both fixture views, `fixtures/composite-incident.json` and `fixtures/composite-incident.d1.json`, and returns the same agent decisions as the mock. Those fixtures are the test suite. The D+1 view matters as much as the bridge view: an adapter that invents data the view does not hold (a process listing nobody collected, a change query nobody ran) fails conformance even if the data looks plausible.
