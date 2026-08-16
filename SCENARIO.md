# Composite Scenario: Silent Degradation on a Batch Integration Host

**Status:** Composite. Not a client incident.
**Purpose:** Single source of truth for the Response Engineering demo. Every spec, fixture, chart and voiceover derives from this file. If something is not in here, it does not appear in the demo.

---

## 1. What this is, and what it is not

This scenario is assembled from a pattern observed repeatedly across enterprise engagements. It is not a reconstruction of any single incident, and it is not attributable to any client. The product, the host names, the dates, the numbers and the vendors are invented. What is preserved is the **shape**, because the shape is what recurs:

1. A standing resource condition nobody treats as a risk
2. A new agent deployed weeks before onset, unremarkable at the time
3. An observability platform raising the same problem daily into an empty room
4. The newest tool blamed first, because it is the newest
5. Non-production that cannot validate production
6. Resolution by suppression, with the cause never established

### Sanitisation rules (non-negotiable)

These must never appear in any artefact, public or private, derived from this work:

- Real host names, incident numbers, ticket references or bridge participants
- Real client, tenant, subscription, resource group or network names
- Named third-party products in a causal role. Vendors appear only as generic categories: *the observability platform*, *the endpoint compliance agent*, *the integration service*
- Any screenshot from a real console, including cropped
- Any statement that a named product caused a failure. In the source pattern the cause was never confirmed, and naming a vendor as cause without evidence is the exact failure mode this demo exists to criticise

---

## 2. System under test

| Attribute | Value |
| --- | --- |
| Host | `intg-prod-a1`, single production instance, IaaS VM |
| OS | RHEL 8.x, SELinux enforcing, `targeted` policy |
| Workload | JVM-based managed file transfer and batch integration service |
| Capacity | 8 vCPU, 32 GiB RAM, 8 GiB swap |
| Uptime at onset | 247 days |
| Non-production equivalent | Exists, but differs materially in build, patch level and installed agents |

### Standing condition (the pre-existing risk)

The JVM holds roughly **23 GiB resident of 32 GiB**. This is normal and has been normal for months. It is also the whole incident: usable headroom is single-digit GiB, so any new process with a non-trivial memory appetite tips the host into exhaustion. Nobody owns this number. It appears on no risk register and triggers no alert, because at steady state nothing is wrong.

---

## 3. Timeline

Relative days. Synthetic anchor: D0 = Monday 2 March.

| When | Event | Visible to whom |
| --- | --- | --- |
| **D-8** | Endpoint compliance agent rolled out across the fleet. Routine change, low risk, closed successful. | Change registry |
| **D0** | SELinux AVC denials begin at volume. The audit dispatcher wakes the OS denial-analysis daemon, which stays up from this point. The source domain of the denials is never identified. | Audit log (uncollected) |
| **D0** | Daemon consumes ~20% CPU sustained, spiking to 99%. RSS climbs from ~0.6 GiB towards 4 GiB. Combined with the JVM, the host enters memory exhaustion. Page fault rate rises. Swap usage climbs to ~4.5 GiB. | OS metrics |
| **D0 to D+15** | The observability platform opens and closes a memory-exhaustion problem on this host on **13 of 15 days**. Every one auto-closes. **None are acknowledged, assigned or actioned.** | Observability platform |
| **D+15, 16:40** | Batch transfers running late. A business user raises a ticket. Severity 2. Bridge convened at 17:00. | ITSM |
| **D+15, 18:38** | A process dump is analysed with LLM assistance. The output correctly notes that the observability agent's injection library is mapped into the daemon, explicitly flags this as **a lead and not proof**, and names the deciding evidence: the audit denial log, which identifies the source domain of the denials. | Bridge chat |
| **D+15, ~19:00** | The caveats are lost in transmission. What reaches the bridge is "AI indicates the observability agent is involved." The observability vendor is engaged. Investigation converges on them. | Bridge |
| **D+15, 19:21** | Change correlation finally run. Package history shows the compliance agent installed at D-8, the most recent change on the host, 8 days before onset. Two hours and twenty minutes into the bridge. | Bridge |
| **D+16, 09:51** | Vendor demonstrates their agent does not inject into Python processes and is not attached to the daemon. Their telemetry shows the host has been memory-exhausted for 15 days and that the platform has been raising it throughout. | Bridge |
| **D+16, 14:01 to 14:27** | Separately, a snapshot restore is rehearsed to an alternate location. Recovery point selected is **D+11, inside the affected window**. Restore takes 26 minutes against a stated 10 minute expectation, before any validation runs. | Cloud console |
| **D+16, 14:49** | Suppression applied: SELinux set to permissive, audit dispatcher deactivated, daemon killed. CPU and memory recover. | Host |
| **D+16, 19:29** | Incident closed. Root cause recorded as unconfirmed. | ITSM |

### Never collected

The audit denial log naming the source domain of the denials. This is the single piece of evidence that would have distinguished the compliance agent from the observability agent from the application's own service account. It was requested twice and never produced.

**The cause was not found. It was made to stop mattering.**

### Ground truth for generation (fiction, never evidence)

The fixtures are generated from a defined causal chain: the compliance agent's filesystem and integrity scanning produces the denials that wake the daemon. It is recorded here so the synthetic data is internally coherent and so evals have a truth to score against.

