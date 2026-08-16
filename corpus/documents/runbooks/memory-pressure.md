---
source_uri: corpus://runbooks/memory-pressure
source_family: runbook_procedure
licence: Synthetic, authored in this repository
recorded_at: 2026-01-12
record_status: filed
---

# Runbook: host memory exhaustion

## When this applies

A host is reported as memory exhausted, swapping, or showing an elevated page
fault rate. It applies whether or not an alert has fired, and whether or not
anyone has acknowledged one.

## Establish the standing condition first

Find the resident set of the largest existing consumer and compare it against
total memory. A host that normally runs at ninety per cent of memory is not
the same incident as a host that normally runs at forty and has just moved.

The standing condition is not the cause. It is what decides whether a new
consumer of a given size is enough to matter. Record it as a condition, not as
a finding.

## Attribute the memory before changing anything

Take a process-level snapshot while the host is still exhausted. Resident set
by process, ordered, with start times. A snapshot taken after a restart proves
nothing, and the restart is the most common way this evidence is destroyed.

If the snapshot cannot be taken, record that as a gap rather than proceeding
as though the attribution is known.

## Distinguish a new consumer from a changed one

Two shapes present identically. Either a process that was not there before has
arrived, or an existing process has changed behaviour. The start time in the
process snapshot separates them, and they have nothing in common beyond the
symptom.

A new consumer points at change history. A changed consumer points at the
dependency or destination that changed underneath it.

## What not to do

Do not raise a memory limit to relieve pressure before the consumer is
attributed. Raising a limit consumes the headroom that a correct attribution
would need, and it can convert an intermittent condition into a permanent one.

Do not restart the workload as a first step. It resolves the symptom and
destroys the evidence in the same action, which is how an incident gets closed
with the cause unconfirmed.
