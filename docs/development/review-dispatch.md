
---
title: "Dormant Codex Review Dispatch"
created_date: 2026-11-27
update_date: 2026-11-27
status: DRAFT
---

# Dormant Codex Review Dispatch

[Issue #10](https://github.com/craigholland/lighthouse/issues/10) implements the
offline **codex-dispatch-v1** scope. The explicit
[composition](../../src/lighthouse/review_composition.py) connects the existing
[reconciler](reconciliation.md) and [SQLite ledger](ledger.md) to a separate
[Codex wire worker](../../src/lighthouse/adapters/codex/stdio.py) and
[GitHub COMMENT publisher](../../src/lighthouse/adapters/github/review_publisher.py).
The two effect boundaries are injected and are not selected by the package.
The installed CLI, imports, help and version remain inert.

## Claim and recovery

The caller names a committed REVIEW intent and supplies its accepted normalized
work binding and exact GitHub head. The dispatch service retains the original
order, intent, target and context digest before submitting through the injected
non-blocking queue. The worker must win a second compare-and-set on the same
attempt before any runtime work. Admission and queue consumption both require
the latest committed T04 disposition and exact recommendation to be current
inside the same writer transaction. A newer HOLD leaves the original intent
and any unconsumed claim intact and authorizes no runtime or publication. Only
a later valid T04 observation can make that exact review eligible again. A
callback that already started cannot consume the claim a second time. Unsupported
intent types, a missing commit, a changed binding, a stale head, or a separate
unresolved attempt cannot start a review. All external work is outside SQLite
write transactions. This layer never changes the workflow phase or releases work.

A reserved attempt without durable acknowledgement is an unknown, not a retry.
Once acknowledged, only its exact thread/turn may supply completion. An
approval request identifies Craig. The durable receipt reports approval
attention, observed or unconfirmed remote completion, and local shutdown
separately across restart. Observed remote completion with unconfirmed local
shutdown still cannot publish. Status exposes bounded normalized identities and
fixed reasons; it never includes prompts, output, provider payloads or machine
paths. No attempt expires or is automatically replaced.

Publication requires exact usable output, completed owned cleanup, a fresh head
and trusted Lead authority. The distinct publication marker is committed before
the one COMMENT POST. A lost response or failed receipt save can only query that
original marker, actor, head and output digest; the lookup never POSTs. After the
head advances it can reconcile an existing exact historical receipt but cannot
publish onto the new head. Completion output is transient. If it is lost before
a publication attempt, retain the completed status and hold until the same
attributed text is available; no thread-history fallback or second review.
COMMENTED is not APPROVED. Existing T04 verification, effective Lead review
and actual owner-merge rules are unchanged.

## Compatibility and limits

The worker uses the public App Server stdio/JSONL contract at runtime 0.171.0, as
documented by the [T01 evidence](../../experiments/codex-review/README.md). It
checks the independently attested checkout before launch and again before
review, then checks the effective read-only/no-network/never-approve session
policy. It retains bounded completion events that precede acknowledgement and
requires an ordered exact-thread/turn enter, exit, clean terminal, and final
owned cleanup without contradictory trailing evidence. The shutdown witness
requires both owned root exit and an empty Job; local shutdown does not establish
remote cancellation. Unknown work never starts again automatically.

The session owner must enforce the original bounded execution/cleanup deadlines,
attest the dedicated Windows workspace and pinned runtime, and supply verified
root/Job shutdown and bounded contiguous transport. The publishing owner must
select a separately authorized allowlisted target and immutable Lead identity
and supply bounded GitHub I/O. Tests inject these boundaries. They do not
prove native containment, provider compatibility, a real account or model,
credential isolation on a live machine, externally effective policy, or a
hosted COMMENT. The [dormant concrete bindings](runtime-bindings.md) supply an explicit session owner and review client.
There is no operational launch command, usable live profile or credential discovery. Any actual activation
requires separate owner-approved target, runtime, auth/retention and operational
evidence. This work does not reopen the T01 trial, T02, or PR #15.

## Foreground formal outcomes

The [one-shot operator runner](review-runner.md) reuses this durable attempt
boundary. An explicitly authorized structured APPROVE or REQUEST_CHANGES is
bound alongside its body digest before publication; the exact receipt state
must agree. Prior records with no event remain COMMENT. A confirmed receipt
alone never supplies missing implementation verification or merge authority.
