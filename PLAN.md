# Plan

## What this is

A reference implementation of an agent-run incident response layer, built on [Open Agent Spec](https://github.com/prime-vector/open-agent-spec). It exists to demonstrate that production investigation can be defined as code, tested in CI and constrained by contract, rather than performed from memory on a bridge call at 3am.

It is a demonstration, not a platform. Success is a four minute video and a repo that a sceptical SRE can read and believe.

---

## Milestones

### M1: Scenario locked
**Done when:** `SCENARIO.md` is reviewed, the fixture cadence matches the reference chart, and no source material has entered the repo.

- [x] Composite scenario drafted
- [x] Fixture generator producing 13 problems across 15 days
- [ ] Cadence tuned against reference chart
- [ ] Sanitisation review

### M2: Specs written
**Done when:** all five specs validate against OAS 1.6.0 and the role boundaries hold without overlap.

- [x] Incident Commander, holds the hypothesis board
- [x] Telemetry Analyst, consumes the problem feed and detects recurrence
- [x] Change Correlator, correlates change and package history against onset
- [x] Scribe, produces the timeline and the draft change record
- [ ] Comms, produces the stakeholder update

Cost Guardrail is deliberately excluded. It does not fit this scenario and forcing it in would weaken the demo.

### M3: Runnable
**Done when:** `oa run` executes the pipeline end to end against the fixture with no live platform.

- [x] Mock MCP adapter serving the `telemetry` surface on 8422
- [x] Mock MCP adapter serving the `change_registry` surface on 8423
- [x] `depends_on` chain wired commander to brief
- [x] Pipeline driver composing the acts as dataflow: correlator output into the commander's `correlation` input, the live board into the Scribe's timeline (`demos/investigate.sh`)
- [ ] Deterministic enough to record without retakes

### M4: Governance visible
**Done when:** all three failure modes are demonstrable on demand, not described.

- [x] Sandbox blocks a production state change and reports why
- [x] Output contract rejects a board missing its falsifying test
- [x] Attribution guard fires on third-party convergence without evidence

All three run from `demos/governance.sh`, which exits zero only when every failure mode behaves. The sandbox demo's `mitigate` prompt cooperates with the directed change deliberately: what blocks it is the allow list, so the demo proves the boundary belongs to the harness rather than to prompt wording.

Two of the three fail closed in the runner. The attribution guard is a different class of control: the agent's judgement made structural, with a schema backstop that rejects any board naming a third party below confirmed confidence without the guard triggered. The demo exercises both paths, the guard firing live and the guard-off board being rejected, but the firing itself remains the model's judgement. Say it that way; do not sell it as a peer of the sandbox.

This milestone proves the boundaries only. The narrated act three, blast radius stated, escalation for authorisation, Scribe's draft change record, is demo assembly plus Scribe's milestone and is not claimed here.

This milestone is the product. If it is not visible on screen, this is just another AI incident tool.

### M5: Public
**Done when:** the repo is public, the video is recorded, and the site points at both.

- [ ] Sanitisation review, second pass, by someone other than the author
- [ ] Repo moved to the org, once the brand decision is made
- [ ] Four minute walkthrough recorded
- [ ] README readable by someone with no context

### M6: Precedent Analyst

Full spec: `docs/precedent-analyst.md`

The fifth agent. Owns a retrieval surface over prior incident records and runbook documentation, hands the commander typed precedent alongside findings and correlation. Headline risk is the confident wrong precedent, so refusal and divergence are contract requirements, not tuning targets.

- [x] `interfaces/PRECEDENT.md` written, no implementation named
- [x] Adapter serving `precedent_archive`, cited passages, corpus manifest populated
- [ ] `.agents/precedent-analyst.yaml` validates against OAS 1.6.0, runs standalone
- [ ] `no_applicable_precedent` path and grounding guard both exercised
- [ ] `demos/governance.sh grounding` passes fire and reject
- [ ] Evals baseline recorded
- [ ] Measured improvement documented with before and after
- [ ] `investigate.sh` composes four acts, precedent enters the board as supporting but never deciding evidence

**Done when:** a board cites precedent by `passage_id`, convergence still blocks on outstanding deciding evidence, and the README carries a results table the runner can regenerate.

#### Where this is up to

Phases 0 and 1 are merged. The surface is live and honest enough to consume: `python3 mock/adapter.py --surface precedent_archive` on 8426, 12 documents, 59 heading-aware passages, `corpus/eval.py` green on both chunkers, CI running the lot.

Phase 2 is the spec, `.agents/precedent-analyst.yaml`, task `recall`. What the surface work has already decided for it:

- **`as_of` is a required input field.** Both `precedent_search` and `coverage_describe` require `before`, and the runner substitutes only from keys present in the input, so a missing `as_of` reaches the model as literal template text and the run degrades silently.
- **The prompt passes the signature type, never the entity id.** `host.memory.exhaustion`, not `host.memory.exhaustion:intg-prod-a1`. Identity is not a similarity feature, and the archive holds records about this host.
- **The mitigate-style wording covers both calls.** "Do not report `no_applicable_precedent` until you have called `coverage_describe`" as well as the search, or the agent self-attests a refusal it never checked. Verify from the adapter log, never from the output.
- **`DRAFT-2601` is visible at the bridge bound and that is correct.** It was written by then. A draft working note is not evidence, so the spec has to handle it through `record_status` and the attribution guard rather than through the time bound. Do not move its date.
- **The near miss is `INC-2411`.** Same signature, resolution that would be actively wrong to repeat here. It is what `divergence` exists to catch.

Live `oa run` needs an API key and the `patches/` provider patch. `oa validate` needs neither.

---

## Definition of done for the demo

Three acts, four minutes, in this order:

1. **Day two.** Recurrence detected in the problem feed, standing condition attached. The predictive half.
2. **Day fifteen.** Bridge opens with change correlation already on the board. Hypotheses carry confidence and falsifying tests. Attribution guard fires.
3. **Mitigation.** Sandbox blocks the security control change, states blast radius, escalates for authorisation. Scribe drafts the change record.

**It closes on a blocked state, not a resolution.** Hypothesis unresolved, deciding evidence outstanding, the single command that would settle it, and what each outcome rules in or out. This is not a limitation to apologise for. It is the most credible thing in the demo.

---

## Non-goals

- Building an orchestrator or agent runtime. OAS plus external orchestration is sufficient.
- Competing with APM vendors on automated root cause analysis.
- Alert correlation. Correlation reduces noise. This investigates.
- Autonomous remediation. Every production state change requires human authorisation, by design and permanently.
- Generality. Incident investigation only. No adjacent use cases until this one is finished.

---

## Open decisions

| Decision | Status |
| --- | --- |
| Brand and org the repo lands under | Open. Blocks M5, nothing earlier. |
| Whether act one is a separate invocation or the first turn of the pipeline | Resolved during M3: a separate invocation of the Telemetry Analyst against the D+1 view. |
| Whether the mock adapter becomes its own package | The mock exists in-repo. Repackage only if a second consumer appears. |
| Who owns the change registry | Resolved: the Change Correlator, exclusively. The commander consumes the correlator's typed output through its `correlation` input, never raw registry rows, and holds telemetry only. |
| Comms boundary against the commander's `brief` | Open. Blocks the Comms spec, nothing earlier. `brief` already renders the board for bridge, incident manager and executive audiences; either it narrows to investigation-internal audiences, or Comms owns external stakeholders only. Leaning: Comms owns outward stakeholder updates (business impact, expectations, no board detail), `brief` keeps the three internal audiences. |

---

## Notes

Commercial objectives, pricing and pipeline are tracked outside this repository and must not be added to it.
