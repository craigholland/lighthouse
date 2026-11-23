---
title: "Craig Architecture AI Contributor Guidance"
created_date: 2026-11-21
update_date: 2026-11-21
status: APPROVED
tags: [ai-contributors, architectural-review, local-contracts, task-intake, evidence, scope-discipline]
---

# Craig Architecture AI Contributor Guidance

AI contributors apply [Craig Architecture](../Craig-Architecture.md) through explicit context, bounded changes, and honest verification. A fresh session should be able to reconstruct its assignment from durable sources.

## Orientation

Read the governing architecture, project development profile, assigned work, and nearest local `__ai__.md`. Read relevant parent contracts and language guidance. Identify the actual repository, branch, PR target, source owners, and verification commands before mutation.

Use chat context to assist orientation. Preserve durable scope, decisions, acceptance criteria, and handoff state in the appropriate repository or task surface.

## Before Implementation

- Identify the layers and concepts affected.
- Distinguish exploratory structures from stable rules.
- Search existing owners, callers, tests, configuration, and composition before adding a new abstraction.
- Choose the smallest semantically meaningful change that satisfies the task.
- Inspect target modules for size, cohesion, helper depth, and dependency problems.
- Surface conflicting requirements and genuinely missing decisions; continue independent authorized work when possible.

## During Implementation

Preserve inward dependency direction and translate external representations at boundaries. Keep stable rules and authoritative state with their owners. Supply required dependencies explicitly.

Maintain task scope. Unrelated cleanup, new features, or changes to design decisions need their own scope rather than being bundled into a convenient edit. Existing user authorization remains valid for necessary in-scope work.

## Reconcile Local Contracts

Read each affected section as a whole. Update current purpose, exports, file responsibilities, dependencies, cross-folder assumptions, and verification when their meaning changes.

Delete or move stale statements. Keep unresolved present limitations in Known Gaps. Completed tasks, reviews, and release history belong in delivery records. A new bullet or refreshed verification timestamp does not by itself make a local contract current.

## Verification and Review

Run the actual project verification contract. Record exact commands, working directory, results, and the checked commit when available. Explain skipped or blocked checks without relabeling them as passes.

Inspect changed behavior and relevant neighboring context. Tests and generated artifacts can support a review, but do not replace reasoning about invariants, public contracts, or actual caller-to-implementation wiring.

After changes following review, assess evidence freshness and rerun the affected checks. Do not attribute readiness to a commit that was not checked.

## Handoff

State the objective, actual changes, PR and head, verification performed, unresolved findings, next actor, and expected action. Keep review, merge execution, release, and Owner decisions distinct according to the project binding.

Do not claim independent QA for self-review. If the same person or agent holds several responsibilities, make the active responsibility and verification limits explicit.

## Drift Signals

Look for core code importing framework or provider shapes; policy hidden in orchestration; competing canonical state; missing or stale contracts; broad folders; giant files; fragile helper chains; and plans with overlapping ownership.

When a signal matters to the current task, correct it within authorized scope or report the concrete issue and owner. Avoid quietly normalizing it as an acceptable permanent boundary.
