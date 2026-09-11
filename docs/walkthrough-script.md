# Four minute walkthrough: shot list

Checked against `docs/walkthrough-claims.md`. Every claim below is annotated
with the tier that guarantees it. **No line speaks a Tier 3 number.** Where a
figure has to appear it is read off the screen inside the take, not asserted
from here.

Seven shots, 591 words of voice. **It lands at 4:32, and that number is
measured rather than assumed.** Shot 1 was recorded on 11 Sep and read in 24.45
seconds, first word to last, which is 137 words a minute. The timings below are
cut from that rate, plus 13 seconds of air across the seven holds. Timings are a
budget, not a metronome.

**The pace is not a problem to fix, and the length is the cost of that.** 137
wpm is a comfortable, clearly enunciated read; the earlier 145 was a figure
taken off a table rather than off a voice, and reading to it would buy twelve
seconds by making the delivery worse. Four minutes is the format's name. This is
where the writing and the reading actually came out, recorded here rather than
discovered in an edit.

**The alternative was cutting about thirty words, and it was rejected on
purpose.** Compressing checked copy to hit a clock is the exact pressure shot 2
is about, and the odds of taking a qualifier rather than a filler word are not
low enough to spend the claim list on.

The budgets are apportioned to the word counts. They were not, until 26 Aug:
shot 2 was written to 195 words a minute and shot 7 to 222, which is not a
measured pace but an auctioneer, and shot 7 is the close carrying the hero line.

The order is the argument: the failure, then the moment it happened, then the
layer, then the layer doing it, then what we will not claim. It opens on day
one and not at the bridge, deliberately. Opening at the bridge sells two hours
of saved call time.

---

## 1. The empty room (0:00 to 0:26)

**Screen** `docs/diagrams/fifteen-days.svg` to orient, then
`python3 demos/show.py feed`, held on the thirteen rows. Every line ends
`auto-closed  unacknowledged`, which is the shot: the column does the work, not
the voiceover.

This is the bridge view's feed, not the day one view. The day one view holds two
problems and belongs to shot 4, so putting it here would contradict the line
being spoken over it.

**Crop the header line, or hold below it.** It prints the view's collection
window, `2026-02-27 to 2026-03-17`, which is nineteen days. The fifteen being
spoken is the span of the problem days, 2 to 16 March, and the rows show it
correctly. Both are true and they are different numbers, so leaving the wider
one above the rows invites a viewer to do the arithmetic against the narration
and get a mismatch.

**Voice**
> A production integration host. Over fifteen days, the observability platform
> opened and closed the same memory exhaustion problem on thirteen of them.
> Same signature, same severity, every one auto closed. Not one of them was
> acknowledged.
>
> Detection existed. Consumption did not. The tooling was not the failure, and
> buying more of it would not have helped.

**Claims** Thirteen, fifteen, auto closed, unacknowledged, one signature, one
severity: **Tier 0a**, each one an assertion in `assert_feed_shape`. Do not
add "assigned or actioned": there is no such field and nothing asserts it.

---

## 2. Twenty two minutes (0:26 to 1:15)

**Screen** `docs/diagrams/caveat-decay.svg`.

**Voice**
> On day fifteen a business user raises a ticket about late batch transfers. A
> bridge convenes. Nobody on it has seen the fifteen days.
>
> A process dump is analysed, and the analysis is good. It names a lead, says
> plainly that it is a lead and not proof, and names the one piece of evidence
> that would settle it.
>
> Within the hour, what reaches the bridge is a sentence. The confidence is
> gone. The falsifying test is gone. A third party is engaged, the investigation
> converges on them, and the next morning they demonstrate it was never their
> agent.
>
> The cause was never established. It was made to stop mattering.

**Claims** The composite's own timeline, from `SCENARIO.md`. That is authored
fiction, fixed for a given commit and checked by nobody, so it is not Tier 0 and
not a guarantee. `SCENARIO.md` itself says the relay happened at around 19:00,
so the script says "within the hour" rather than asserting a precision the
source refuses. No third party is named. Do not say the cause was found.

