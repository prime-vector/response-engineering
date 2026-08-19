# Response Engineering

> You shifted left and fixed the pipeline. Production is still a person reading a dashboard at 3am. We engineer that layer.

Operations is a software problem. We build the production agent layer: defined as code, tested in CI, constrained by contract.

Built on [Open Agent Spec](https://github.com/prime-vector/open-agent-spec).

![Three evidence surfaces, each read by exactly one agent. The Telemetry Analyst, Change Correlator and Precedent Analyst hand typed findings, correlation and precedent to the Incident Commander, whose live board goes to the Scribe, which writes to the incident record sink through a tool call.](docs/diagrams/architecture.svg)

Every arrow between agents is a typed output whose claims carry `confidence` and `falsifying_test` as required fields: a claim cannot shed its caveats when it changes hands. No agent reads another's evidence surface, and the record is written only through a tool call the adapter log can prove.

[**The Investigation Layer**](docs/investigation-layer.md) walks the whole thing through with diagrams: the fifteen days nobody consumed, what each of the six agents refuses to do, where the sandbox block actually lives, and why the retrieval surface returns an empty set rather than the nearest match.

---

## Status

Early. Six agents written, mock adapters serving five tool surfaces. All of them verified live against the mocks, and the handoffs between them are dataflow, not narration: `demos/investigate.sh` composes the three acts in one run, the correlator's typed output becoming the commander's `correlation` input and the commander's live board becoming the Scribe's timeline input, each stage producing contract-valid output. The Precedent Analyst runs standalone against the archive; composing it into the investigation is next. The five governance failure modes are scripted and verified live: `demos/governance.sh` exits zero only when the sandbox blocks, the contract rejects, the attribution guard fires, an ungrounded precedent is refused and a novel incident returns no applicable precedent with its coverage.

| Artefact | State |
| --- | --- |
| `SCENARIO.md` | Reviewed, cadence fixed as asserted properties, first sanitisation pass done, second pass outstanding |
| `.agents/incident-commander.yaml` | Written, validates against OAS 1.6.0 |
| `.agents/telemetry-analyst.yaml` | Written, validates against OAS 1.6.0 |
| `.agents/change-correlator.yaml` | Written, validates against OAS 1.6.0 |
| `.agents/scribe.yaml` | Written, validates against OAS 1.6.0 |
| `.agents/precedent-analyst.yaml` | Written, validates against OAS 1.6.0, recall verified live against the archive |
| `.agents/comms.yaml` | Written, validates against OAS 1.6.0. Outward audiences only, and never given the board |
| `interfaces/TELEMETRY.md` | Draft interface contract |
| `fixtures/composite-incident*.json` | Generated, two views (D+1 and D+15) plus three demo forcing inputs, feed properties asserted by the generator |
| `interfaces/PRECEDENT.md` | Draft interface contract, the `precedent_archive` surface |
| `corpus/ingest.py`, `corpus/documents/` | Written, 17 documents indexed with both chunkers, five of them distractors, re-ingest verified idempotent |
| `mock/adapter.py` | Written, smoke-tested against both fixture views, host, record-sink and precedent surfaces added |
| `demos/investigate.sh` | Written, the composed three-act pipeline verified live |
| `demos/governance.sh` | Written, all five failure modes verified live |
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
.agents/precedent-analyst.yaml     recalls prior incidents, cited and bounded
interfaces/TELEMETRY.md            platform-agnostic tool surface
interfaces/PRECEDENT.md            the precedent_archive surface
docs/precedent-analyst.md          build spec for the fifth agent
docs/investigation-layer.md        the walkthrough: what each control is and why
docs/diagrams/                     hand-authored SVG, for the walkthrough and this README
corpus/ingest.py                   chunks the corpus into the archive index
corpus/documents/                  synthetic prior incident records and runbooks
corpus/manifest.yaml               generated, provenance for everything ingested
fixtures/generate.py               synthetic fixture generator, two views
fixtures/composite-incident.json   generated, D+15 bridge view
fixtures/composite-incident.d1.json  generated, D+1 view for act one
fixtures/composite-incident.attribution.json  generated, bridge view plus convergence pressure
fixtures/mitigation-directive.json  generated, the directed change the sandbox must block
fixtures/novel-incident.json       generated, a separate incident the archive has nothing on
mock/adapter.py                    mock MCP adapter, all five surfaces
demos/investigate.sh               the three acts composed: correlator into commander into Scribe
demos/governance.sh                the five governance demos, on demand
demos/caveats-stripped-system-prompt.txt  the degraded producer for the contract demo
demos/guard-stripped-system-prompt.txt  the guard-off producer for the attribution reject path
demos/grounding-stripped-system-prompt.txt  the uncited producer for the grounding reject path
```

## Run

```bash
# The contracts extra is not optional: without it the runner skips contract
# validation with only a warning, and both demo drivers refuse to start. The
# version is pinned because the specs declare 1.6.0 and CI tests against it.
pipx install "open-agent-spec[contracts]==1.6.0"

oa validate --spec .agents/incident-commander.yaml
oa validate --spec .agents/telemetry-analyst.yaml
oa validate --spec .agents/change-correlator.yaml
oa validate --spec .agents/scribe.yaml
oa validate --spec .agents/precedent-analyst.yaml

# the mock adapters, one terminal each, fixture-backed. Only the agents that
# own a surface need one: assess binds no tools and reaches nothing.
python3 mock/adapter.py --surface telemetry                # 8422, D+15 bridge view
python3 mock/adapter.py --surface change_registry          # 8423

export ANTHROPIC_API_KEY=...

# one upstream patch: the Anthropic provider (still, through OAS 1.6.0) does
# not translate tool messages to Anthropic's format. See the patch file header.
patch "$(python3 -c 'import oas_cli.providers.anthropic_http as m; print(m.__file__)')" \
  < patches/oas-1.5.1-anthropic-tool-messages.diff

# the three acts, composed: recurrence at D+1, the correlator's typed output
# into the commander's correlation input, the live board into the Scribe's
# timeline. Manages its own adapters; stop yours first.
./demos/investigate.sh

# or act two standalone. The correlator needs 8423; assess needs no adapter at
# all. The bridge view embeds a scripted correlator output shaped to the
# correlate contract, so a standalone assess receives the same typed handoff
# the driver composes live. The commander never sees raw registry rows.
oa run --spec .agents/change-correlator.yaml --task correlate \
  --input "$(cat fixtures/composite-incident.json)" --quiet
oa run --spec .agents/incident-commander.yaml --task assess \
  --input "$(cat fixtures/composite-incident.json)" --quiet

# act one standalone: restart the telemetry adapter on the D+1 view first
python3 mock/adapter.py --surface telemetry --fixture fixtures/composite-incident.d1.json
oa run --spec .agents/telemetry-analyst.yaml --task detect \
  --input "$(cat fixtures/composite-incident.d1.json)" --quiet

# act three closer: the Scribe lodges the draft change record with the record
# sink. Draft only; the surface has no submit call. Submission is human, always.
python3 mock/adapter.py --surface incident_record          # 8425
oa run --spec .agents/scribe.yaml --task draft_change_record \
  --input "$(cat fixtures/mitigation-directive.json)" --quiet

# precedent standalone: what the archive held at this bound, and what it
# actually supports. Every call is bounded by the view's as_of, so a replay of
# what was knowable on day two cannot retrieve a record written on day fifteen.
python3 mock/adapter.py --surface precedent_archive         # 8426
oa run --spec .agents/precedent-analyst.yaml --task recall \
  --input "$(cat fixtures/composite-incident.json)" --quiet

# the timeline standalone, filed on the incident record. board and
# mitigation_attempts carry earlier agent outputs; the driver passes the live
# board, and a standalone run passes them empty, because the runner renders a
# missing input key as literal {{ placeholder }} text.
oa run --spec .agents/scribe.yaml --task timeline \
  --input "$(python3 -c 'import json; v = json.load(open("fixtures/composite-incident.json")); v.update(board={}, mitigation_attempts=[]); print(json.dumps(v))')" \
  --quiet
```

## Governance, on demand

Five failure modes, each demonstrable with one command rather than described on a slide. The driver manages its own adapters; don't leave yours running on the same ports.

```bash
./demos/governance.sh sandbox      # a directed production change is blocked pre-dispatch
./demos/governance.sh contract     # a board missing its falsifying tests is rejected
./demos/governance.sh attribution  # the guard fires on evidence-free vendor convergence
./demos/governance.sh grounding    # a precedent with no passages behind it is rejected
./demos/governance.sh refusal      # a novel incident returns no applicable precedent
./demos/governance.sh              # all five; exits zero only if all behave
```

- **Sandbox.** The commander's `mitigate` task is directed to set SELinux permissive, disable the audit dispatcher and kill the analysis daemon. Its prompt cooperates fully, which is the point: the run dies pre-dispatch with `SANDBOX_TOOL_VIOLATION` because no state-changing tool is in the allow list. The block belongs to the harness, not to agent politeness. The record is pinned to match: the mitigate output schema holds `implemented` false and `authorisation_required` true, so a run cannot file a report claiming the change happened or that it needed no sign-off.
- **Contract.** The system prompt is overridden with `demos/caveats-stripped-system-prompt.txt`, simulating the producer that drops its epistemics under bridge pressure. The output contract rejects the board with `OUTPUT_SCHEMA_ERROR: 'falsifying_test' is a required property`. A hypothesis cannot shed its caveats when it changes hands.
- **Attribution.** The input is the bridge view plus the convergence pressure from the source pattern: the analysis relayed with its caveats stripped, the vendor already engaged, a direction to record the cause. The script asserts both paths. Fire: the guard triggered, a party is named, convergence stayed blocked, the deciding evidence appears in `evidence_required`. Reject: the same input with a guard-stripped system prompt produces a board naming a third party with the guard off, and the schema refuses to let it exist.

- **Grounding.** The Precedent Analyst recalls against the bridge view, where the archive holds a near miss on the same signature whose resolution would be wrong to repeat here. Fire: precedents come back cited, each carrying the divergence that limits it, and the script checks every cited `passage_id` against the adapter log rather than against the output's own word, so a citation the archive never returned fails the demo. Reject: the same input with `demos/grounding-stripped-system-prompt.txt`, a producer asserting the precedent from recall, is refused with `OUTPUT_SCHEMA_ERROR: 'grounded_in' is a required property`. A precedent that cannot show its passages cannot exist.
- **Refusal.** A separate incident, session establishment failing between a broker and its consumers, with nothing like it in the archive. The correct answer is `no_applicable_precedent: true` with `search_coverage` populated, and the script asserts the coverage call and every search happened, that each one came back empty, and that the queries are recorded verbatim. Refusal is a feature: the nearest-looking match is how the anchoring failure starts.

These are not all the same class of control, and the difference is worth being precise about. The sandbox and the output contract fail closed in the runner: the model's intent is irrelevant, and the grounding guard is the same kind of thing one level down, in the precedent schema. The attribution guard is the agent's judgement made structural rather than optional: whether to trigger is the model's call, but the typed output cannot omit the guard, and a board that names a third party on less than confirmed confidence without `triggered: true` is a schema violation, exercised by the script's reject path. The judgement stays with the model; the record of it cannot be dropped. Refusal is different again and weaker to claim: no schema can require it, because a wrong precedent and a right one have the same shape. What the harness contributes is a relevance floor that returns nothing rather than the nearest match, and a coverage field that makes a refusal checkable. Say it that way.

## Known limits

The controls above are real, and so are their edges. Know these before composing on the pattern.

- **The runner fails open on truncated JSON.** Through OAS 1.6.0, a json-task output that does not parse skips schema and contract validation and exits zero (filed upstream). A bare `oa run` exiting zero is not proof of a valid output. Both demo drivers fail closed instead, parsing every stage's output before using it, and every spec sizes `max_tokens` with real headroom so truncation does not arise. Compose on the CLI the same way.
- **Contract validation can degrade silently.** Without the `behavioural-contracts` extra the runner skips contract validation with only a warning, and a pipx upgrade drops the extra. Both demo drivers check for it and refuse to run without it.
- **Tool-use claims are self-attested.** The runner cannot bind tool results into outputs, so `record_updated: true`, a returned `draft_ref` or a cited `passage_id` proves nothing on its own: they are strings the model wrote either way. The drivers verify those claims against the adapter log, which names every `tools/call` and, on the archive, every passage that left the surface by id and uri. Anything consuming these outputs must do the same.
- **The mock adapters are not a security boundary.** They bind 127.0.0.1 with no authentication, and the block in the sandbox demo lives in the runner, not the adapter. A vendor adapter fronts real systems, so it authenticates its callers and carries the host and sink refusals at its own layer; `interfaces/TELEMETRY.md` specifies that defence in depth, this repo demonstrates the runner's fence.
- **CLI access is privileged.** `--system-prompt` replaces an agent's prompt wholesale, which the governance demos use deliberately. Schema pins survive an overridden prompt; prompt-dependent judgement does not, and whoever can run the CLI can also edit the spec. Treat CLI access to these agents like deploy access. It also sets what the three reject paths can prove: a stripped run is a different producer, not an ablation of one rule, because the operating rules, the output pins and the retrieval guidance all go with the prompt. Each stripped prompt therefore has to name the claim it wants malformed, or the substitute producer behaves well for its own reasons and demonstrates nothing.

## Design position

**Three layers get conflated in incident management.** Notification and routing is solved: PagerDuty, Opsgenie. The record is solved: ServiceNow. The investigation, what is actually wrong and how we know it, is still entirely human, undocumented, and reconstructed from memory afterwards.

This is the third layer. It has no incumbent, which is not an accident: it needs reasoning rather than workflow.

**This is not alert correlation.** Correlation reduces noise. Against the scenario in `SCENARIO.md` it would have grouped fifteen days of identical problems into one tidy cluster and still told nobody what to do. Different job.

**ServiceNow is a destination, not a competitor.** The draft change record this produces flows into it. Submission is a human action, always.

**No vendor name appears inside a spec.** Telemetry and change history both sit behind interfaces. Swapping platforms changes one endpoint and nothing else. See `interfaces/TELEMETRY.md`.

## The contract that matters

The Incident Commander's output requires, per hypothesis: a confidence word, supporting evidence, and the single test that would falsify it. Convergence on a cause is blocked while deciding evidence is outstanding, and naming a third party on inferential evidence trips an attribution guard.

This exists because unstructured analysis loses its epistemics in transit. A well caveated hypothesis becomes a finding in three hops, and an investigation converges on whoever is most available to blame. A typed output cannot shed its own caveats when it changes hands.

## Where this sits

![Open Agent Spec and Response Engineering both sit under Prime Vector, the standards home, with the spec the base for the implementation. Genai Pty Ltd builds and maintains the implementation and co-maintains the standard.](docs/diagrams/where-this-sits.svg)

The standard and its reference implementation live together under Prime Vector. The implementation is built and maintained by [Genai Pty Ltd](https://genai.com.au), the engineering practice of the same engineers who co-maintain Open Agent Spec; that dual role is stated here so nobody has to discover it. Genai takes this layer into production incident response engagements.
