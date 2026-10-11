# Spec variants the committed judgement records ran on

Copies of `.agents/precedent-analyst.yaml` that differ in `model` and
`reasoning_effort` and drop the comment block that argues the shipped model
choice, and in nothing else, kept so a record under `../results/` that names one of
them by fingerprint points at a file a reader can open. They are inputs to a
measurement, not specs the demos run: `oa validate` passes on them, and
`checks/contract_invariants.py` reads `.agents/` only, so a drift here is
caught by the fingerprint in the record and nowhere else. Regenerate one by
copying the shipped spec and changing those two keys; never edit it in place
under a record that cites it.
