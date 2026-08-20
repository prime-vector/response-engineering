# Evals

Measured quality for the Precedent Analyst, in two halves: what the retrieval
surface returns, and what the agent does with it. `docs/precedent-analyst.md`
section 7 specifies it; this directory implements it.

The agent's headline risk is not the missed precedent, it is the confident
wrong one. So the metrics that matter here are the ones that punish a
plausible answer: a precedent offered as applying when the record diverges, and
a refusal issued when the archive held something.

## What is here

| File | What it is |
| --- | --- |
| `dataset.yaml` | 38 cases with ground truth. Hand-authored. |
| `RELEVANCE.md` | How `expect.relevant` is judged, and why it is not scoped to the case. |
| `validate.py` | Asserts every claim in the dataset the corpus can settle. Runs in CI against both indexes. |
| `runner.py` | Measures retrieval against the dataset. Writes a timestamped JSON record and `results/latest.md`. |
| `config.yaml` | The baseline configuration: fixed chunker, no reranker, the k values, the passage budget. |
| `judgement.py` | Measures the agent: one live `oa run` per case, scored against the dataset and the adapter log. |
| `config.judgement.yaml` | The judgement arms, the judge model and the prompts it runs. |
| `judges/` | The judge prompts, committed. A judged number whose prompt is not readable is an assertion. |
| `prompts/` | System prompts derived from the spec for an arm that replaces one paragraph. Generated, checked in CI. |
| `results/` | Timestamped run records, `latest.md` (the baseline table), `chunker-comparison.md` and the judgement tables. |

Both halves are written. Retrieval measures the surface with no model in the
loop and re-runs for free; judgement measures the agent and costs one live
model run per case. What each can and cannot see is the whole reason they are
separate, and it is set out under **Judgement mode** below.

## Running it

```bash
python3 evals/validate.py                                   # heading-aware index
python3 evals/validate.py --index corpus/index.fixed.json   # the Phase 4 baseline
python3 evals/validate.py --repin                           # after a corpus change

python3 evals/runner.py --config evals/config.yaml          # record the baseline
python3 evals/runner.py --config evals/config.yaml --check   # CI: has the table drifted
python3 evals/runner.py --config evals/config.yaml --cross-check          # both indexes, every k
python3 evals/runner.py --config evals/config.yaml --cross-check --check  # CI
python3 evals/runner.py --index corpus/index.json --chunker heading --label heading-aware
python3 evals/runner.py --compare evals/results/<a>.json evals/results/<b>.json

python3 evals/judgement.py --list-arms                    # what an arm changes
python3 evals/judgement.py --dry-run                      # spends nothing
python3 evals/judgement.py --cases a01,b01,e01            # a cheap smoke run
python3 evals/judgement.py --arm judgement-heading        # a full sweep, live
python3 evals/judgement.py --check-prompts                # CI: derived arm prompts
python3 evals/judgement.py --check-records               # is a sweep owed, spends nothing
python3 evals/judgement.py --rescore evals/results/<record>.json
```

`evals/runner.py --mode judgement -- <flags>` reaches the same entry point,
which is the command `docs/precedent-analyst.md` names; everything after `--`
is passed through rather than mirrored in two argument parsers.

Needs PyYAML. Neither an API key nor the `patches/` provider patch is required
by either script in retrieval mode: both drive the mock surface directly and
never call a model. That is the point of splitting the modes, and it is what
makes iterating on the dataset affordable. Judgement mode needs both, plus the
`behavioural-contracts` extra, which it checks for rather than measuring a
harness with contract validation silently switched off.

`--rejudge` re-runs the judge over a recorded sweep with the current prompts and
payload, without re-running the agent. It is a fresh measurement rather than a
recount, so it stamps `rejudged_at`, records the fingerprint of the code that
produced the new verdicts, and prints what moved. The three committed records
have been judged four times each: once during the sweep, then three times
again. The first re-judge widened the payload from four fields
of a claim to all of them, which moved `groundedness_judge` from 71.2% to
75.0%, 80.4% to 85.7% and 81.8% to 90.9%: the original figures answered a
narrower question than the metric's own description, which is the reason to
re-judge rather than to restate. The two after that changed nothing the judge
sees, and measured something worth having.

**The judged level is a property of the judge, not of the agent.** The same
claims have now been scored by two model families. Under `claude-opus-4-6` at
temperature 0, and under `cursor-grok-4.6-high` through the CLI:

