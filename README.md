# Response Engineering

> You shifted left and fixed the pipeline. Production is still a person reading a dashboard at 3am. We engineer that layer.

Operations is a software problem. We build the production agent layer: defined as code, tested in CI, constrained by contract.

Built on [Open Agent Spec](https://github.com/prime-vector/open-agent-spec).

---

## Status

Early. Two of five agents written, mock adapters serving both tool surfaces. A live end to end run has not been recorded yet.

| Artefact | State |
| --- | --- |
| `SCENARIO.md` | Draft, needs review |
| `.agents/incident-commander.yaml` | Written, validates against OAS 1.5.1 |
| `.agents/telemetry-analyst.yaml` | Written, validates against OAS 1.5.1 |
| `interfaces/TELEMETRY.md` | Draft interface contract |
| `fixtures/composite-incident*.json` | Generated, two views (D+2 and D+15), cadence needs tuning against reference |
| `mock/adapter.py` | Written, smoke-tested against both fixture views |
| Change Correlator, Scribe, Comms | Not started |

## Layout

```
SCENARIO.md                        source of truth, read this first
PLAN.md                            milestones and definition of done
CLAUDE.md                          working rules for this repo
.agents/incident-commander.yaml    holds the hypothesis board
.agents/telemetry-analyst.yaml     detects recurrence in the problem feed
interfaces/TELEMETRY.md            platform-agnostic tool surface
fixtures/generate.py               synthetic fixture generator, two views
fixtures/composite-incident.json   generated, D+15 bridge view
fixtures/composite-incident.d2.json  generated, D+2 view for act one
mock/adapter.py                    mock MCP adapter, both surfaces, fixture-backed
```

## Run

```bash
pipx install open-agent-spec
oa validate --spec .agents/incident-commander.yaml
oa validate --spec .agents/telemetry-analyst.yaml

# the mock adapters, one terminal each, fixture-backed
python3 mock/adapter.py --surface telemetry                # 8422, D+15 bridge view
python3 mock/adapter.py --surface change_registry          # 8423

export ANTHROPIC_API_KEY=...

# act two: the bridge, run from evidence
oa run --spec .agents/incident-commander.yaml --task assess \
  --input "$(cat fixtures/composite-incident.json)" --quiet

# act one: restart the telemetry adapter on the D+2 view first
python3 mock/adapter.py --surface telemetry --fixture fixtures/composite-incident.d2.json
oa run --spec .agents/telemetry-analyst.yaml --task detect \
  --input "$(cat fixtures/composite-incident.d2.json)" --quiet
```

## Design position

**Three layers get conflated in incident management.** Notification and routing is solved: PagerDuty, Opsgenie. The record is solved: ServiceNow. The investigation, what is actually wrong and how we know it, is still entirely human, undocumented, and reconstructed from memory afterwards.

This is the third layer. It has no incumbent, which is not an accident: it needs reasoning rather than workflow.

**This is not alert correlation.** Correlation reduces noise. Against the scenario in `SCENARIO.md` it would have grouped fifteen days of identical problems into one tidy cluster and still told nobody what to do. Different job.

**ServiceNow is a destination, not a competitor.** The draft change record this produces flows into it. Submission is a human action, always.

**No vendor name appears inside a spec.** Telemetry and change history both sit behind interfaces. Swapping platforms changes one endpoint and nothing else. See `interfaces/TELEMETRY.md`.

## The contract that matters

The Incident Commander's output requires, per hypothesis: a confidence word, supporting evidence, and the single test that would falsify it. Convergence on a cause is blocked while deciding evidence is outstanding, and naming a third party on inferential evidence trips an attribution guard.

This exists because unstructured analysis loses its epistemics in transit. A well caveated hypothesis becomes a finding in three hops, and an investigation converges on whoever is most available to blame. A typed output cannot shed its own caveats when it changes hands.
