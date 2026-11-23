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
| RQ-02 | OPEN — Craig | Approve one local Python process, TOML profiles and SQLite for the internal workflow ledger, with GitHub authoritative for repository facts. Recommend this minimum baseline; an append-only file journal would need additional transaction/recovery work. The core retains a storage contract. | T00 runtime choice and T05 persistence |
| RQ-03 | OPEN — Craig | Approve or amend the proposed ready-label/actor, captured-scope, dependency, priority and Issue-to-PR binding conventions. Recommend Lead/Owner authorization, explicit dependency evidence, immutable accepted work snapshots and attributed linked PRs. Exact label names and field representation can be explicitly delegated to Codex before T03/T06. | Profile and admission contracts |
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

As of 2026-11-23, Craig has requested this proposal and resolved RQ-01. The
detailed architecture, remaining recommendations, candidate tasks and execution
permissions are not yet approved. No orchestration implementation or initial
implementation Issue backlog has been started by this planning work.

Resolve questions iteratively. A later general expression of agreement must not
silently resolve an unproven capability, grant new access, or approve a release.