It is a property of the fiction, not a finding. No fixture exposes it, no agent can reach it, and no artefact may present it as established. In the pattern this composite is drawn from, the cause was never confirmed, and the timeline above carries only what was observable at the time.

---

## 4. Evidence availability map

The demo is only honest if the agents are restricted to evidence that was genuinely obtainable at that moment. This table is the constraint.

| Evidence | Available from | Cost to obtain | Collected in reality? |
| --- | --- | --- | --- |
| Problem feed, host-scoped | D0 | Free, already streaming | Yes, ignored |
| Host memory and CPU metrics | Continuous | Free | Yes, on a dashboard |
| Process-level resource attribution | D0 | One command | D+15 |
| Package and change history | Always | One command | D+15, 19:21 |
| Recent change records | Always | Registry query | Never correlated |
| Audit denial log, source domain | D0 | One command, needs host access | **Never** |
| Non-prod comparison | n/a | Impossible, builds diverge | Attempted, abandoned |

---

## 5. The gaps this demonstrates

1. **Detection existed. Consumption did not.** Fifteen days of correct, specific, automated detection went into an empty room. The tooling was not the failure.
2. **Standing risk was invisible because it was static.** 23 of 32 GiB is a latent incident with no alert attached, because nothing is wrong until something else arrives.
3. **The newest tool was blamed first.** Not from malice. From availability: it was the most recently changed thing anyone could name, and it was the only party with someone on the call able to answer for it.
4. **Epistemics were lost in transit.** The analysis was correctly caveated at the point of production. Three hops later the confidence and the falsifying test had fallen off, and a hypothesis was being treated as a finding.
5. **Non-prod could not validate prod.** The comparison that would have settled it in minutes was unavailable by construction.
6. **Recovery rehearsal validated a compromised recovery point.** The snapshot chosen sat inside the affected window. Had this been a real recovery, the condition would have been restored along with the host.

---

## 6. Counterfactual claims

What the demo asserts, in descending order of confidence. Understate deliberately. Every SRE watching will check the working.

### Tier 1: claim hard

**Days, not weeks, to human attention.**
Requires only a process that consumes the problem feed and notices recurrence. No diagnosis, no cleverness. A repeated auto-closing problem on the same entity is a signal on day two.

### Tier 2: claim confidently

**The bridge opens with change correlation already on the board.**
Package history against onset is a lookup. Note the framing: the bridge does not disappear, and humans still decide. It starts from evidence rather than spending two hours assembling it.

### Tier 3: claim carefully, and this is the differentiator

**The hypothesis reaches the bridge with its epistemics intact.**
Not "our model would have been right". The claim is structural: when confidence, supporting evidence and falsifying test are required fields on a typed output, a hypothesis cannot be quoted downstream stripped of its caveats. The lead about the observability agent still gets raised, because it was a reasonable lead. What changes is that it arrives labelled unconfirmed, with the deciding evidence marked blocking, so investigation does not converge on a vendor before the evidence that would exonerate them has been collected.

### Do not claim

- **Root cause.** It was never confirmed in the source pattern and the demo must not invent one. The compliance agent is the leading hypothesis. It is not a finding.
- **Autonomous remediation.** Every action that changes host state in this scenario is a security control change and requires human authorisation.
- **That the outcome would have been perfect.** Claim earlier, better evidenced and honestly bounded. Not solved.

---

## 7. Demo structure

Four minutes, three acts. **Do not open at the bridge.** Opening at the bridge sells two hours of saved call time. Opening at D0 sells fifteen days of degraded production and an unnecessary vendor escalation.

**Act one, D+1 to D+2, roughly 60 seconds.**
The problem feed. Second occurrence on the same entity, same signature, auto-closed, unacknowledged. Telemetry Analyst raises recurrence with the standing condition attached: 23 of 32 GiB resident, headroom insufficient to absorb a new consumer. This is the predictive half of the story and it is the part nobody else demonstrates.

**Act two, D+15, roughly 120 seconds.**
The bridge, run from evidence. Change Correlator has the D-8 deployment on the board at minute one. Incident Commander holds the hypothesis board: compliance agent leading, observability agent open, both unconfirmed, deciding evidence named and marked blocking. Attribution guard fires when convergence on a third party is attempted without direct evidence.

**Act three, roughly 60 seconds.**
Someone proposes setting SELinux permissive. The sandbox blocks it: security control change on a production host, outside the read-only boundary, human authorisation required. Blast radius and posture impact stated, including that the change is runtime-only while the config file still says enforcing, so it silently reverts on reboot. Scribe emits the change record that in reality was never written.

**Close on the blocked state, not a resolution.**
The final output is: hypothesis unresolved, deciding evidence outstanding, here is the single command that settles it, here is what each outcome rules in and rules out. Every SRE in the room has lived that ending. Closing there when a tidy resolution could easily have been faked is worth more than the other three claims combined.

---

## 8. Open items

- [ ] Reference chart of the 15 day problem feed, for faithful synthetic reconstruction. Reference only, never published.
- [ ] Confirm the fixture's problem cadence and severity mix against that reference
- [x] Decide whether act one runs as a separate spec invocation or as the first turn of the same pipeline. Resolved during M3: a separate invocation of the Telemetry Analyst against the D+1 view.