| arm | opus, four rounds | grok |
| --- | --- | --- |
| `judgement-heading` | 39, 37, 39, 38 of 52 | 15 of 52 |
| `judgement-fixed` | 48, 45, 49, 48 of 56 | 18 of 56 |
| `judgement-single-query` | 20, 19, 21, 21 of 22 | 10 of 22 |

Forty-five points of level, and the ordering survived intact: heading below
fixed below single-query under both. So `groundedness_judge` is readable as a
comparison and not as a score. A published figure of 73% or 29% says as much
about which judge ran as about the agent, and the arms' order says something
about the arms.

**The difference is one rule doing almost all the work.** Both judges apply the
prompt's instruction that a claim about the prior record lacking something is
unsupported unless a passage states the absence. Opus applies it to about a
quarter of claims; Grok applies it to nearly all of them, because most
divergence text asserts an absence somewhere. The rule is the metric's opinion
and the judge is how strictly that opinion is held.

**`divergence_quality` barely moved: 6/6, 6/7, 5/7 against 6/6, 6/7, 6/7.**
That judge is handed the dataset's list of distinguishing factors and asked
whether the text names one. The constrained question ported across families
almost perfectly; the open one did not. If a judged metric has to be comparable
across models, give the judge the answer key and ask it to match.

**Within one judge, the verdicts still move.** Four judgings of the identical
claims under Opus, all of them in the records:

| arm | first | second | third | fourth |
| --- | --- | --- | --- | --- |
| `judgement-heading` | 39/52 | 37/52 | 39/52 | 38/52 |
| `judgement-fixed` | 48/56 | 45/56 | 49/56 | 48/56 |
| `judgement-single-query` | 20/22 | 19/22 | 21/22 | 21/22 |

**Read that table for what it supports, which is less than it first appears.**
The four rounds do not share judge fingerprints: the payload was widened before
the first, and what the fingerprint covers was changed before the second, third
and fourth. So the spread across rounds mixes judge variance with those
changes, and this is not a clean variance measurement. The generated per-arm
tables say so themselves, from the fields rather than from a claim: when the
retained rounds do not share every judge input, the sentence under the table
changes to say so.

What each round does support is the comparison inside it. Both arms in a round
were judged by the same code, the same prompts and the same model, so the
ordering within a round is a like-for-like reading, and heading came out below
fixed in all four. That is the basis for calling the chunker gap repeatable:
four matched within-round comparisons, not four measurements of one number.

Each arm still moves by two to four claims between rounds, up to seven points
on `judgement-fixed`, which is reason enough never to read a single judged
percentage as precise. Isolating how much of that is the judge alone needs two
rounds with no code change between them, and that has not been run.

The deterministic figures do not move under `--rescore`; these do, which is the
reason the two are never published in the same table.

A record fingerprints two scorers, not one. The top-level `scorer` covers this
whole file and is answered by a free `--rescore`; the judged half carries its
own, narrower fingerprint over the code that decides what the judge is asked and
how its reply is read (`judge_run`, `call_judge`, `extract_json`, `score_run`,
`cited_ids`), and is answered by a paid `--rejudge`. The split is deliberate:
one fingerprint over both halves would certify judge output against code that
never saw it, and a file-level hash on the paid side would demand money for a
comment, which is how a check that costs money gets switched off. All three
committed records carry both.

`--rescore` recomputes the deterministic figures of a recorded sweep with the
current scoring, from what the record already holds. The runs are the half
that costs money and the scoring is the half that gets edited, so a scoring
change does not mean paying for the sweep again. It refuses a record whose
ground truth has moved, keeps the judged verdicts as recorded, and stamps the
record with what rescored it: a file whose numbers changed after it was
written has to say so.

`--check-records` answers the question you would otherwise answer by paying,
and names which of three remedies each drift needs. A re-run is a live sweep. A
re-judge is one model call per claim, against passages the record already
holds, and it recomputes the deterministic half on its way past. A rescore
reads the record and spends nothing.
is the recorded sweep still about this tree. Each record names the spec,
system prompt, index, corpus, ground truth, judge and scorer it ran against,
by fingerprint, and the check compares every one against what is on disk now.
It sorts what it finds into the three remedies, because they cost differently.
An input the runs depended on means a fresh sweep, live, 38 cases. A moved
judge, or moved code that drives it, means `--rejudge`: one model call per
claim, against passages the record already holds. Moved scoring means
`--rescore`, which reads the record and spends nothing. A green line is the
useful half: an arm nobody owes anything for.

