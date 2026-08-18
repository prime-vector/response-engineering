# Evals

Measured retrieval quality for the Precedent Analyst. `docs/precedent-analyst.md`
section 7 specifies it; this directory implements it.

The agent's headline risk is not the missed precedent, it is the confident
wrong one. So the metrics that matter here are the ones that punish a
plausible answer: a precedent offered as applying when the record diverges, and
a refusal issued when the archive held something.

## What is here

| File | What it is |
| --- | --- |
| `dataset.yaml` | 38 cases with ground truth. Hand-authored. |
| `validate.py` | Asserts every claim in the dataset the corpus can settle. Runs in CI against both indexes. |

The runner and the metrics are not written yet. See **Status** below.

## Running it

```bash
python3 evals/validate.py                                   # heading-aware index
python3 evals/validate.py --index corpus/index.fixed.json   # the Phase 4 baseline
```

Needs PyYAML. Neither an API key nor the `patches/` provider patch is required:
`validate.py` drives the mock surface directly and never calls a model.

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

14 cases have no applicable precedent, against a specified minimum of eight.
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

**What this costs.** It cannot tell a citation of the right document's
`Resolution` section from its `Gaps` section. That is a real limit of this
dataset and it belongs in the results table rather than in a footnote. What
still catches a citation landing in the wrong part of a document is
`groundedness`, which checks the cited passage against the adapter log's `hit`
lines rather than against the output's own word.

### Why it is hand-authored

Every other artefact derived from the corpus is generated with a `--check` that
fails on drift, so the instinct is to generate this too. Ground truth is a
judgement about which prior records a responder would want to see, and a
dataset generated from the retriever's output measures only that the retriever
agrees with itself.

The cases are made checkable instead. `validate.py` asserts, per case and per
index:

- every `source_uri` named still exists in the corpus
- a document claimed unreachable at a bound really is recorded after it
- a document named relevant is not one the bound puts out of reach
- every relevant document carries an applicability truth, so
  `false_precedent_rate` cannot silently skip one
- stated `cleared_floor` and `candidates_considered` figures still hold
- `must_be_retrieved` documents are still returned, so a case about rejecting
  the hindsight trap fails rather than passing vacuously if the trap stops
  being reachable
- a no-precedent case retrieves nothing it does not explicitly allow, so a
  refusal case cannot decay into a judgement call
- the canonical query obeys the rule the agent is scored against, carrying no
  entity id

Negative-tested: each of those checks was confirmed to fail on a deliberately
broken case before being relied on.

### What validate.py deliberately does not check

That the documents a case calls `relevant` are the ones the surface returns.
That number is `precedent_hit_rate`, it is what the runner reports, and
asserting it here would let the dataset grade itself: any case the retriever
missed could be "fixed" by editing the ground truth. It is printed as an
observation instead, so a collapse is visible without being enforced.

At limit 8, on a single canonical query, that observation currently reads:

| Index | Relevant documents reached |
| --- | --- |
| heading-aware | 36 / 41 |
| fixed | 37 / 41 |

Both numbers are from one query per case. The spec tells the agent to query
more than once, and the five documents a single probe misses are mostly the
ones that need the second axis: `INC-2288` on the bridge case is reached by the
denial-daemon query, not by the signature. Do not read these as the retrieval
baseline. They are the floor under it.

That fixed currently edges heading-aware on this probe is worth noting rather
than explaining away: larger chunks match more query terms. Whether
heading-aware wins on the metrics that matter is Phase 5's question, and it is
not settled in advance.

## Status

Phase 4 is partly done.

- [x] Dataset written, 38 cases, composition asserted
- [x] Integrity check, both indexes, in CI
- [ ] Metrics implemented
- [ ] Runner, `--compare`, `results/latest.md`
- [ ] Baseline recorded against the fixed chunker with no reranker

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
