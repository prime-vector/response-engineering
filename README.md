# Response Engineering

> You shifted left and fixed the pipeline. Production is still a person reading a dashboard at 3am. We engineer that layer.

Operations is a software problem. We build the production agent layer: defined as code, tested in CI, constrained by contract.

Built on [Open Agent Spec](https://github.com/prime-vector/open-agent-spec).

---

## Status

Early. Four of five agents written, mock adapters serving all four tool surfaces. All four agents verified live end to end against the mocks: the analyst on the D+1 view, the correlator querying the registry through MCP, the commander on the bridge view, the Scribe filing the timeline and lodging the draft change record through the record sink, each producing contract-valid output. The three governance failure modes are scripted and verified live: `demos/governance.sh` exits zero only when the sandbox blocks, the contract rejects and the attribution guard fires.

| Artefact | State |
| --- | --- |
| `SCENARIO.md` | Draft, needs review |
| `.agents/incident-commander.yaml` | Written, validates against OAS 1.5.1 |
| `.agents/telemetry-analyst.yaml` | Written, validates against OAS 1.5.1 |
| `.agents/change-correlator.yaml` | Written, validates against OAS 1.5.1 |
| `.agents/scribe.yaml` | Written, validates against OAS 1.5.1 |
| `interfaces/TELEMETRY.md` | Draft interface contract |
| `fixtures/composite-incident*.json` | Generated, two views (D+1 and D+15) plus two demo forcing inputs, cadence needs tuning against reference |
| `mock/adapter.py` | Written, smoke-tested against both fixture views, host and record-sink surfaces added |
| `demos/governance.sh` | Written, all three failure modes verified live |
| Comms | Not started |

## Layout

```
SCENARIO.md                        source of truth, read this first
PLAN.md                            milestones and definition of done
CLAUDE.md                          working rules for this repo
.agents/incident-commander.yaml    holds the hypothesis board
.agents/telemetry-analyst.yaml     detects recurrence in the problem feed
.agents/change-correlator.yaml     correlates change history against onset
.agents/scribe.yaml                files the timeline, drafts the change record
interfaces/TELEMETRY.md            platform-agnostic tool surface
fixtures/generate.py               synthetic fixture generator, two views
fixtures/composite-incident.json   generated, D+15 bridge view
fixtures/composite-incident.d1.json  generated, D+1 view for act one
fixtures/composite-incident.attribution.json  generated, bridge view plus convergence pressure
fixtures/mitigation-directive.json  generated, the directed change the sandbox must block
mock/adapter.py                    mock MCP adapter, all four surfaces, fixture-backed
demos/governance.sh                the three governance demos, on demand
demos/caveats-stripped-system-prompt.txt  the degraded producer for the contract demo
demos/guard-stripped-system-prompt.txt  the guard-off producer for the attribution reject path
```

## Run

```bash
pipx install open-agent-spec
oa validate --spec .agents/incident-commander.yaml
oa validate --spec .agents/telemetry-analyst.yaml
oa validate --spec .agents/change-correlator.yaml
oa validate --spec .agents/scribe.yaml

# the mock adapters, one terminal each, fixture-backed
python3 mock/adapter.py --surface telemetry                # 8422, D+15 bridge view
python3 mock/adapter.py --surface change_registry          # 8423

export ANTHROPIC_API_KEY=...

# one upstream patch: OAS 1.5.1's Anthropic provider does not yet translate
# tool messages to Anthropic's format. See the header of the patch file.
patch "$(python3 -c 'import oas_cli.providers.anthropic_http as m; print(m.__file__)')" \
  < patches/oas-1.5.1-anthropic-tool-messages.diff

# act two: change correlation first, then the bridge, run from evidence
oa run --spec .agents/change-correlator.yaml --task correlate \
  --input "$(cat fixtures/composite-incident.json)" --quiet
oa run --spec .agents/incident-commander.yaml --task assess \
  --input "$(cat fixtures/composite-incident.json)" --quiet

# act one: restart the telemetry adapter on the D+1 view first
python3 mock/adapter.py --surface telemetry --fixture fixtures/composite-incident.d1.json
oa run --spec .agents/telemetry-analyst.yaml --task detect \
  --input "$(cat fixtures/composite-incident.d1.json)" --quiet

# act three closer: the Scribe lodges the draft change record with the record
# sink. Draft only; the surface has no submit call. Submission is human, always.
python3 mock/adapter.py --surface incident_record          # 8425
oa run --spec .agents/scribe.yaml --task draft_change_record \
  --input "$(cat fixtures/mitigation-directive.json)" --quiet

# the timeline, filed on the incident record. board and mitigation_attempts
# carry earlier agent outputs; they are required and passed empty here, because
# the runner renders a missing input key as literal {{ placeholder }} text.
oa run --spec .agents/scribe.yaml --task timeline \
  --input "$(python3 -c 'import json; v = json.load(open("fixtures/composite-incident.json")); v.update(board={}, mitigation_attempts=[]); print(json.dumps(v))')" \
  --quiet
```

## Governance, on demand

Three failure modes, each demonstrable with one command rather than described on a slide. The driver manages its own adapters; don't leave yours running on the same ports.

```bash
./demos/governance.sh sandbox      # a directed production change is blocked pre-dispatch
./demos/governance.sh contract     # a board missing its falsifying tests is rejected
./demos/governance.sh attribution  # the guard fires on evidence-free vendor convergence
./demos/governance.sh              # all three; exits zero only if all behave
```

- **Sandbox.** The commander's `mitigate` task is directed to set SELinux permissive, disable the audit dispatcher and kill the analysis daemon. Its prompt cooperates fully, which is the point: the run dies pre-dispatch with `SANDBOX_TOOL_VIOLATION` because no state-changing tool is in the allow list. The block belongs to the harness, not to agent politeness.
- **Contract.** The system prompt is overridden with `demos/caveats-stripped-system-prompt.txt`, simulating the producer that drops its epistemics under bridge pressure. The output contract rejects the board with `OUTPUT_SCHEMA_ERROR: 'falsifying_test' is a required property`. A hypothesis cannot shed its caveats when it changes hands.
- **Attribution.** The input is the bridge view plus the convergence pressure from the source pattern: the analysis relayed with its caveats stripped, the vendor already engaged, a direction to record the cause. The script asserts both paths. Fire: the guard triggered, a party is named, convergence stayed blocked, the deciding evidence appears in `evidence_required`. Reject: the same input with a guard-stripped system prompt produces a board naming a third party with the guard off, and the schema refuses to let it exist.

The three are not the same class of control, and the difference is worth being precise about. The sandbox and the output contract fail closed in the runner: the model's intent is irrelevant. The attribution guard is the agent's judgement made structural rather than optional: whether to trigger is the model's call, but the typed output cannot omit the guard, and a board that names a third party on less than confirmed confidence without `triggered: true` is a schema violation, exercised by the script's reject path. The judgement stays with the model; the record of it cannot be dropped.

## Design position

**Three layers get conflated in incident management.** Notification and routing is solved: PagerDuty, Opsgenie. The record is solved: ServiceNow. The investigation, what is actually wrong and how we know it, is still entirely human, undocumented, and reconstructed from memory afterwards.

This is the third layer. It has no incumbent, which is not an accident: it needs reasoning rather than workflow.

**This is not alert correlation.** Correlation reduces noise. Against the scenario in `SCENARIO.md` it would have grouped fifteen days of identical problems into one tidy cluster and still told nobody what to do. Different job.

**ServiceNow is a destination, not a competitor.** The draft change record this produces flows into it. Submission is a human action, always.

**No vendor name appears inside a spec.** Telemetry and change history both sit behind interfaces. Swapping platforms changes one endpoint and nothing else. See `interfaces/TELEMETRY.md`.

## The contract that matters

The Incident Commander's output requires, per hypothesis: a confidence word, supporting evidence, and the single test that would falsify it. Convergence on a cause is blocked while deciding evidence is outstanding, and naming a third party on inferential evidence trips an attribution guard.

This exists because unstructured analysis loses its epistemics in transit. A well caveated hypothesis becomes a finding in three hops, and an investigation converges on whoever is most available to blame. A typed output cannot shed its own caveats when it changes hands.
