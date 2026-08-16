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
| `passage_id` | Stable identifier. Stable across re-ingest, so a citation in a board written today still resolves next month. |
| `source_uri` | Where the document lives. |
| `heading_path` | The heading chain down to this passage, e.g. `Runbook > Memory pressure > Node eviction`. What makes a citation checkable by a human in about five seconds. |
| `ordinal` | Position within the document, so a reader can find it even if the headings repeat. |

**A passage that cannot produce a complete citation must not be retrievable.** Not returned with a null citation, not returned with a best guess: absent from the result set entirely. This is the retrieval equivalent of the incident record being written only through a provable tool call. An ungrounded claim should be impossible to construct, not merely discouraged, and the agent's output contract requires a `passage_id` in `grounded_in` for exactly this reason.

Passages are returned verbatim. The adapter does not summarise, paraphrase, merge or synthesise across passages, because a reader checking a citation must find the words that were cited. An adapter that improves the text it returns has broken the only guarantee this surface offers.

### `precedent.search`

Request: `signature_terms` (the stable signature the Telemetry Analyst detects on), `symptom_text` (free text describing what is happening now), `before` (optional; excludes anything recorded after this time), `limit` (optional).

`before` exists because precedent is time-ordered evidence. An investigation reconstructing what was knowable on day two must not retrieve a record written on day fifteen. Without this the archive quietly leaks hindsight into a replay.

Response: `passages`, each with its citation, the verbatim text, a `relevance` score, and:

- `source_family`, one of the families `coverage.describe` reports, so the reader knows whether they are looking at vendor documentation or at this organisation's own history.
- `cause_claimed`, where the passage comes from a prior incident record that states a cause. **Treated as a signal, never as evidence**, exactly as `root_cause_claimed` is on `problems.list`. A prior record asserting a cause is a record of what someone concluded, which is not the same as what happened.
- `record_status`, where the passage comes from a record this system produced. A Scribe draft is unsubmitted and unreviewed, and a passage retrieved from one must say so rather than borrowing the authority of a filed record.
- `superseded_by`, where a later change invalidated the resolution described. This is what lets the agent return `applicability: superseded`: surfaced, cited, and not recommended.

Plus, on the response envelope: `floor_applied` (the score threshold in force), `total_before_floor`, and `excluded_by_before` (how much the time bound removed, so a thin result set caused by the bound is distinguishable from a thin archive).

**No more than two passages come from any one document.** Four passages from a single prior incident is not corroboration, it is one record quoted four times, and a result set weighted that way reads as agreement. Capping the source is what leaves room for the thing an agent has to state a divergence against.

**Below the floor, the surface returns an empty passage set.** Not the nearest match with a low score attached, because a low score in a result set still anchors, and the failure this whole agent is built against is the confident wrong precedent. An empty set with `total_before_floor: 7` is a specific, auditable statement: seven candidates were found and none was good enough. The agent then has nothing to ground a claim in, and its output contract does the rest.

### `passage.get`

Request: `passage_id`. Returns the full passage, its complete citation, and the same qualifier fields.

This is the call that makes a citation verifiable rather than decorative. A board citing `passage_id` can be checked, by a human or by an eval, without access to the search that produced it. An adapter where search returns identifiers that `passage.get` cannot resolve is not conformant, however good its search results look.

### `coverage.describe`

Request: none. Returns `source_families` (the categories ingested, e.g. prior incident records, runbook procedures, postmortems, vendor operational documentation), `date_range`, `document_count`, `passage_count`, `chunker`, `floor_applied`, and `corpus_current_to`.

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

The mock indexes the corpus with `corpus/ingest.py` and serves it from `corpus/index.json`, stdlib only, like every other surface. Its ranking is term overlap weighted by inverse document frequency, which is not what the real adapter does and is not meant to be: what the mock has to reproduce is the contract, not the retrieval. One property of it is load bearing, though, and any adapter needs the equivalent. A query term the archive has never seen must be weighted as maximally informative and unmatched, or a genuinely novel incident scores its way past the floor on the ordinary English it shares with the corpus, and the refusal path never fires.

---

## What this surface must not do

- **No write call, of any shape.** Not ingest, not feedback, not a usefulness rating. The capability is structurally absent, the same way the incident record sink has no submit call.
- **No synthesis.** No summarised answer, no merged passage, no generated explanation of why a passage matched. The agent reasons; the surface retrieves.
- **No reading another agent's surface.** Precedent is retrieved from the archive, never assembled by querying telemetry or the change registry. One agent, one surface.
- **No silent enrichment.** An adapter that fills a missing `heading_path` by inference, or that infers a `cause_claimed` a record never stated, fails conformance even though every field is populated.

---

## Conformance

An adapter is conformant when, against the same corpus as the mock:

1. Every returned passage carries a complete citation, and every returned `passage_id` resolves through `passage.get`.
2. A query whose best candidate falls below the floor returns an empty passage set with `floor_applied` and `total_before_floor` populated, not a degraded match.
3. `coverage.describe` reports families and a date range that match what was actually ingested. An adapter reporting coverage it does not hold fails, and this is the failure that matters most: it makes every refusal unverifiable.
4. The near-miss record in the corpus is retrievable for a query resembling it, and is returned with the qualifier fields that let the agent distinguish it. An adapter that returns the near miss with nothing marking it as a near miss has passed retrieval and failed the actual job.
5. `before` is honoured. A passage recorded after the bound does not appear, whatever its score.
6. Passages are byte-identical to the corpus text.

The near-miss case is the one to test first. Retrieval quality is measured in `evals/`; what is checked here is narrower and harder to fudge, that the surface hands the agent everything it needs to be wrong out loud rather than confidently.
