# Precedent Interface

**Principle: no vendor name appears inside a spec.** Same rule as `interfaces/TELEMETRY.md`, and it bites harder here. Retrieval is where implementation detail leaks fastest: a spec that mentions an index, an embedding model or a similarity threshold has stopped declaring capability and started configuring a product. The Precedent Analyst asks for precedent. How that is found is entirely the adapter's problem.

The seam is MCP, the naming convention is the same (dotted call names here, underscores in the MCP tool names), and the mock at `mock/adapter.py` is the conformance reference.

What lives behind this surface and never in front of it: the store, the chunker, the embedding model, the ranking strategy, the reranker, the score threshold. Change any of them and no spec changes. That is the test of whether this document is doing its job.

---

## `precedent_archive` surface

Port 8426 in development, chosen to sit clear of telemetry (8422), change registry (8423), host (8424) and the incident record sink (8425).

Read only, permanently. There is no ingest call, no feedback call and no call that marks a precedent as useful. Writing to the archive is a pipeline concern, outside the incident window and outside any agent's reach. The Scribe writes records; this surface only ever reads them back.

### Citation shape

Every passage this surface returns carries, without exception:

| Field | Meaning |
| --- | --- |
| `passage_id` | Stable identifier, derived from position rather than content. |
| `source_uri` | Where the document lives. |
| `heading_path` | The heading chain down to this passage, e.g. `Runbook > Memory pressure > Node eviction`. What makes a citation checkable by a human in about five seconds. |
| `ordinal` | Position within the document, so a reader can find it even if the headings repeat. |

**What `passage_id` stability actually guarantees**, stated narrowly because the broad version is not true: re-ingesting an unchanged document tree reproduces every id exactly, and editing the wording inside a passage does not move it. Renaming a heading, inserting a section, or changing chunker all reassign ids, because all three change position. Citations made against one index resolve against the next only while the document structure holds, and a chunker change orphans every citation in the archive by design. That is a smaller promise than "a citation still resolves next month", and it is the one the format can keep.

**A passage that cannot produce a complete citation must not be retrievable.** Not returned with a null citation, not returned with a best guess: absent from the result set entirely. This is the retrieval equivalent of the incident record being written only through a provable tool call. An ungrounded claim should be impossible to construct, not merely discouraged, and the agent's output contract requires a `passage_id` in `grounded_in` for exactly this reason.

Passages are returned verbatim. The adapter does not summarise, paraphrase, merge or synthesise across passages, because a reader checking a citation must find the words that were cited. An adapter that improves the text it returns has broken the only guarantee this surface offers.

### `precedent.search`

Request: `signature_terms` (the stable signature type the Telemetry Analyst detects on), `symptom_text` (free text describing what is happening now), `before` (**required**; excludes anything recorded after this time), `limit` (optional). At least one of `signature_terms` and `symptom_text` must be present.

Pass the signature *type*, never the entity id. The host is identity, not symptom, and a similarity query built on it makes identity a retrieval feature: the archive starts returning records because they mention the same machine rather than because they describe the same failure.

`before` exists because precedent is time-ordered evidence. An investigation reconstructing what was knowable on day two must not retrieve a record written on day fifteen. Without this the archive quietly leaks hindsight into a replay.

Response: `passages`, each with its citation, the verbatim text, a `relevance` score, and:

- `source_family`, one of the families `coverage.describe` reports, so the reader knows whether they are looking at vendor documentation or at this organisation's own history.
- `document_cause_claimed`, where the passage comes from a prior incident record that states a cause. **Treated as a signal, never as evidence**, exactly as `root_cause_claimed` is on `problems.list`. A prior record asserting a cause is a record of what someone concluded, which is not the same as what happened.
- `record_status`, where the passage comes from a record this system produced. A Scribe draft is unsubmitted and unreviewed, and a passage retrieved from one must say so rather than borrowing the authority of a filed record.
- `document_superseded_by`, where a later change invalidated the resolution described. This is what lets the agent return `applicability: superseded`: surfaced, cited, and not recommended.
- `claim_scope`, always `document`.