---

## 3. What we build (1:15 to 1:53)

**Screen** `docs/diagrams/architecture.svg`, then `.agents/telemetry-analyst.yaml`
open at the `findings` item schema, which fits on one screen and shows
`confidence` with its five values and `falsifying_test` in the same `required`
line. Search `required: [statement, confidence, falsifying_test]`.

Use an analyst rather than the commander. The commander's contract is 1,078
lines and the interesting part is buried; the analyst makes the same point in a
screenful.

**Voice**
> Operations is a software problem. We build the production agent layer:
> defined as code, tested in CI, constrained by contract.
>
> Every arrow between these agents is a typed output. Any claim carries a
> confidence word and a falsifying test as required fields. What went missing
> on that bridge cannot go missing between them: the contract rejects the
> claim instead. Confidence is one enum in one order, six declarations across
> five specs, and a check in continuous integration holds every one of them to
> the same scale.

**Claims** Required fields and the single scale: **Tier 1**, enforced by the
output contracts and `checks/contract_invariants.py`. Descriptor is verbatim
from the language rules and does not get paraphrased.

The line is "no field to fall out of", and it is scoped to the handoff between
agents on purpose. "Nowhere to fall" is false the moment anything renders prose,
including shot seven, and saying it here is what makes shot seven read as a
retraction rather than as the argument.

---

## 4. Day one (1:53 to 2:44)

**Screen** `python3 demos/show.py day-one` first, held on `alerting: false` and
`owner: none` against the standing condition. Then `demos/investigate.sh act1`.

The `show.py` frame is what makes the act mean anything: two problems, no
evidence, no changes, no incident, and the line that is the whole incident
sitting there alerting nobody.

Then **end on one finding object from the act's own output**, not on the
driver's summary. The driver prints the confidence word in brackets and does not
print the falsifying test, so a narration that mentions both is describing
something the viewer cannot see. Open the act's `act1-detect.json` at a single
`findings` entry, where `statement`, `confidence`, `supporting_evidence` and
`falsifying_test` sit together, and hold it. Found by checking captured footage
against this file, which is what that step is for.

Choose the entry by two properties rather than by position, because which entry
is which is Tier 3 and moves between captures. **Prefer one whose `confidence`
is below `confirmed`**: the word is doing visible work only when it is not the
top of the scale, and its `falsifying_test` is then a real observation rather
than a restatement. **Never the entry that quotes the feed's note string**,
which reads "No problem in this window was acknowledged, assigned or actioned":
that is the phrase `docs/walkthrough-claims.md` bans, and putting it on screen
under a narration about typed fields asserts through the frame what the voice
is forbidden to say. In the 25 August capture that rules out the first entry
and leaves the `supported` projection, which is the frame that was checked.

**Voice**
> This is that layer against the day one view, before anyone knows there is an
> incident. The view holds only what had actually been collected by then: two
> problems, a metric series, and a standing condition nobody owns.
>
> Everything the analyst reports comes with a confidence word and the
> observation that would prove it wrong. The archive is searched as it stood
> that day. A note written later in the incident is not filtered out of the
> answer. On day one it does not exist yet.
>
> Opening at the bridge sells two hours of saved call time. Opening here sells
> fifteen days of degraded production and an unnecessary escalation.

**Claims** Day one view contents: **Tier 0b**, committed to the fixture and not
asserted. Required fields on whatever is reported: **Tier 1**. The bound on
search is **Tier 2**, verified from the adapter log by the driver in this run,
and the script says "searched" rather than "asked" because `passage_get` takes
no bound.

Do not say "the recurrence" or "each finding". `recurrence_detected` is a
required boolean, not a constant, and both are Tier 3 shapes with no digit in
them.

---

## 5. The board refuses (2:44 to 3:16)

**Screen** the captured `governance.sh attribution` output, ending on the guard
and the convergence note.