The scoring check is over the whole of `judgement.py`, so editing a comment in
it reports every record as owed a rescore. That is the right way round, because
the remedy is free and settles the question either way. The judge check is
narrower for the same reason inverted: its remedy costs money, so it covers the
code that decides what the judge is asked and how its reply is read, and not a
comment somewhere else in the file.

Deliberately not in CI, unlike `--check-prompts`. A stale recording is a
statement about money owed rather than a broken artefact, and a gate that
fails until somebody spends is a gate that gets switched off.

`runner.py` refuses to run if the corpus fingerprint has moved off the
dataset's pin, and refuses if the config's `chunker` disagrees with the index
it names. Recording a baseline against the wrong index is the one mistake that
would make the Phase 5 comparison meaningless while looking entirely normal.
`--compare` refuses two runs that differ in corpus, ground truth, relevance
floor, passage budget or k list, and refuses a record too old to state one of
them. Each of those produces a plausible delta rather than an error, and the
delta is that input moving rather than retrieval improving.

Only a `--config` run writes `latest.md`. An exploratory `--index` run writes
its JSON and leaves the committed table alone, because it used to overwrite it
silently and the next `--check` reported drift that was the scratch run.

`runner.py` also refuses to measure through an adapter it did not start, and
proves the one it did start is serving the index that was asked for by
resolving a passage id taken from that index file. A passage id carries the
chunker name, so a leftover process serving the other index cannot pass it.

## The dataset

38 cases, against the 17-document corpus in `corpus/`.

| Group | Cases | What it tests |
| --- | --- | --- |
| `composite` | 4 | The scenario itself, at both bounds it is run at |
| `near_miss` | 7 | Records that match on symptom and diverge on what to do |
| `applies` | 8 | Precedent that genuinely transfers |
| `record_status` | 3 | A draft cannot ground a claim, however well it matches |
| `novel` | 10 | No counterpart in the archive; refusal is the correct answer |
| `time_bound` | 4 | An archive that held nothing yet, against one that held nothing relevant |
| `identity` | 2 | The entity id is not a similarity feature |

13 cases have no applicable precedent, against a specified minimum of eight.
Seven are near misses, against a minimum of four. `validate.py` asserts both
minima, so the composition cannot drift below what the spec fixes.

### Ground truth names documents, not passages

`docs/precedent-analyst.md` sketched the dataset with
`expected_passages: [<passage_id>, ...]`. That cannot work here, and the reason
is worth stating because the sketch reads as obviously right.

`corpus/ingest.py` derives a passage id from
`chunker|source_uri|heading_path|ordinal`. The chunker name is inside the key,
so the two indexes share no id at all: 82 passages under heading-aware, 39
under fixed, disjoint id spaces. Phase 4 records its baseline against the fixed
chunker and Phase 5 compares heading-aware against it, so passage-level ground
truth would score zero on whichever index it was not written against, and the
entire Phase 5 improvement would be the id scheme changing rather than
retrieval getting better.

Ground truth is `source_uri`, which both chunkers agree on, and
`precedent_hit_rate@k` is measured over documents.

**What this costs, and it is more than it first looks.** Document-level truth
cannot tell a citation of the right document's `Resolution` section from its
`Gaps` section. Nothing else measures it either:

- Adapter-log groundedness proves only that a cited `passage_id` was in the set
  the surface returned. A precedent citing `Gaps` passes whenever `Gaps` was
  among the hits, which the two-passages-per-document cap makes common.
- `groundedness_judge` is a different check again, an LLM judge at temperature
  0. Both are written now and neither closes this gap: the judge is given the
  passages the claim cites and asked whether they support it, which says
  nothing about whether a different section of the same document was the one
  to cite.

So the section-level gap is **unmeasured, not mitigated**, and it belongs in the
results table as such. An earlier draft of this file claimed groundedness
covered it; that was using the weaker check to wave away the cost.

If section quality has to be measured before Phase 5, the way in is an optional
heading-level expectation scored against the heading-aware index only, never
folded into the cross-chunker `hit_rate` comparison, which is the one number the
fixed baseline has to be able to share.

### Why it is hand-authored