The `document_` prefix is doing work. These are properties of the whole document, repeated on every passage cut from it, so two passages carrying the same claim are one source saying one thing twice. Named `cause_claimed` they read as two records agreeing, which is a corroboration the archive never offered.

Plus, on the response envelope: `floor_applied`, `excluded_by_before`, and a ladder of three counts narrowing to the returned set.

| Count | Meaning |
| --- | --- |
| `candidates_considered` | Passages that survived the time bound |
| `total_scoring_above_zero` | Of those, how many the query touched at all |
| `cleared_floor` | Of those, how many met the floor, before the per-document cap and `limit` |

Three rather than one, because one cannot separate the cases an empty result could mean. `candidates_considered: 0` means the bound emptied the archive. Considered at 59 with nothing scoring means the archive holds nothing the query touches. Considered at 59, 31 scoring, none clearing means the archive was searched properly and nothing was good enough. Only the last is a precedent judgement, and a caller that cannot tell them apart will report the first two as though they were the third.

Each count answers a question the others cannot, which is the test for whether a fourth belongs. Two names for one number is worse than one name.

**The bound is required.** There is no value meaning "no bound", and callers pass the view's `as_of`. An optional hindsight control is how hindsight gets in: a replay of what was knowable on day two that omits the bound still looks correct, and nothing in the result says otherwise.

**No more than two passages come from any one document.** Four passages from a single prior incident is not corroboration, it is one record quoted four times, and a result set weighted that way reads as agreement. Capping the source is what leaves room for the thing an agent has to state a divergence against.

**Below the floor, the surface returns an empty passage set.** Not the nearest match with a low score attached, because a low score in a result set still anchors, and the failure this whole agent is built against is the confident wrong precedent. An empty set with `total_scoring_above_zero: 7` and `cleared_floor: 0` is a specific, auditable statement: seven passages touched the query and none was good enough. The agent then has nothing to ground a claim in, and its output contract does the rest.

The floor's *value* is adapter configuration and does not transfer. Scores from term overlap, from cosine similarity and from a cross-encoder live on different scales, and a number tuned against one corpus means nothing against another. What transfers is the property, and this is the conformance requirement:

> **A query whose distinctive terms are unseen in the archive must not clear the floor.**

An adapter satisfies that however its scoring works. The mock does it by weighting an unseen term as maximally informative and unmatched, which is worth knowing but is not a requirement to reimplement.

Be honest about what the floor is not. It is not a semantic guarantee, and it does not certify that a passage above it is relevant. A content-free query of ordinary words can clear it, which the conformance suite records as a measured observation rather than hiding.

### `passage.get`

Request: `passage_id`. Returns the full passage, its complete citation, and the same qualifier fields.

This is the call that makes a citation verifiable rather than decorative. A board citing `passage_id` can be checked, by a human or by an eval, without access to the search that produced it. An adapter where search returns identifiers that `passage.get` cannot resolve is not conformant, however good its search results look.

### `coverage.describe`

Request: `before`, **required**, the same bound `precedent.search` takes. Returns `as_of`, `source_families` (the categories ingested, e.g. prior incident records, runbook procedures, postmortems, vendor operational documentation), `date_range`, `document_count`, `passage_count`, `floor_applied`, and `corpus_current_to`, all computed over the documents that bound allows.

**Coverage is bounded exactly like search, and for the same reason.** Unbounded, this call leaks what search refuses. A D+1 caller cannot retrieve the working note dated inside the incident window, but an unbounded `corpus_current_to` would still tell it the archive holds something recorded during the incident it is investigating. Search honest and coverage not is worse than either being wrong on its own, because coverage is the thing a refusal cites as proof it looked.