**Re-wrap it first.** The driver emits a labelled value on one line however long
the value is, which is right for someone reading a terminal and wrong for a
camera. In the 25 August capture three of those lines are 336, 263 and 470
characters, and the 470 is the convergence note this shot ends on. Wrapped under
its own label column it is 23 lines inside 78 columns, which is one screen and
holds. Shot 6 gains from the same treatment even though its longest line is only
111: wrapping puts `Allowed: []` on a short line of its own under the violation
reason, which is the frame.

**Voice**
> Now the same material the bridge had. The relay with the caveats stripped, a
> third party already engaged, and a direction to record the cause and stand
> down.
>
> The board refuses. It cannot converge while a blocking item is outstanding,
> and this board has them. Naming a third party below confirmed forces a guard
> onto the board, and here it names the evidence that is missing.

**Claims** The convergence rule and the guard being forced are **Tier 1**. What
the guard *contains* is **Tier 2**: `party`, `reason` and `evidence_required`
are optional in the schema and the demo is what checks them, so the line is
scoped to this board with "here it names".

Say "while a blocking item is outstanding", never "convergence is always
blocked". Do not say the deciding evidence is outstanding: which item is
outstanding is the board's judgement, and that count already moved between two
measured runs.

---

## 6. The change that does not dispatch (3:16 to 3:42)

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

## 7. What we will not claim (3:42 to 4:32)

**Screen** `ls docs/samples/briefing-2026-08-24/`, then
`briefing-bridge-before-rule-6a.json` beside `board.json`, on the entry that
attaches a precedent to a hypothesis the board cited none against. The
briefing's second suspected cause names `INC-2411`; the board's matching
hypothesis carries `precedent_cited: None`.

That is the render worth showing rather than the current one: it is the failure
the typed fields were added to close, and both files are committed so a viewer
can open them.

**Two frames with a cut between them, not both files side by side.** Pretty
printed these carry lines of 464 and 1,515 characters, the 1,515 being the entry
this shot ends on, so side by side is unreadable at any legible size. Show the
board hypothesis first, eleven lines, `confidence` and `precedent_cited (none)`
above the statement. Cut. Then the briefing entry it became, wrapped, about
thirty lines, with the sentence naming `INC-2411` marked in the gutter. The
sequence is the argument: what the board held, then what the prose did to it.
Mark the sentence, never edit it. The samples are committed byte for byte, em
dashes and all, and a frame that tidies one is no longer evidence.

**`INC-2411` is a real document in the corpus.** The render did not fabricate a
record, it carried one the board did not cite, and prose is what let it. Say it
that way. "It made up a citation" is the sentence this shot will drift towards
on the day, and it claims more than the two files on screen support, which is
the failure this shot exists to name.

**Voice**
> One last thing, because it is the whole argument.
>
> Our own briefing agent still strengthens its board. Four renders of one board
> are committed here, including the ones that failed. The current render's
> typed half is checked against the board it came from, entry by entry. The
> prose half is not, and cannot be, because a caveat carried in a sentence can
> be negated by a sentence.
>
> That is why the contract carries the caveat as a field and does not trust the
> paragraph to carry it as a word.
>
> You shifted left and fixed the pipeline. Production is still a person reading
> a dashboard at 3am. We engineer that layer.

**Claims** `checks/briefing_grounded.py` runs over the current render only, not
over the three failing ones, so the line is scoped to it. The failing renders
are committed evidence about prose rather than something a check covers, which
is the point being made. Hero line verbatim.

---

## Capture order

Shots 1, 2, 3 and 7 read committed files and can be captured any time on a green
commit. Shots 4, 5 and 6 are runs, and they are captured first so the narration
is written over output that has already been checked.

    python3 demos/show.py feed          # shot 1, free
    python3 demos/show.py day-one       # shot 4, free
    ./demos/investigate.sh act1         # shot 4, about 30c
    ./demos/governance.sh attribution   # shot 5
    ./demos/governance.sh sandbox       # shot 6

