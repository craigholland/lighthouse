---
title: "Lighthouse Architecture Review Questions"
created_date: 2026-11-23
update_date: 2026-11-23
status: PROPOSED
---

# Lighthouse Architecture Review Questions

The [architecture](../architecture/proposal.md) and
[initial plan](../development/initial-plan.md) are drafts. Approval of one row
does not approve the remaining rows or authorize implementation. Record Craig's
resolution or explicit bounded delegation before turning affected tasks into Issues.

| ID | Status | Decision and recommendation | Gate affected |
| --- | --- | --- | --- |
| RQ-01 | RESOLVED | Craig accepted dedicated local Codex review sessions on 2026-11-23. Each receives durable Issue, PR and repository context; this desktop chat need not be resumed. SDK/runtime compatibility remains T01 evidence. | Codex adapter target |
| RQ-02 | RESOLVED | Craig approved one local Python process, TOML project profiles and SQLite for the internal workflow ledger on 2026-11-23, with GitHub authoritative for repository facts. Supported Python versions, dependency policy and detailed contracts still require their applicable task approvals. | Approved baseline for T00 and T05; task execution remains gated |
| RQ-03 | RESOLVED | Craig approved explicit Owner/Lead readiness, dependency-complete unblocked work, one active task, captured scope and verification, reauthorization after scope changes, deterministic priority/age/Issue-number selection, explicit Issue/work-order-to-PR binding and same-PR revisions on 2026-11-23. He delegated exact label names and Issue fields to Codex, now recorded in the [work intake contract](../development/work-intake.md). | Approved admission policy for T03/T04/T06; task execution remains gated |
| RQ-04 | UNPROVEN — delegation required | Authorize a bounded feasibility stage for T01/T02 and accept/revise its evidence before production dispatch. Recommend proving receipt recovery and Dot cloud-to-local behavior early. Any tunnel/plugin/access/cost change still needs approval of its concrete setup. | Gate A exit and T07/T08 |
| RQ-05 | OPEN — before live activation | Confirm Koios repository branches, separate workspace locations, labels, project verification contract and the controlled proof/demo targets. Recommend keeping its profile inactive until these are verified; use fakes for destructive or uncontrolled negative paths. | Live portions of T01/T02 and T09 |

## Established boundaries

The approved bootstrap and merged standards already establish separate Codex and
Dot identities/checkouts; Craig's merge authority; `development` for active work
and `main` for releases; mandatory independent review; one active implementation
task per project by default; no automatic merge; no next task before actual merge;
and durable, visible workflow transitions and failures.

The current basic GitHub protections do not establish named-reviewer or
owner-only merge enforcement. The proposed application safeguards and their
limits are stated in the architecture; a stronger platform enforcement mechanism
would be another reviewed decision.

## Approval record

On 2026-11-23, Craig resolved RQ-01 and explicitly approved the Python/TOML/SQLite
baseline in RQ-02. He also stated that he approved the then-current state of PR #2,
whose head was `c5b5e882b96ad1391a114b4d3683a173a1ed641b`. This records his
approval of that documentation state; it did not resolve the remaining questions,
authorize implementation, or authorize a merge.

Craig subsequently approved RQ-03 and delegated exact label names and Issue
fields to Codex on 2026-11-23. Codex exercised that delegation in the work intake
contract. RQ-04 and RQ-05 remain unproven or open; this approval does not authorize
their experiments or live activation.

The remaining detailed architecture, candidate tasks and execution permissions
are not yet approved. No orchestration implementation or initial implementation
Issue backlog has been started by this planning work. This decision-record update
changes the PR head; earlier review evidence must not be attributed to that new head.

Resolve questions iteratively. A later general expression of agreement must not
silently resolve an unproven capability, grant new access, or approve a release.
