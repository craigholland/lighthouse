---
title: "Lighthouse Work Intake Contract"
created_date: 2026-11-23
update_date: 2026-11-25
status: APPROVED
---

# Lighthouse Work Intake Contract

Craig approved the admission policy in RQ-03 on 2026-11-23 and delegated exact
label names and Issue fields to Codex. Codex selected the conventions below under
that delegation. This contract defines future behavior; it does not authorize
implementation, create labels or templates, or publish an implementation backlog.
The [initial plan](initial-plan.md) and its remaining gates still apply.

## Admission and authorization

An eligible Issue is open, explicitly authorized by the configured Owner or Lead,
unblocked, dependency-complete, and has the required task fields. The project must
have no active task. Dot cannot authorize its own implementation work.

The [recovery amendment](initial-plan.md) takes effect after its documentation
PR merges. Its Owner-approved parking exception for experimental PR #15 permits
the next bounded offline task without merging that experiment. This is development
sequencing, not a runtime reservation-release feature: it cannot bypass active or
uncertain executions, dependencies, fresh readiness or consequential-action gates.
Ordinary implementation tasks still wait for the preceding PR's actual merge;
there is one implementation writer. Parking alone never marks a dependency complete.

The GitHub adapter must verify the readiness event's numeric actor identity and
that it covers the current task fields. Issue text claiming approval is not
authorization. If authority or scope freshness cannot be established, hold for a
fresh Owner/Lead readiness event rather than guessing. Removing and reapplying
the ready label is the explicit way to renew that event.

Admission captures the accepted task fields, verification requirements, source
references, authorizing event and profile fingerprint in the work order. Changed
scope pauses further dispatch until renewed authorization; it never silently
replaces an active worker's instructions or starts another worker. Preserve the
reservation and reconcile any existing execution.

## Label mapping

These are the default names in a project profile; another repository may map
equivalent names without changing core policy.

| Label | Meaning |
| --- | --- |
| `lighthouse:ready` | Owner/Lead authorization of the reviewed task; all other eligibility checks still apply |
| `lighthouse:blocked` | Blocks admission regardless of readiness |
| `lighthouse:priority:high` | First priority among eligible Issues |
| `lighthouse:priority:normal` | Normal priority; also the default if no priority label is present |
| `lighthouse:priority:low` | Last priority among eligible Issues |

Allow at most one explicit priority label. Conflicting priorities require
correction before admission. Readiness review covers priority; a changed priority
needs Owner/Lead confirmation. Within a priority, sort by creation time ascending,
then Issue number ascending. Labels never prove implementation, review or merge.
The runtime's derived-metadata writer cannot grant readiness through its contract.

## Required Issue fields

Use these exact level-two Markdown headings, once each. Content may link to
versioned authoritative detail; required fields cannot contain unresolved choices
that the task needs in order to proceed.

| Heading | Required content |
| --- | --- |
| `Objective` | Concrete outcome and why it is needed |
| `Sources` | Authoritative requirements and applicable local contracts |
| `In scope` | Authorized behavior and boundaries |
| `Out of scope` | Exclusions, preserved contracts and limits on exploratory simplification |
| `Expected surfaces` | Files or bounded surface families expected to change |
| `Acceptance criteria` | Observable results, relevant negative paths and invariants |
| `Dependencies` | `None`, or fully qualified `owner/repository#number` references and their completion evidence |
| `Verification` | Exact commands, repository-relative working directory, required evidence and limits on live actions |
| `Stop conditions` | Missing inputs, conflicting authority and actions requiring further approval |
| `Handoff` | Implementer, independent reviewer, expected PR base and required evidence, consistent with the project profile |

Repository identity, actors, workspaces and branch policy come from the validated
profile. Issue fields cannot override them. Keep credentials and real machine
paths out of these fields. New templates must not automatically apply readiness.

## Dependency evidence

A managed dependency requires a verified merged Lighthouse run. Closing an Issue
or asserting completion in its body is insufficient. An unmanaged dependency
requires an explicit Owner/Lead resolution before admission.

For an unmanaged dependency, its entry in `Dependencies` links to an Owner/Lead
comment on the candidate Issue containing these exact fields and a reason:

```text
Lighthouse-Dependency: owner/repository#123
Lighthouse-Resolution: satisfied
Reason: explanation of the dependency's resolution
```

Verify the comment's author, target Issue, dependency reference and current
content against provider data; capture its ID and observed revision/fingerprint.
A copied assertion, missing/deleted evidence, wrong actor or changed evidence
requires reconciliation. The comment resolves only that dependency, not readiness.

## Issue-to-PR binding

Dot's PR body contains these top-level fields exactly once:

```text
Lighthouse-Issue: owner/repository#123
Lighthouse-Work-Order: <opaque ID issued by the ledger>
```

Verify both fields against the accepted work order, configured implementer,
repository and integration branch. Do not bind an unrelated PR from a coincidental
mention, closing keyword or completion receipt alone. Revisions use the same PR
and work-order ID; each distinct dispatch still has its own stable dispatch ID.
Ambiguous or conflicting links hold the task for attention.

T03 will introduce templates and validation; T04 and T06 will verify policy and
provider evidence. These conventions add no merge or release capability.
