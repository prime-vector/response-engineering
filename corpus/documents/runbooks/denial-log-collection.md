---
source_uri: corpus://runbooks/denial-log-collection
source_family: runbook_procedure
licence: Synthetic, authored in this repository
recorded_at: 2026-01-12
record_status: filed
---

# Runbook: collecting the security denial log

## What this evidence settles

A denial log names the source domain of each denial. That is what separates
one candidate process from another when several are plausible and none has
been ruled out. Without it, every candidate stays equally likely and the
investigation converges on whichever party has someone available to answer.

It is usually a single command and a few seconds of host access. The cost of
collecting it is almost never the reason it goes uncollected.

## Collect before suppressing

Deactivating the event dispatcher stops the denials reaching analysis, which
is often proposed as relief when a denial-analysis process is consuming CPU.

It also stops the log being collectable. If suppression is applied before the
log is taken, the evidence that would have identified the source is gone, and
no later collection recovers it. Collect first, then suppress if suppression
is still wanted.

## Runtime changes revert on reboot

Setting the enforcement mode at runtime does not change the boot
configuration. The host will return to its configured mode on the next
restart, which may be months away and will not be associated with this
incident by anyone who was not on the call.

Any proposal to change enforcement mode must state whether it is runtime only,
and any record of it must say the same.

## If the log cannot be produced

Record it as outstanding deciding evidence, name what each outcome would rule
in and rule out, and leave the hypothesis unresolved. A request that was made
twice and never satisfied is a finding about the investigation, and it belongs
in the record.
