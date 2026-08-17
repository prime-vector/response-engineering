---
source_uri: corpus://runbooks/recovery-point-selection
source_family: runbook_procedure
licence: Synthetic, authored in this repository
recorded_at: 2026-01-12
record_status: filed
---

# Runbook: selecting a recovery point during an incident

## The window matters more than the age

A recovery point taken inside the affected window restores the condition along
with the host. The snapshot will restore cleanly, validate against every check
that does not look for the condition, and reproduce the incident.

Before selecting a point, establish when the condition began. If onset is not
known, treat every point after the first unexplained symptom as suspect.

## Rehearsal is not validation

A restore that completes is not a restore that works. Time the restore, then
run the workload's own checks against the restored copy. A rehearsal that
stops at "the restore completed" has measured the storage layer and nothing
above it.

Record the elapsed time against the stated expectation. A restore that takes
significantly longer than the expectation is a finding whether or not the data
is correct.

## What to record

The recovery point selected, the onset time it was checked against, the
elapsed restore time against the expectation, and what validation was run. A
rehearsal with no recorded validation is an untested assumption with a
timestamp on it.
