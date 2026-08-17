---
source_uri: corpus://runbooks/change-correlation
source_family: runbook_procedure
licence: Synthetic, authored in this repository
recorded_at: 2026-01-12
record_status: filed
---

# Runbook: correlating change against onset

## Run this first, not last

Package history and change records against the onset time is a lookup, not an
investigation. It costs one command and one registry query. It is routinely
run hours into a bridge, after the expensive hypotheses have already been
formed and defended.

Run it before the first hypothesis, so the board starts from what changed
rather than from what someone remembered.

## Correlation is not attribution

The most recent change on a host is the most available explanation, not the
most likely one. Availability is why the newest component gets named first,
and why it is often the one with a representative on the call.

A change that correlates in time earns a place on the hypothesis board with
its confidence stated and a falsifying test attached. It does not earn a
cause.

## Absence of change is not absence of change

Components that update themselves outside the package manager do not appear in
package history with a current timestamp. An empty result means the query
found nothing, which is not the same as nothing having happened.

Record the query, its window, and what it cannot see. A correlation report
that does not state its blind spots reads as complete when it is not.

## What to carry forward

For each correlated change: what changed, when, who implemented it, the
interval to onset, and the single piece of evidence that would rule it out.
The interval alone is not a ranking.
