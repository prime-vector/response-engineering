# Four minute walkthrough: shot list

Checked against `docs/walkthrough-claims.md`. Every claim below is annotated
with the tier that guarantees it. **No line speaks a Tier 3 number.** Where a
figure has to appear it is read off the screen inside the take, not asserted
from here.

Seven shots, about 560 words of voice, which is four minutes at a measured
pace. Timings are a budget, not a metronome.

The order is the argument: the failure, then the moment it happened, then the
layer, then the layer doing it, then what we will not claim. It opens on day
one and not at the bridge, deliberately. Opening at the bridge sells two hours
of saved call time.

---

## 1. The empty room (0:00 to 0:30)

**Screen** `docs/diagrams/fifteen-days.svg`, held. Then the problem feed in the
day one view.

**Voice**
> A production integration host. Over fifteen days, the observability platform
> opened and closed the same memory exhaustion problem on thirteen of them.
> Same signature, same severity, every one auto closed. Not one was
> acknowledged, assigned or actioned by anybody.
>
> Detection existed. Consumption did not. The tooling was not the failure, and
> buying more of it would not have helped.

**Claims** Thirteen problems, fifteen days, all auto closed, none acknowledged:
**Tier 0**, asserted by `fixtures/generate.py` and diffed in CI.

---

## 2. Twenty two minutes (0:30 to 1:05)

**Screen** `docs/diagrams/caveat-decay.svg`.

**Voice**
> On day fifteen a business user raises a ticket about late batch transfers and
> a bridge convenes. Nobody on it has seen the fifteen days.
>
> A process dump is analysed, and the analysis is good. It names a lead, states
> plainly that it is a lead and not proof, and names the single piece of
> evidence that would settle it.
>
> Twenty two minutes later, what reaches the bridge is a sentence. The
> confidence is gone. The falsifying test is gone. A third party is engaged and
> the investigation converges on them, and the next morning that third party
> demonstrates it was never their agent.
>
> The cause was never established. It was made to stop mattering.

**Claims** The composite's own timeline, **Tier 0**, from `SCENARIO.md`. No
third party is named. Do not say the cause was found.

---

## 3. What we build (1:05 to 1:40)

**Screen** `docs/diagrams/architecture.svg`, then a spec open at the
`confidence` and `falsifying_test` declarations.

**Voice**
> Operations is a software problem. We build the production agent layer:
> defined as code, tested in CI, constrained by contract.
>
> Every arrow between these agents is a typed output. Any claim carries a
> confidence word and a falsifying test as required fields, so the thing that
> fell off the analysis on that bridge has nowhere to fall. Confidence is one
> enum in one order in every spec that carries a claim, and a check in
> continuous integration holds all six of them to it.

**Claims** Required fields and the single scale: **Tier 1**, enforced by the
output contracts and `checks/contract_invariants.py`. Descriptor is verbatim
from the language rules and does not get paraphrased.

---

## 4. Day one (1:40 to 2:25)

**Screen** `demos/investigate.sh act1` starting. Cut on the generation, return
on the output.

**Voice**
> This is that layer against the day one view, before anyone knows there is an
> incident. The view holds only what had actually been collected by then: two
> problems, a metric series, and a standing condition nobody owns.
>
> The analyst reports the recurrence and states how far each finding can be
> carried. The archive is asked as it stood that day, so a note written later
> in the incident is out of reach of the query rather than filtered out of the
> answer.
>
> Opening at the bridge sells two hours of saved call time. Opening here sells
> fifteen days of degraded production and an unnecessary escalation.

**Claims** Day one view contents: **Tier 0**. Bounded recall: **Tier 1**. Read
the finding count off the screen if it is mentioned at all, it is Tier 3.

---

## 5. The board refuses (2:25 to 3:05)

**Screen** `demos/governance.sh attribution` live, ending on the guard and the
convergence note.

**Voice**
> Now the same material the bridge had. The relay with the caveats stripped, a
> third party already engaged, and a direction to record the cause and stand
> down.
>
> The board refuses. Convergence cannot be allowed while a blocking item is
> outstanding, and the deciding evidence is outstanding. Naming a third party
> below confirmed forces a guard onto the board that states what is missing and
> what would settle it.

**Claims** Both **Tier 1**, and the take's own **Tier 2** verdict is its exit
status. Say "while a blocking item is outstanding", never "convergence is
always blocked".

---

## 6. The change that does not dispatch (3:05 to 3:30)

**Screen** `demos/governance.sh sandbox`, ending on the violation line.

**Voice**
> And the directed production change. The prompt cooperates fully. The sandbox
> refuses it before dispatch, because the allow list on that task is empty.
>
> Anything that changes production state, alters a security control, or cannot
> be reversed inside the incident window requires human authorisation. There is
> no configuration option to turn that off.

**Claims** **Tier 1**, structural. The `Allowed: []` on screen is the evidence,
so hold the frame on it.

---

## 7. What we will not claim (3:30 to 4:00)

**Screen** `docs/samples/briefing-2026-08-24/`, the file list, then the failing
render beside the board.

**Voice**
> One last thing, because it is the whole argument.
>
> Our own briefing agent still strengthens its board. Four renders of one board
> are committed here, including the ones that failed. The typed half holds and
> is checked against the board it came from. The prose half is not, and cannot
> be, because a caveat carried in a sentence can be negated by a sentence.
>
> That is why the contract carries the caveat as a field and does not trust the
> paragraph to carry it as a word.
>
> You shifted left and fixed the pipeline. Production is still a person reading
> a dashboard at 3am. We engineer that layer.

**Claims** The briefing measurement: **Tier 1**, the samples are committed and
`checks/briefing_grounded.py` runs over them. Hero line verbatim.

---

## Before recording

1. All checks green on the commit being recorded, so every Tier 1 claim is true
   of what is on screen.
2. This file read against `docs/walkthrough-claims.md`, line by line, for Tier 3
   numbers that crept in during editing.
3. `demos/governance.sh all` inside the take where shots 5 and 6 run, so the
   exit status is the take's own verdict rather than a claim about earlier runs.
4. Three patches applied and `checks/stream_probe.py` green, or a long
   generation can be cut in transit and the take is lost at length rather than
   at content.