It reports content, never implementation. Which chunker built the index, which store holds it and which model embedded it all stay behind the surface, for the same reason this document opens with. Those belong to the evals, which read the index directly.

`corpus_current_to` is the date of the newest document held, not the time the index was built. Deliberately: a build timestamp changes on every ingest whether or not anything was ingested, which makes an unchanged archive look refreshed. What a responder needs to know is how current the content is.

Not decoration, and not a status endpoint. It is what makes a refusal falsifiable. "No applicable precedent" from an agent that cannot say what it searched is indistinguishable from an agent that searched nothing, and a refusal nobody can check is worth exactly as much as a claim nobody can check. The `no_applicable_precedent` path in the spec requires populated coverage for this reason.

It also states the archive's limits honestly. An archive whose `date_range` starts after the incident under investigation cannot hold precedent for it, and that should be visible in the output rather than inferred from an empty result.

---

## Adapter mapping

| Interface call | Confluence | ServiceNow | Docs site or object store |
| --- | --- | --- | --- |
| `precedent.search` | Content search API, plus own index | Incident search over resolution notes | Own index over crawled or synced documents |
| `passage.get` | Page and anchor fetch | Incident record fetch | Object fetch by key |
| `coverage.describe` | Space and page inventory | Query scope and retention window | Sync manifest |

Every column needs an index the source system does not provide, which is the honest position: none of these platforms exposes retrieval at the granularity a citation requires. The adapter owns the index. The interface owns the citation.

The mock indexes the corpus with `corpus/ingest.py` and serves it from `corpus/index.json`, stdlib only, like every other surface. Its ranking is term overlap weighted by inverse document frequency, which is not what the real adapter does and is not meant to be: what the mock has to reproduce is the contract, not the retrieval.

Both the mock and its two chunkers are also what `corpus/eval.py` runs against, which is the point of keeping the fixed-size index alongside the heading-aware one. An adapter that passes the suite against one index and fails against the other has found a property of its chunking, not of the contract.

---

## What this surface must not do

- **No write call, of any shape.** Not ingest, not feedback, not a usefulness rating. The capability is structurally absent, the same way the incident record sink has no submit call.
- **No synthesis.** No summarised answer, no merged passage, no generated explanation of why a passage matched. The agent reasons; the surface retrieves.
- **No reading another agent's surface.** Precedent is retrieved from the archive, never assembled by querying telemetry or the change registry. One agent, one surface.
- **No silent enrichment.** An adapter that fills a missing `heading_path` by inference, or that infers a `document_cause_claimed` a record never stated, fails conformance even though every field is populated.

---

## Conformance

An adapter is conformant when, against the same corpus as the mock:

1. Every returned passage carries a complete citation, and every returned `passage_id` resolves through `passage.get`.
2. A query whose best candidate falls below the floor returns an empty passage set with `floor_applied` and the three counts populated, not a degraded match.
3. `coverage.describe` reports families and a date range that match what was actually ingested. An adapter reporting coverage it does not hold fails, and this is the failure that matters most: it makes every refusal unverifiable.
4. The near-miss record in the corpus is retrievable for a query resembling it, and is returned with the qualifier fields that let the agent distinguish it. An adapter that returns the near miss with nothing marking it as a near miss has passed retrieval and failed the actual job.
5. `before` is honoured. A passage recorded after the bound does not appear, whatever its score.
6. Passages are byte-identical to the corpus text.

7. A search with no `before` is refused, and the hindsight trap in the corpus is unreachable at the D+1 bound and reachable at a later one, from the same query.

`corpus/eval.py` runs all of these against the mock and exits non-zero on failure. It is the executable form of this section, and an adapter is conformant when it passes the suite against both indexes.

The near-miss case is the one to test first. Retrieval quality is measured in `evals/`; what is checked here is narrower and harder to fudge, that the surface hands the agent everything it needs to be wrong out loud rather than confidently.