Every other artefact derived from the corpus is generated with a `--check` that
fails on drift, so the instinct is to generate this too. Ground truth is a
judgement about which prior records a responder would want to see, and a
dataset generated from the retriever's output measures only that the retriever
agrees with itself.

The cases are made checkable instead. `validate.py` asserts, per case and per
index:

- the corpus is the one this ground truth was judged against, by a fingerprint
  over every document's sha256. Names existing is not enough: a document can be
  rewritten under the same uri, or a new one added, and every citation still
  resolves while the judgement behind it has gone stale. A corpus change fails
  here on purpose, and `--repin` is what you run after re-reading the affected
  judgements rather than instead of it
- every `source_uri` named still exists in the corpus
- a document claimed unreachable at a bound really is recorded after it
- a document named relevant is not one the bound puts out of reach
- every relevant document carries an applicability truth, so
  `false_precedent_rate` cannot silently skip one
- a filed document barred from grounding a claim argues why, per uri, in
  `must_not_cite_reason`, and a reason cannot outlive the entry it justified
- a case whose failure has a covering procedure in the archive, in reach at its
  bound, either names it or argues the omission in `covering_procedure_waived`
- what `coverage_describe` reports at a case's bound matches `coverage_expect`
- the retrieval figures a case states, per index: how much scored above zero,
  where a named document lands in the returned order, and what an identity
  probe clears
- stated `cleared_floor` and `candidates_considered` figures still hold
- `must_be_retrieved` documents are still returned, so a case about rejecting
  the hindsight trap fails rather than passing vacuously if the trap stops
  being reachable
- a document a case bars from grounding a claim, and which that case's own
  probe returns, is guarded by `must_be_retrieved`. Three cases bar a document
  their probe does not reach, because the agent issues queries this dataset
  does not; `d02` holds the trap's reachability for those, and if it ever stops
  returning it, that fails
- a no-precedent case retrieves nothing it does not explicitly allow, so a
  refusal case cannot decay into a judgement call
- the canonical query obeys the rule the agent is scored against, carrying no
  entity id

Negative-tested: each of those checks was confirmed to fail on a deliberately
broken case before being relied on.

The last three of those exist because figures kept living in prose. A number in
an `intent` paragraph is a comment, and one had already rotted before anyone
noticed: `g01` claimed its identity probe clears the floor seven times, which is
the fixed index's figure, while heading-aware gives nine. Anything a case
asserts about retrieval is a field now.

### What validate.py deliberately does not check

That the documents a case calls `relevant` are the ones the surface returns.
That number is `precedent_hit_rate`, it is what the runner reports, and
asserting it here would let the dataset grade itself: any case the retriever
missed could be "fixed" by editing the ground truth. It is printed as an
observation instead, so a collapse is visible without being enforced.

At limit 8, on a single canonical query, that observation currently reads:

| Index | Relevant documents reached |
| --- | --- |
| heading-aware | 36 / 60 |
| fixed | 38 / 60 |

`runner.py` reports the same two numbers as `precedent_hit_rate@limit`, from
the same probes. Deliberately the same figure in two places rather than two
figures: this one is printed as an observation the dataset must not be edited
to satisfy, and the runner's is the measurement. If they ever disagree, one of
them has changed what it counts.

**Read the denominator, not the ratio.** These are one query per case against
relevance that is scoped to the incident, so a case probing one axis of a
multi-axis incident is counted as missing the documents its other axis reaches.
`a03` searches the denial-daemon axis and is marked down for not returning the
memory-exhaustion records, which is correct: the spec tells the agent to query
more than once, and this observation deliberately does not.

`a04` is included, and that is deliberate. Its canonical query is the reported
symptom used whole, it reaches none of its five relevant documents, and it was
excluded from this figure on the reasoning that a probe designed to retrieve
nothing should not be mixed with probes designed to retrieve. That was the
fitting move in miniature: five real misses of a real query, uncounted because
the query cannot reach them.

Earlier versions of this file published 36/41, then 36/51, 36/53, 36/54 and
36/55. The denominator moved five times and the retriever never changed once.
Each step was a set of misses the bookkeeping had been hiding: relevance scoped
per case, then a rule applied to one group and not the next, then a case whose
gold set told an agent to refuse, then this exclusion.

That fixed edges heading-aware on this probe is worth noting rather than
explaining away: larger chunks match more query terms. Whether heading-aware
wins on the metrics that matter is Phase 5's question, and it is not settled in
advance.

## Judgement mode

