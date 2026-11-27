---
title: "Dormant T07 Runtime Bindings"
created_date: 2026-11-27
update_date: 2026-11-27
status: DRAFT
---

# Dormant T07 Runtime Bindings

[Issue #10](https://github.com/craigholland/lighthouse/issues/10) selects the
concrete Windows STDIO and scoped GitHub bindings through the private
[runtime factory](../../src/lighthouse/runtime_bindings.py). Importing the
package or calling the factory does not start a process, use credentials or
make an HTTP request. There is no enabled run command, live profile, service,
secret discovery or general-purpose launcher.

The [Windows owner](../../src/lighthouse/adapters/codex/windows_session.py)
requires an explicitly approved executable and SHA-256, pinned public App
Server 0.171.0 protocol, the dedicated canonical workspace and exact HEAD,
local Git executable and canonical repository, private Codex home and only
allowlisted environment settings. It checks checkout state before open and
again before review. An owned suspended root enters a non-breakaway Job
before resume. Only the three selected child stdio handles are inherited.
Overlapped I/O is bounded by the original deadlines. Private stderr is
drained separately and never logged. Cleanup needs that retained root to be
signaled, its Job empty, and a bounded complete stdout drain. Kill-on-close
alone is not evidence. These mechanics use the established
[T01 ownership reference](../../experiments/codex-review/windows_job.py)
and CPython 3.14's Windows handle and overlapped primitives without importing
any experiment.

The [HTTP client](../../src/lighthouse/adapters/github/review_http.py) only
accepts its explicitly configured repository and PR. It uses the standard
library's certificate-verified GitHub API TLS connection, the pinned API
representation, injected repository-scoped bearer, fixed read endpoints and
one COMMENT request. It follows no redirects and never retries POST. A request
that outlasts its wait holds rather than replaying; a still-running transport
blocks another request on that instance. Historical lookup requires a
complete bounded page and exact receipt attribution. Credential values stay
out of the child environment, review input, status and diagnostics.

## Inert operator status

Supply the path locally, not in a shared transcript:

    python -m lighthouse status --ledger <existing-ledger> --project <owner/repo>
    python -m lighthouse status --ledger <existing-ledger> --project <owner/repo> --dispatch <id>

This opens the existing schema-v2 SQLite ledger read-only, selects the latest
accepted reservation/dispatch or the explicit dispatch, and reports bounded
identity and independent lifecycle facts. The selected dispatch retains the
Issue bound at admission, even after a new reservation. Current T04 decision
reason and numeric actor are separate; a current HOLD uses its recorded actor
for operator guidance rather than the pending action's usual role. The original
assignee of a pending dispatch remains visible across duplicate recommendations.
When that same action remains current, its assignee is the next actor even
though the latest observation issued no new recommendation. It cannot create, reset, migrate,
queue, dispatch or publish. Help, version and ordinary imports are inert.

## Verification and activation boundary

Ordinary tests exercise synthetic process/HTTP edges and temporary ledgers.
The gated native fixture is explicitly selected only after approval on Windows:
temporarily set LIGHTHOUSE_T07_OWNED_FIXTURE=1 and run
python -m pytest -x -q -s tests/test_codex_session.py::test_owned_windows_python_fixture,
with a 30-second invocation limit. Its two sequential cases use a fixed
harmless Python root and descendant, each within 10 seconds plus up to 3
seconds emergency teardown. It proves local pipe/Job behavior only; stop
after unexpected output, deadline or unconfirmed cleanup.

A future one-use smoke is only a proposal. Craig must separately approve the
exact repository/PR/head, current authorization, Lead publishing identity and
independently sourced bearer, pinned executable/hash and scoped workspace,
approved managed Codex home/account/model/retention, environment and owners.
Then attest those bindings, do one exact-head review, verify effective policy,
retained remote correlation and owned local shutdown, separately authorize
the exact COMMENT, and record or reconcile only its original receipt. Stop on
unknown acceptance or shutdown without a retry. No prior T01 allowance is
renewed; no hosted or real account behavior is proven by offline tests.
