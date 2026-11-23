---
title: "Lighthouse Architecture Review Questions"
created_date: 2026-11-23
update_date: 2026-11-23
status: PROPOSED
---

# Lighthouse Architecture Review Questions

The [architecture](../architecture/proposal.md) and
[initial plan](../development/initial-plan.md) await overall adoption. Craig has
resolved the five policy questions below; proof evidence, concrete live targets
and final package approval remain separate gates. Individual policy approvals
do not authorize implementation or publication of its Issue backlog.

| ID | Status | Decision and recommendation | Gate affected |
| --- | --- | --- | --- |
| RQ-01 | RESOLVED | Craig accepted dedicated local Codex review sessions on 2026-11-23. Each receives durable Issue, PR and repository context; this desktop chat need not be resumed. SDK/runtime compatibility remains T01 evidence. | Codex adapter target |
| RQ-02 | RESOLVED | Craig approved one local Python process, TOML project profiles and SQLite for the internal workflow ledger on 2026-11-23, with GitHub authoritative for repository facts. Supported Python versions, dependency policy and detailed contracts still require their applicable task approvals. | Approved baseline for T00 and T05; task execution remains gated |
| RQ-03 | RESOLVED | Craig approved explicit Owner/Lead readiness, dependency-complete unblocked work, one active task, captured scope and verification, reauthorization after scope changes, deterministic priority/age/Issue-number selection, explicit Issue/work-order-to-PR binding and same-PR revisions on 2026-11-23. He delegated exact label names and Issue fields to Codex, now recorded in the [work intake contract](../development/work-intake.md). | Approved admission policy for T03/T04/T06; task execution remains gated |
| RQ-04 | RESOLVED — evidence pending | Craig approved the bounded feasibility-first stage as part of the initial plan on 2026-11-23: T00 foundation, T01 dedicated Codex review proof and T02 Dot cloud-to-local proof. Production dispatch waits for his acceptance of the evidence; inconclusive results return for a revised design. This approves planned sequencing, not execution, proven capability, new access/cost or a live target. | Approved Gate A sequence; evidence acceptance still gates T07/T08 |
| RQ-05 | RESOLVED — activation pending | Craig approved controlled Lighthouse Issues and Dot-authored PRs for integration proofs, with ordinary review and his merge authority preserved, on 2026-11-23. Koios remains the first real configured project and stays inactive until its profile is verified. Codex verifies branches, separate checkouts, identities, labels and verification commands, keeping machine configuration private. Concrete live targets require Craig's separate approval before execution; disruptive failure cases use fakes. | Approved rollout policy; verified bindings and live-target approval still gate T01/T02/T09 |

## Package approval and execution gates

The five policy decisions are resolved. The next decision is Craig's formal
adoption of the architecture and T00–T09 initial plan as a whole. The plan proposes
a bounded delegation for Codex to select compatible project-local runtime and
dependency pins, define task contracts and publish their Issues within that
approved scope. That delegation is proposed, not yet granted.

Overall adoption would not approve future proof results, a concrete live target,
new connectivity/access/cost, Koios activation, a PR merge or a release. Those
remain explicit gates at the relevant task. Unproven capability is evidence to
obtain during the approved feasibility stage, not a reason to assume it works.

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
contract. That decision did not authorize integration experiments or live activation.

Craig then approved the feasibility-first stage as part of the initial plan
(RQ-04) on 2026-11-23. The approval covers the planned T00–T02 sequence and its
evidence gate. It does not establish integration capability or authorize execution
before final architecture/plan approval. Concrete connectivity, permissions,
costs and live test targets still require approval.

Craig subsequently approved the RQ-05 rollout policy on 2026-11-23, explicitly
retaining separate approval of concrete live targets before execution. This
resolves the rollout decision, not the future verification of a profile or its
activation.

The remaining detailed architecture, candidate tasks and execution permissions
are not yet approved. No orchestration implementation or initial implementation
Issue backlog has been started by this planning work. This decision-record update
changes the PR head; earlier review evidence must not be attributed to that new head.

Resolve questions iteratively. A later general expression of agreement must not
silently resolve an unproven capability, grant new access, or approve a release.
