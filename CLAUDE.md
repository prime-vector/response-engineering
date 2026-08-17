# CLAUDE.md

Instructions for Claude Code working in this repository.

## Context

A reference implementation of an agent-run incident response layer, built on [Open Agent Spec](https://github.com/prime-vector/open-agent-spec). Read `SCENARIO.md` before touching anything. It is the source of truth, and every spec, fixture and piece of copy derives from it. `PLAN.md` has the milestones.

This repo is currently private. It goes public. Write everything as though it is already public.

---

## Hard rules

### 1. No source material, ever

This project is derived from real engagements. Nothing from that source material enters this repository. Not transcripts, not screenshots, not exported charts, not host names, not ticket references, not participant names. Not in a branch, not gitignored, not in a commit that is later reverted.

Git history is permanent. A file that was never added cannot be recovered from it.

If asked to add reference material, refuse and say why.

### 2. No vendor may be named in a causal role

Third-party products appear only as generic categories: *the observability platform*, *the endpoint compliance agent*, *the integration service*. Naming a vendor as a cause without direct evidence is the exact failure this project criticises. Doing it in our own artefacts would be self-refuting.

Vendors may be named in capability mappings, for example the adapter table in `interfaces/TELEMETRY.md`. That is a statement about APIs, not about blame.

### 3. The scenario is a composite

Never describe it as a client incident, a case study, or a real incident, even hedged. It is a composite of a recurring pattern. If copy drifts towards attribution, correct it.

### 4. Never invent a root cause

In the scenario, the cause was never established. The demo must not resolve it. If a spec, fixture or piece of copy starts asserting a confirmed cause, that is a bug.

### 5. No vendor names inside specs

Specs declare capability. Adapters implement it. If a spec references a specific platform, the interface abstraction has failed. See `interfaces/TELEMETRY.md`.

---

## Language

These exact words, everywhere. Do not paraphrase into synonyms.

> **Hero:** You shifted left and fixed the pipeline. Production is still a person reading a dashboard at 3am. We engineer that layer.
>
> **Descriptor:** Operations is a software problem. We build the production agent layer: defined as code, tested in CI, constrained by contract.

Vocabulary to use: production, incident response, responders, investigation, specs, contracts, evidence.

Vocabulary to avoid: *governed operations*, *ops automation*, *AIOps*, *single pane of glass*, *maturity*, *observability journey*. These read as managed services and undo the positioning.

Australian English. No em dashes.

---

## OAS conventions

The CLI is `oa`, not `oas`.

```bash
oa validate --spec .agents/<name>.yaml     # before every commit, for every spec touched
```

- `agent.role`: CLI 1.6.0 (Python and npm, both published) loosened role from the 1.5.x closed enum to a free-form string with well-known values. The incident commander declares `role: commander`, one of the 1.6.0 well-known hierarchy roles; the other specs keep their 1.5.x enum values, which remain well-known. Role is informational; role framing belongs in the prompt and the output contract.
- Spec version is `1.6.0`, tested against CLI 1.6.0 (previously 1.5.0 against 1.5.1). The 1.5.1 fail-open findings below have no fix in the 1.6.0 changelog; treat them as current. The declared version must be true rather than merely tolerated: the CLI bundles one schema, `oas-schema-1.6.json`, and selects nothing per version, so a spec declaring `1.5.0` while using `role: commander` validates green against a version it does not conform to. Declare what the spec actually uses.
- 1.6.0 adds a root-level `sandbox` key. Do not use it. It merges into every task the way a root `behavioural_contract` does, with per-task overrides applied per constraint key, so a task silently inherits a boundary nobody declared on it. Sandbox constraints belong on the task, for the same fail-open reason contracts do.
- Tool-calling `oa run`s need the provider patch in `patches/` until it lands upstream; stock installs through 1.6.0 400 the moment the model calls a tool (re-verified live on 1.6.0, 30 Jul 2026). `oa validate` is unaffected. A pipx upgrade also drops the contracts extra: re-inject `behavioural-contracts` afterwards, or contract validation skips with only a warning.
- One agent owns each surface: the Telemetry Analyst owns `telemetry`, the Change Correlator owns `change_registry`, the Scribe owns the `incident_record` sink, the commander consumes their outputs. Do not give a new spec a surface another agent already owns.
- Every agent output carrying a claim must include `confidence` and `falsifying_test` as required fields. This is not decoration. It is the entire thesis: a typed output cannot shed its caveats when it changes hands.
- Every variable a prompt template references must be a required input field. The CLI 1.5.1 runner substitutes `{{ placeholders }}` only from keys present in the input; a missing optional key reaches the model as literal template text, degrades the run silently, and input schema `default:` values are not applied. Callers pass empty values (`{}`, `[]`) explicitly.
- A task whose job is a tool call must say so in the mitigate task's wording: "Do not report until you have done X with a tool call." Without it the model self-attests: the Scribe's first live run reported `record_updated: true` having never called the sink. The runner cannot bind tool results into outputs, so a success flag or returned reference in an output proves nothing on its own; verify tool-use claims from the adapter log (the mock names every `tools/call`), never from the output.
- Size `max_tokens` with real headroom and declare `behavioural_contract` per task, never at spec root. Both for the same reason: CLI 1.5.1 fails open. A root contract merges into every task with arrays unioned, and a truncated JSON output skips schema and contract validation entirely and exits 0. Both are filed upstream; until fixed, headroom and task scoping are correctness settings. A task that files its payload with a tool call generates that payload twice in one response budget, once as tool arguments and once as the final reply: size for both, or the response truncates inside the tool call and the run exits 0 with empty output.
- Anything that changes production state, alters a security control, or is irreversible within the incident window must set `authorisation_required: true`. There are no exceptions and no configuration option to disable this.

---

## Fixtures

The fixture files are generated, never hand-edited. Change `fixtures/generate.py` and regenerate every view and demo input:

```bash
python3 fixtures/generate.py > fixtures/composite-incident.json             # D+15, the bridge
python3 fixtures/generate.py --at d1 > fixtures/composite-incident.d1.json  # act one
python3 fixtures/generate.py --demo attribution > fixtures/composite-incident.attribution.json
python3 fixtures/generate.py --demo mitigation > fixtures/mitigation-directive.json
```

The corpus behind the `precedent_archive` surface is generated and indexed the same way, and the index is a build artefact, never hand-edited:

```bash
python3 fixtures/generate.py --corpus corpus/documents   # the synthetic prior incident records
python3 corpus/ingest.py                                 # heading-aware, writes index.json and manifest.yaml
python3 corpus/ingest.py --chunker fixed                 # the Phase 5 baseline index
python3 corpus/ingest.py --check                         # non-zero if the index is stale
python3 corpus/eval.py                                   # surface conformance, non-zero on failure
```

Re-ingesting unchanged sources writes nothing, so `--check` failing means a document changed without the index being rebuilt. Treat it exactly like a stale fixture. `corpus/eval.py` must pass against both `corpus/index.json` and `corpus/index.fixed.json`: a case that passes against one and fails against the other is a property of the chunker, not the contract, and belongs in the evals instead.

The corpus carries a deliberate hindsight trap, `DRAFT-2601`, dated inside the live incident's window and naming a cause that was never established. It is the only document recent enough to catch a search that omits its time bound. Do not date it earlier, and do not remove it: without it an unbounded query looks correct and the archive becomes a back door to a confirmed cause.

The bridge view embeds a scripted correlator output in `correlation`, shaped exactly to the correlate task's output contract, so standalone assess runs and the governance demos stay deterministic; `demos/investigate.sh` replaces it with a live correlator run. The raw rows in `changes` feed the mock registry and the Scribe's timeline only. The commander never sees them: the typed output is the handoff.

The two `--demo` outputs are forcing inputs, not views of the incident: attribution is the bridge view plus scripted convergence pressure for the M4 governance demos (`demos/governance.sh`), mitigation is the directed production change the sandbox must block, and the same directive is the input the Scribe's `draft_change_record` task documents, which is why it carries an explicit empty `board`.

Each view contains only what had actually been collected by its `as_of` time, not what was obtainable. The D+1 view is nearly empty by design: two auto-closed problems, the metric series and the standing condition, with no incident, no evidence and no change query. Do not enrich it.

The bridge view is deliberately evidence-poor. The deciding evidence sits in `missing_evidence`, not `evidence`, so an agent cannot reason its way to a conclusion it should not be able to reach. **Do not move it.** If a spec appears to underperform because evidence is missing, that is the fixture working correctly.

---

## Before committing

1. `oa validate` passes on every spec touched
2. Fixture regenerated if the generator changed
3. No source material anywhere in the tree, including untracked files
4. No vendor named in a causal role
5. No commercial detail: no rates, revenue targets, client names or pipeline
6. Language matches the vocabulary above

## Style

Concise. No preamble. Comments explain why a constraint exists, not what the line does.