`judgement.py` runs the agent. One live `oa run` of the recall task per case,
against the arm's index, with the arm's system prompt, and then scores what
came back. It needs `ANTHROPIC_API_KEY` and the `patches/` provider patch: a
stock install 400s the moment the model calls a tool.

**The runs are not regenerable. Everything derived from them is.**
A judgement table has a model in it: re-running an arm gives different
numbers, so no CI job can diff a fresh sweep against a committed one, and the
record carries a timestamp, the spec, the system prompt, the model and the
case ids instead. What CI does diff is everything downstream of the records,
which are files like any other: the three per-arm tables, the Phase 5
comparison grid and its two injected copies, and the query-strategy arm's
derived prompt.

The numbers cannot be checked, then. The inputs can, and that is what
`--check-records` does: it reads back the fingerprints a record already
carries and says whether the recording still describes the tree. A different
question from whether it would come back the same, and the one that decides
whether to spend.

### Two kinds of number, never one table

Deterministic, read off the typed output, the adapter's audit log and the
ground truth. Anyone can recheck them from the JSON record:

| Metric | What it counts |
|---|---|
| `false_precedent_rate` | precedent claims offered as `applies` where truth is `partial`, `superseded` or not relevant, over every claim offered |
| `no_precedent_accuracy` | correct `no_applicable_precedent` over cases where none exists |
| `false_refusal_rate` | refusals over cases where the archive held applicable precedent |
| `groundedness_log` | cited `passage_id`s that were in the set the surface returned |
| `agent_reach` | relevant documents the archive returned across the queries the agent chose |

Judged, by a separate model with the prompt committed in `judges/`. This is a
model's opinion of a model, and how much that matters is measured below:

| Metric | What it asks |
|---|---|
| `groundedness_judge` | do the cited passages support what the claim says |
| `divergence_quality` | does the stated divergence name a factor that actually distinguishes the two incidents |

The two never share a table. `groundedness_log` is the stronger check and the
weaker question: it proves a citation was not invented and says nothing about
whether the claim rests on the passage. The judge asks the question that
matters and answers it the way a model does.

`agent_reach` is the figure retrieval mode cannot produce. Retrieval mode
issues one canonical probe per case, which the README above is careful to call
a floor on the surface rather than an estimate of the agent. This counts what
the archive actually returned across the queries the agent issued, so the
"one query per case" limit does not apply to it. It is not comparable to
`precedent_hit_rate@k`: no rank truncates it, and the queries are the agent's.

### What is read from the log and never from the output

The OAS runner does not bind tool results into outputs, so a `passage_id` in a
citation is a string the model wrote either way, and a claim of the form "the
trap was retrieved and rejected" cannot be checked from an output that asserts
it. The archive logs `hit {passage_id} {source_uri}#{ordinal}` for every
passage that leaves the surface. Groundedness, reach, whether
`coverage_describe` was called before a refusal, and how many searches were
issued all come from that log.

### Arms

`config.judgement.yaml` holds them. Each changes one input against the first,
and `--compare` refuses two records that differ in more than one:

| Arm | What it changes |
|---|---|
| `judgement-heading` | nothing. The shipped configuration: heading-aware index, the spec's own prompt |
| `judgement-fixed` | the index, to the Phase 4 fixed-chunker baseline |
| `judgement-single-query` | rule 4 of the system prompt, replaced wholesale |

**One input is not one instruction, and the third arm is where that bites.**
Rule 4 tells the agent to query more than once *and* to ask for enough breadth,
because the surface caps how many passages a single document contributes. The
replacement drops both, and the records show the second doing real work: the
shipped arm passed `limit: 8` on 157 of its 182 searches, the alternative
passed no limit at all on 41 of its 43 and took the surface default of five. So
that arm measures the paragraph, not query count inside it. Neither `--compare`
nor `--check-prompts` can see the difference: one paragraph is one knob to
both. Separating them needs a fourth arm that keeps the breadth instruction,
and it is not run.

The third replaces the reranker experiment `docs/precedent-analyst.md` names
for Phase 5. There is no reranker in this repo to switch off: the mock ranks
by term overlap and `runner.py` refuses a config that declares one. The
retrieval guidance is the configuration this project actually made a decision
about, on a measurement (a whole reported symptom scores 79 of 82 passages
above zero and clears the floor 0 times, while the signature type alone
clears 35), so whether that decision is worth its words is the experiment that
was available.

