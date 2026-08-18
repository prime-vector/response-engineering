---
source_uri: corpus://runbooks/container-resource-limits
source_family: runbook_procedure
licence: Synthetic, authored in this repository
recorded_at: 2026-01-12
record_status: filed
---

# Runbook: container memory limits against host memory

## Establish which memory ran out

A container restarted on reaching its memory limit and a host driven into
exhaustion produce similar words in a ticket and have almost nothing else in
common. Before anything else, establish which one happened. A container limit
is a ceiling somebody chose. Host exhaustion is the absence of one.

The distinguishing evidence is the host's own memory and swap during the
event. If they were flat, the host was never short of memory and no
host-level attribution is needed. If they were not, the container limit is a
detail and the host is the incident.

## Why the limit is usually the easier case

A limit bounds the consumer before the host feels it, which is what it is
for. The restart is loud, the blast radius is one workload, and the fix is
either a bound on what grew or a limit that matches the working set.

A host with no such ceiling gives none of that. The first process to ask for
memory that is not there fails, and it is rarely the process responsible.

## What this runbook does not cover

Hosts running a workload directly, without a container runtime. There is no
limit to read, the standing condition has to be established from the resident
set of the largest existing consumer, and the procedure is in the host memory
exhaustion runbook instead.
