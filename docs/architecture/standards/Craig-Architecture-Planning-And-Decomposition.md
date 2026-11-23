---
title: "Craig Architecture Planning and Decomposition"
created_date: 2026-11-21
update_date: 2026-11-21
status: APPROVED
tags: [work-decomposition, task-contracts, architecture-discovery, pull-request-scope, integration-ownership, code-shape]
---

# Craig Architecture Planning and Decomposition

Work decomposition is an architectural concern. It determines whether changes have clear ownership, integrate coherently, and remain understandable to reviewers. This guidance supplements [Craig Architecture](Craig-Architecture.md).

## Meaning at Each Level

| Level | Meaning and guidance |
| --- | --- |
| Epic | A coherent product, package, or milestone outcome with scope and non-goals. |
| Story | A feature or module increment translated into affected architectural boundaries and integration requirements. |
| Task | A bounded implementation objective with concrete surfaces, acceptance, verification, and handoff. |
| PR | A reviewable delivery unit that demonstrates the task's intended change. |

Use only the hierarchy useful to the current effort. The project binding determines branches, review cadence, and which aggregation levels exist. Folder names and ticket counts do not establish readiness.

## Discover Before Designing a Change

Inspect the relevant authoritative requirements, current code, configuration, tests, and local contracts. Record:

- Which capability and objective are being changed.
- Existing owners and public surfaces to reuse, modify, or extend.
- Why a new object, service, schema, or module is necessary if one is proposed.
- Parallel abstractions or duplicate state that must not be introduced.
- Affected dependencies, integration ownership, and unresolved inputs.

Assess the actual surfaces needed by the objective. A generic assertion that the architecture was reviewed is insufficient.

## Task Contract

A worker-ready task should state:

1. Objective and authoritative source references.
2. In-scope behavior, non-goals, and excluded surfaces.
3. Expected new and changed files or a bounded surface family.
4. Existing contracts to preserve and any permitted exploratory simplification.
5. Acceptance criteria, including relevant negative paths and invariants.
6. Applicable local contracts and runnable verification commands.
7. Branch/PR target, integration or review owner, and handoff requirements.
8. Open decisions, stop conditions, and any specifically delegated consequential actions.

Keep implementation detail proportionate to the task. A short issue can satisfy this contract if it names concrete requirements and links their owners.

## Reviewable Size

Useful planning heuristics are PRs below roughly 500 changed code lines, tasks within about five initial PR slices, stories within about ten tasks, and epics within about five stories. These are reviewability prompts rather than quotas. Documentation, generated files, and coherent bootstrap changes require judgment.

Split work by meaning and ownership. Avoid several tasks independently creating the same file, many changes converging on one growing hotspot, or unrelated implementation lanes hidden inside one assignment. Name the parent integration owner when several child tasks contribute to a capability.

## Task Review Boundary

When a task contains several internal slices, use a task feature branch and task PR as its coherent review and handoff boundary. Keep the PR body aligned with the current objective and delivered behavior.

Before task handoff, check the full task change, resolve review findings, refresh affected contracts, and run the applicable verification. Inspect the immediate periphery needed to assess integration. Checks against only the last small slice do not establish correctness of the assembled task.

Proceed to another task according to the authorized sequencing and parallelization plan. The project binding determines whether internal slice branches and intermediate merges are useful or authorized.

## Final-Head Freshness

Identify the checked commit and the current review head. If source, tests, configuration, or governing requirements change afterward, assess which checks and review must be refreshed.

An evidence-only change still needs classification. Do not claim that an earlier pass applies to a later implementation without inspecting the delta. Exact packet formats belong to a project verification contract when that project needs them.

## Code-Shape Assessment

Planning and review should look for broad folders, oversized files, weakly cohesive helpers, circular dependencies, and public contracts that are difficult to explain. Consider a focused object or module before adding another layer of helpers.

Identify local `__ai__.md` files affected by architectural changes. Reconcile their current responsibilities, exports, dependencies, and verification in the same delivery unit. Updating a timestamp alone is not a contract review.