One arm delivers its prompt through `--system-prompt` and the others do not,
so the delivery path had to be equivalent or the delta would be partly about
that. It was read rather than assumed: `oas_cli/runner.py` `_resolve_prompts`
assigns `system = override_system` at exactly the point it would otherwise
take the spec's, and only the user template is placeholder-substituted. Check
it again after a CLI upgrade.

Its prompt is **derived from the spec**, not written beside it. `--system-prompt`
replaces the whole system prompt rather than editing it, which the Phase 3
stripped-prompt work settled: a stripped run is not a plain run minus one
rule. So `judgement.py --write-prompts` regenerates
`prompts/single-query.system.txt` from the spec with one paragraph
substituted, `--check-prompts` fails when the spec moves under it, and a run
of that arm re-derives and refuses if the file is stale. A hand-maintained
override would drift into being a second prompt rather than one changed rule,
and every delta after that would be unattributable.

### What judgement mode still does not measure

- **Section-level citation.** Ground truth names documents. Neither the log
  check nor the judge distinguishes a citation of the right document's
  `Resolution` from its `Gaps`. Unmeasured, not mitigated, in both modes.
- **`cost_per_recall_usd`.** `oa` reports no token usage, so a per-recall cost
  from this runner would be a price list times an estimate. The judge's own
  usage is recorded, because the API returns it.
- **Whether a difference between two arms is real.** One sweep is one sample
  of a stochastic system. `--compare` prints deltas and says so; 38 cases
  would not support much of a significance test, and nothing here attempts
  one.

## Status

Phase 4 and Phase 5 are done.

- [x] Dataset written, 38 cases, composition asserted
- [x] Integrity check, both indexes, in CI
- [x] Retrieval metrics implemented: `precedent_hit_rate@k`, `mrr@k`, and the
      hit rate at a fixed passage budget
- [x] Runner, `--compare`, `--check`, `results/latest.md`, drift checked in CI
- [x] Baseline recorded against the fixed chunker with no reranker
- [x] Judgement metrics: `false_precedent_rate`, `no_precedent_accuracy`,
      `false_refusal_rate`, `groundedness_log`, `agent_reach`, deterministic
- [x] `groundedness_judge` and `divergence_quality`, with the prompts in
      `judges/` and whatever sampling the transport pins. Neither closes the
      section-level gap above, and the tables say so
- [x] `judgement-heading` recorded, the shipped configuration
- [x] `judgement-fixed` and `judgement-single-query` recorded, both
      comparisons run, and the result written up in the top-level README

**What these three records do not pin, and what the runs themselves show.**
They were made before the CLI and provider were recorded, so which runtime
produced them is an assertion by the author, one session on one install, rather
than a property of the artefact. `--check-records` says so per arm and calls
for a fresh sweep, which is the only thing that closes it. One part of it is
evidenced rather than asserted: 182, 163 and 43 tool calls came back
successfully across the three arms, and an unpatched install fails the first
one, so the `patches/` provider patch was applied. The CLI version is not
evidenced that way. Arms recorded from here carry both.

### The two Phase 5 comparisons

Three arms, one live sweep each, 38 cases, nothing rejected or unparseable.
The grid is generated from the three records and diffed in CI:

<!-- judgement-comparison:start -->

| measured by code | unit | judgement-heading | judgement-fixed | judgement-single-query |
| --- | --- | --- | --- | --- |
| `false_precedent_rate` | claims offered | 0/52 | 0/56 | 0/22 |
| `applies_omission_rate` | applies documents returned to the agent | 14/23 | 13/23 | 3/9 |
| `no_precedent_accuracy` | cases with no precedent | 13/13 | 13/13 | 13/13 |
| `false_refusal_rate` | answerable cases | 0/25 | 1/25 | 8/25 |
| `groundedness_log` | cited passage ids | 138/138 | 88/88 | 32/32 |
| `agent_reach` | (case, relevant document) pairs | 54/60 | 54/60 | 22/60 |
| claims understated | claims offered | 10/52 | 10/56 | 6/22 |
| claims on documents not called relevant | claims offered | 18/52 | 18/56 | 3/22 |
| searches issued | calls on the surface | 182, median 5.0 | 163, median 4.0 | 43, median 1.0 |
| p50 / p95 | one recall | 26.9s / 52.8s | 26.4s / 55.3s | 13.1s / 27.1s |

