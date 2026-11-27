---
title: "Offline Reconciliation Cycle"
created_date: 2026-11-27
update_date: 2026-11-27
status: APPROVED
---

# Offline Reconciliation Cycle

The [coordinator](../../src/lighthouse/application/coordinator.py) performs
one explicit read/evaluate/record cycle. The
[GitHub observation source](../../src/lighthouse/adapters/github/observation_source.py)
passes normalized facts only. It requires the supplied context to match the
accepted durable binding and does not derive authority from provider text.

The caller supplies a stable observation revision and ordered version,
explicit time and, if considering a new reservation, a work-order ID.
Execution and verification are independent caller evidence. The ledger
records a digest of normalized cycle inputs for duplicate/conflict checks,
without storing raw provider responses. A replay uses the original
pre-transition work context and must match the original normalized evidence.
If facts changed, the caller must supply a new revision/version instead.

Provider reads finish before the ledger write. New implementation, review
or revision decisions record matching stable pending IDs in the same
expected-version transaction. Reconciled phases still persist when a repeated
action is suppressed. Duplicate, conflicting, stale and failed writes do not
report a new action. Incomplete observations preserve the last confirmed
durable phase and reservation and return a fixed hold reason. Intent status
is inspectable, never permission to execute it.

The reconciler itself does not dispatch, publish or merge. The separately
composed [dormant review-dispatch slice](review-dispatch.md) consumes committed
REVIEW intents, with fake I/O in integrated tests. No tested provider path is
live and no scheduling or CLI activation is supplied.
