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
**Done when:** all five specs validate against OAS 1.5.x and the role boundaries hold without overlap.

- [x] Incident Commander, holds the hypothesis board
- [x] Telemetry Analyst, consumes the problem feed and detects recurrence
- [ ] Change Correlator, correlates change and package history against onset
- [ ] Scribe, produces the timeline and the draft change record
- [ ] Comms, produces the stakeholder update

Cost Guardrail is deliberately excluded. It does not fit this scenario and forcing it in would weaken the demo.

### M3: Runnable
**Done when:** `oa run` executes the pipeline end to end against the fixture with no live platform.

- [x] Mock MCP adapter serving the `telemetry` surface on 8422
- [x] Mock MCP adapter serving the `change_registry` surface on 8423
- [ ] `depends_on` chain wired commander to brief
- [ ] Deterministic enough to record without retakes

### M4: Governance visible
**Done when:** all three failure modes are demonstrable on demand, not described.

- [ ] Sandbox blocks a production state change and reports why
- [ ] Behavioural contract rejects an output missing its falsifying test
- [ ] Attribution guard fires on third-party convergence without evidence

This milestone is the product. If it is not visible on screen, this is just another AI incident tool.

### M5: Public
**Done when:** the repo is public, the video is recorded, and the site points at both.

- [ ] Sanitisation review, second pass, by someone other than the author
- [ ] Repo moved to the org, once the brand decision is made
- [ ] Four minute walkthrough recorded
- [ ] README readable by someone with no context

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
| Whether act one is a separate invocation or the first turn of the pipeline | Open. Decide during M3. |
| Whether the mock adapter becomes its own package | Defer until it exists. |

---

## Notes

Commercial objectives, pricing and pipeline are tracked outside this repository and must not be added to it.