Applicability offered: judgement-heading `partial` 44, `superseded` 8; judgement-fixed `partial` 48, `superseded` 8; judgement-single-query `partial` 21, `superseded` 1. `false_precedent_rate` fires only on `applies`.

| judged by cursor-grok-4.6-high | judgement-heading | judgement-fixed | judgement-single-query |
| --- | --- | --- | --- |
| `groundedness_judge` | 15/52 | 18/56 | 10/22 |
| `divergence_quality` | 6/6 | 6/7 | 5/7 |

Both judged rates are scored over what each run offered, so offering less can raise them: judgement-heading never offered the diverging record on `b04`.

Generated by `python3 evals/judgement.py --comparison` from 3 records: `judgement-heading` recorded 2026-08-20T04:15:55Z, `judgement-fixed` recorded 2026-08-20T04:41:53Z, `judgement-single-query` recorded 2026-08-20T05:03:03Z. Do not hand-edit either copy: `--comparison --check` diffs this block in every file that publishes it.
<!-- judgement-comparison:end -->

**The headline rate is zero over a word the agent never used.** `applies`
appears in none of the 130 claims across the three sweeps; every one is
`partial` or `superseded`. `applies_omission_rate` catches what that
rate cannot: 14 of 23 documents that apply, returned to the agent by the
archive, on which no precedent was offered at all. Mostly the covering
runbooks. The tables print the applicability distribution beside the rate so
this cannot be read as calibration again.

**The rule 4 paragraph is worth its words, and the arm measures the
paragraph.** Replacing it refuses 8 of 25 answerable cases and reaches 22 of 60
pairs instead of 54, with all four composite cases refusing, at half the
latency. The paragraph carries two instructions and the replacement drops both:
query more than once, and ask for breadth because the surface caps passages per
document. The shipped arm passed `limit: 8` on 157 of 182 searches; the
alternative passed no limit on 41 of 43 and took the default of five. So the
delta is the paragraph, not query count in isolation, and `--compare` cannot
see the difference because a system prompt is one knob to it.

**The chunker is not choosable off one sweep each.** Same reach, 54 of 60, and
14 against 13 omissions. The judged half parts by 15/52 against 18/56, and
heading came out below fixed in every judging, so the gap is repeatable
even though its size moves by several points between rounds. That is a real
difference nobody should choose a chunker on: one sweep each, a judge scoring a
model, and no account of why.
Heading-aware is kept for its citations carrying the heading chain rather than
the document title alone, which no metric here scores.

`d01` is worth reading in both records. Both indexes returned the covering
procedure. Heading-aware offered only the barred draft, as `partial`, and never
cited the procedure; fixed refused the case. Two different failures, and until
`applies_omission_rate` existed neither showed up in a headline rate.

**A higher `groundedness_judge` in both alternatives is explained for one of
them.** The single-query arm made 22 claims against 52, and the failure the
judge catches scales with how much divergence text there is. The fixed arm made
more claims than the shipped one, 56 against 52, and still had more supported.
That is not explained here.

### What the first judgement sweep says

`results/judgement-heading.md` has the table: 38 cases, no run rejected or
unparseable, `false_precedent_rate` 0 of 52 claims, `no_precedent_accuracy` 13
of 13, `false_refusal_rate` 0 of 25, `groundedness_log` 138 of 138,
`agent_reach` 54 of 60 pairs, p50 26.9s and p95 52.8s.

Three things in it are worth more than the headline rates.

**A zero false precedent rate beside ten understated claims.** Ten of the 52
claims are offered as `partial` where the ground truth says the document
applies. An agent that never says `applies` cannot offer a false precedent, so
the two figures have to be read together, and the table prints them together
for that reason.

**`groundedness_judge` at 28.8% under the judge now configured, and the
failures have one shape.** Nearly all of the 37 unsupported claims assert an
absence: "the prior incident shows no audit
daemon", from passages that simply do not mention one. It is a divergence of
exactly the kind rule 5 asks for, resting on something the archive never said.
`groundedness_log` cannot see it: every one of those citations is a passage the
surface really returned. This is the case for having both checks and for never
adding them together.

**Two cases cited a draft, and how they did it is the finding.** `d01` cited
`DRAFT-2508` and `g01` cited `DRAFT-2601`, both as `partial` and
`speculative`, with a `divergence` saying in words that the document is
unsubmitted and cannot ground a precedent claim. `precedents[]` has no entry
meaning retrieved and rejected, so an agent that wants to report the trap has
to type it as precedent and put the caveat in prose. That is a gap in the
output contract rather than a tuning problem, and it belongs on the board
rather than in a prompt tweak.

