---
title: "Offline Workflow Decisions"
created_date: 2026-11-26
update_date: 2026-11-26
status: APPROVED
---

# Offline Workflow Decisions

Call `Workflow(project).evaluate(state, snapshot)` in
`lighthouse.domain.workflow`. Each evaluation returns a reason, suggested next
actor, relevant supplied evidence IDs, and immutable successor state; it never
executes that recommendation. The caller supplies a coherent project-wide
monotonic observation version, explicit timezone-aware times, normalized
facts and actor attribution. For conflicting or unknown facts the caller must
not invent quiescence, verification, or effective approval.

| Evidence | Decision |
| --- | --- |
| Eligible authorized Issue and free project slot | Recommend implementation and retain its supplied work identity |
| Unknown acceptance, changed scope, or unrelated/closed-unmerged PR | Hold; do not free the slot or replace an accepted snapshot |
| Bound, non-draft PR and no unresolved execution | Recommend Lead review for its exact head |
| Effective Lead request for changes | Recommend revision on the same PR |
| Effective exact-head Lead approval and required verification | Await Owner merge; keep the slot |
| Actual Owner merge with exact prior approval and verification, and quiescent executions | Complete and release; retain independent reviewed-head and merge-result evidence in the decision |

Empty priorities use normal; ambiguous labels are ineligible, then creation
time and Issue number break ties. Duplicates and older versions are ignored;
the same action evidence is not recommended twice within a work order. A new
head waits for unresolved earlier review to stop. Changed scope requires
separately reconciled updated authority; evaluation does not overwrite a work
order in place.

Provider authentication and interpreting review effectiveness, persistence,
atomic reservation and dispatch, and effects are outside this increment.
The CLI remains inert. This does not implement or authorize any live operation.