`governance.sh` writes its own verdict as its exit status, so capture the status
with the footage. `investigate.sh act1` has no expected-outcome assertion of its
own: check its output against Tier 0b and Tier 1 by hand before using the take,
and in particular do not let the narration describe a shape the run did not
produce.

## Why the runs happen before the take

Shots 4, 5 and 6 show generations. They are **not** generated during the take.
Run them first, check the output against `docs/walkthrough-claims.md`, and
narrate over footage that is already known good.

This is what closes the retake risk, and it costs nothing. A run that comes out
a shape the narration does not fit is then a re-run and a re-check, not a
re-record. The Tier 2 guarantee is untouched: `demos/governance.sh` exiting zero
for the footage on screen is still that footage's own verdict, and the exit
status belongs to the run being shown.

Measured across three composed runs, including one at `temperature: 0`: every
field the script is allowed to claim was identical in all three, and every field
the claim list forbids speaking moved.

## Recording

Record audio and picture separately, and **record the audio first**. The voice
is the spine and the picture is cut to it. Done the other way you are reading to
fit a fixed visual timing, which is the pacing defect above in another form.

**Voice.** Seven files, one per shot, not one continuous take, so a fluffed shot
2 does not cost shot 7. Two or three seconds of silence at each head and tail
for the edit. Read the whole script aloud once before recording anything:
phrases that break the mouth are invisible on the page and obvious the first
time you say them. Keep ten seconds of room silence, the edit will want it.

**Picture.** Nothing on screen wider than 78 columns, which is what both scratch
renderers wrap to. The terminal is pinned rather than set by hand, because text
that changes size between cuts is what makes a video look amateur without a
viewer being able to say why: one Windows Terminal profile, launched the same
way for every shot, holding at least 79 columns and 28 rows so the widest and
the tallest frame both fit. `runs/RECORDING-STEPS.md` carries the command.
Notifications off. Capture the window rather than the display, or an ultrawide
monitor hands you a picture that is a thin strip on a phone. Diagrams in a
browser sized to match, or dropped into the edit as stills.

What plays, by shot:

- `show.py feed` and `show.py day-one` are free and deterministic, so run them
  live if you prefer the look. They cannot vary
- Act one, attribution and sandbox play from the capture. They are verified,
  `exits.txt` carries the verdict, and re-running costs money and risks a shape
  the narration no longer fits
- Do not fake a live prompt with instant output. Display the captured file, or
  replay it with real timing. Cutting the generation wait is normal; implying a
  run produced something it did not is the thing this whole document exists to
  stop

**Two renderers, uncommitted on purpose.** One picks and wraps a findings entry
for shot 4, the other re-wraps a captured governance run for shots 5 and 6. Both
read gitignored `runs/` and render Tier 3 output, so neither belongs in
`demos/show.py`, whose docstring says everything it prints is Tier 0 and
reproducible by anyone with the repository. Keep them in a scratch directory and
let them be rebuilt.

**Not** one continuous live take. It fights the pre-run decision, and 596 words
of dense copy unbroken takes a dozen attempts to get clean.

## Before recording

1. All checks green on the commit being recorded, so every Tier 1 claim is true
   of what is on screen.
2. This file read against `docs/walkthrough-claims.md`, line by line, for Tier 3
   numbers that crept in during editing.
3. `demos/governance.sh` run **before** the take, with each exit status captured
   beside the footage it produced, the way `runs/2026-08-25-footage/exits.txt`
   records it. The mode behind a shot is that shot's verdict, because
   `governance.sh attribution` exits zero only if attribution produced its
   expected outcome; `all` is broader coverage rather than a stronger guarantee
   for these two shots. This item used to say inside the take, which is what
   "Why the runs happen before the take" supersedes: the guarantee is that the
   exit status belongs to the run on screen, pre-running satisfies it, and a
   live run adds back the retake risk M3 took two attempts to close.
4. Three patches applied and `checks/stream_probe.py` green, or a long
   generation can be cut in transit and the take is lost at length rather than
   at content.