### What the baseline says, and the finding in it

`results/latest.md` has the table. The one result worth carrying forward:

**Two hit rates, because there are two questions.** Ranking documents with
nothing truncating asks which prior records the surface orders highest.
Counting what survives inside a fixed passage budget asks what a caller under
that budget gets, and chunk size decides how many distinct documents fit in
eight passages.

**The budget is an eval parameter, and an earlier version of this file called
it the agent's.** Nothing binds the agent to eight: `mock/adapter.py` defaults
`precedent_search` to five, `.agents/precedent-analyst.yaml` tells the agent to
ask for enough breadth without naming a number, and no demo passes one.
`validate.py` had said "limit 8 matches the demos" since the previous PR and
that was never true. So `precedent_hit_rate@limit` measures the surface under a
fixed budget, which is a real question about the retriever, and it is not an
estimate of what the agent is handed. Sol found it at the gate. What the agent
actually requests is recorded in `search_coverage.queries_issued`, and scoring
it is judgement mode's job.

Whether the spec should name a number at all is a genuine open question rather
than an oversight: the qualitative guidance is deliberate, and pinning a limit
in the prompt would fix something the agent is meant to judge. It is on the
board, not resolved here.

The chunkers differ on both, in different places. At the budget it is 38/60
against 36/60. On the ranking they are identical at k = 1, 3, 5 and 8, and
differ at k = 2, where heading-aware reaches 25 of 60 pairs against fixed's 24:
`b03`'s `INC-2446` is rank 2 under heading-aware and rank 3 under fixed, and
the baseline's grid steps over the gap that lives in. Every one of those
figures is measured by `results/chunker-comparison.md`, which CI diffs.

This file said the ranking was **chunker-blind**, flatly, and that was wrong.
Two failures produced it, and both are worth naming because neither was a
retrieval mistake:

- **A grid was mistaken for every k.** Four k values were chosen for the table,
  the two indexes agreed on all four, and the conclusion drawn was about all k.
- **The claim lived where nothing could falsify it.** It was a hardcoded
  sentence in `runner.py`'s table generator, and `--check` regenerates the
  baseline against one index. Both sides of the diff carried the same sentence
  whatever the other index did, so CI certified it while being structurally
  unable to test it.

The fix for the second is `--cross-check`, which scores both indexes at every k
from 1 to the deepest rank any relevant document reaches, reports the k values
where they part rather than taking a grid, and writes
`results/chunker-comparison.md` with its own `--check` in CI. Grok found the
first in review of PR #16; the k = 2 figure was measured rather than argued
about.

The cross-check scores both indexes **at the passage budget too**, and that was
a second round of the same mistake. The first fix measured the ranking across
both indexes and left the budget comparison where it had always been: `38/60
against 36/60` typed into three documents, with only the `38/60` half inside a
checked artefact, because `latest.md` is the baseline index alone. Sol found it
at the pre-merge gate. A cross-index claim needs a cross-index measurement
whichever metric it is about, and fixing that for one metric while leaving the
metric it is contrasted with unchecked is the fix stopping one line short.

For Phase 5 the consequence is that both numbers get reported. Either alone
answers a question it was not asked.

### Notes for the runner

Two things the dataset already forces.

**Split the modes.** Retrieval metrics (`precedent_hit_rate@k`, `mrr@k`) are
measured from the surface with no model in the loop, from each case's `query`.
The judgement metrics (`false_precedent_rate`, `no_precedent_accuracy`,
`false_refusal_rate`, `groundedness`, `divergence_quality`) need a live
`oa run` per case, which costs an API call and needs the `patches/` provider
patch. Keeping retrieval-only runs free is what makes iterating on the dataset
affordable.

**Score the agent on its own queries, not the canonical one.** `query` exists
so the surface can be measured independently. The agent chooses its own
queries, records them in `search_coverage.queries_issued`, and
`queries_must_not_contain` is checked against those. Case `a04` is the one that
makes this matter: its canonical query is the reported symptom used whole,
which clears the floor zero times on both indexes, so an agent that issues one
verbose query retrieves nothing and refuses. The archive holds precedent, so
that refusal counts as a false refusal.
