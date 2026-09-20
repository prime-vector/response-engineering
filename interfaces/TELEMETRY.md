# Telemetry and Change Interfaces

**Principle: no vendor name appears inside a spec.** Specs declare capability. Adapters implement it. Swapping Dynatrace for Datadog, Prometheus or an internal platform changes one endpoint and nothing else.

The seam is MCP. Each adapter is an MCP server exposing the tool surface below over JSON-RPC 2.0 across HTTP. OAS speaks MCP natively, so no SDK and no glue code sits between the spec and the platform.

Mock first. The mock is not a throwaway: it is the conformance reference, and any vendor adapter is correct when it satisfies the same contract against the same fixtures. The mock lives at `mock/adapter.py`, stdlib only, and serves whichever fixture view it is started with.

The mock binds 127.0.0.1, speaks plain HTTP and authenticates nobody, which is acceptable for a fixture-backed conformance reference and nothing else: any local process can call every tool on a running surface. A vendor adapter fronts real systems, so it authenticates its callers, and its refusals (the host surface's, the sink's) hold at its own layer rather than trusting the spec sandbox in front of it. A spec's sandbox constrains one agent; the adapter is what stands between the network and the platform.

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

## `host` surface

Port 8424 in development. Actuation, not evidence, and the only surface in this system that could change production state. It exists so the sandbox boundary is demonstrable rather than described: the Incident Commander's `mitigate` task binds it, no spec's sandbox allow list includes any of its tools, and the runner therefore blocks every call before dispatch. See `demos/governance.sh sandbox`.

Every call on this surface is a security control change, a service change or an irreversible action, so every call sits behind `authorisation_required: true` in any output that proposes it. There is no configuration in which an agent reaches these tools autonomously.

### `selinux.setenforce`

Request: `mode` (`enforcing` | `permissive`). Runtime-only: the boot configuration is untouched, so a permissive change silently reverts on reboot. That caveat belongs in any output that proposes the change.

### `audit.dispatcher_disable`

Deactivates the audit event dispatcher, stopping denial events from reaching analysis. Also stops the denial log being collectable, which in the composite scenario destroys the deciding evidence.

### `process.kill`

Request: `pid`. Terminates a process on the host.

The mock's handlers refuse all three calls even without a sandbox in front of them: the mock never mutates state. A vendor adapter for this surface must be gated behind human authorisation at its own layer as well; defence in depth is the design, not redundancy.

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

## `incident_record` surface, the sink

Port 8425 in development. Same treatment as the evidence surfaces: ServiceNow, Jira Service Management or a webhook sit behind it, and the Scribe is the only agent bound to it. Write-shaped but inert: every call produces a draft or an append, and the surface deliberately has no submit, approve or close call. Submission is a human action, always, so the capability an agent would need to bypass that is structurally absent rather than blocked.

### `record.create`

Creates an incident record and returns a `record_ref`. The record is created open; closing it is a human action.

### `record.update`

Appends to an existing record, e.g. the assembled timeline. Request: `record_ref`, `update`, both required. Cannot change record state.

An accepted mock update emits a receipt containing the record reference and a SHA-256 digest of `json.dumps(update, sort_keys=True).encode()`. The timeline driver checks its current attempt's receipts against the final output's reference and exact `{entries, gaps}` payload. A rejected call, a different payload or a previous attempt cannot satisfy this check. The mock acknowledges writes without persisting them; this receipt proves acceptance by the mock, not durable storage.

### `change.draft`

Lodges a draft change record and returns a `draft_ref` with `submitted: false`. A draft missing its `summary`, `risk`, `blast_radius`, `implementation_plan`, `backout_plan`, `validation_plan` or `authorisation_required` is refused, not quietly accepted: an incomplete change record is how caveats get lost in a record system, so the sink is the second fence behind the Scribe's output contract. Defence in depth is the design here too; a vendor adapter for this surface must apply the same refusals at its own layer.

---

## Conformance

An adapter is conformant when it satisfies both fixture views, `fixtures/composite-incident.json` and `fixtures/composite-incident.d1.json`, and returns the same agent decisions as the mock. Those fixtures are the test suite. The D+1 view matters as much as the bridge view: an adapter that invents data the view does not hold (a process listing nobody collected, a change query nobody ran) fails conformance even if the data looks plausible.

The sink is conformance-tested on its refusals rather than on fixtures: an `incident_record` adapter is conformant when it refuses an incomplete draft, refuses any submission-shaped argument, and exposes no call that submits, approves or closes. An adapter that quietly accepts what the mock refuses fails conformance even though every accepted call succeeds.
