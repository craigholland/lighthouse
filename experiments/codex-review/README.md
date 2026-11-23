# Codex review experiment: T01 Phase A

This is an offline proof for [Lighthouse issue #4](https://github.com/craigholland/lighthouse/issues/4).
It proves recovery behavior with synthetic data, not an actual Codex run,
GitHub review, production adapter, or acceptance of Gate A. There is no live
command, launcher, credential reader, approval callback, or GitHub client.

## Run

From the repository root, use the
[experiment verification contract](../../docs/development/verification-contract.md)
with existing Windows AMD64 CPython 3.14.x. The only runnable experiment
commands are `proof.py --help` and `proof.py --dry-run`. Dry-run drives the
actual recovery code against one synthetic target and deletes its temporary
journal when it exits. No arbitrary repository, head, prompt or provider
configuration is accepted.

## Offline evidence and limits

- The experiment lock has SDK `openai-codex==0.171.0` and bundled runtime
  `openai-codex-cli-bin==0.171.0` plus the complete Windows tool and dependency
  pins. The upstream SDK wheel SHA-256 is
  `3c9578416acddd8746224cfd6d9d3f4ac08d798b20c56065a337de72eafa6dd6`; the
  Windows AMD64 bundled runtime wheel SHA-256 is
  `1e39d4236aede93a0c3f452a6c10a65f86b5f2c2fcbedbcce546e1f80b61729b`.
  There is no installed CLI override. These are publisher digests, not a
  hash-locked requirements file.
- Intent is durable before the synthetic start; an accepted handle stores the
  exact thread and turn separately. Repeat the same dispatch to retrieve the
  record, not launch. Reject a changed context/head under the same dispatch ID.
  A restarted harness may inspect only a known run. Otherwise it holds for Lead.
- Completion is distinct from publication. A current attributed target is
  required before any fake COMMENT attempt. The stable marker, numeric actor
  bindings, repository/base/PR and head must match the returned receipt.
  Uncertain fake POST acknowledgement or loss of local receipt persistence
  permits marker lookup, not another fake POST.
- Timeouts, stale heads, unavailable capability, duplicate/out-of-order
  observations and uncertain cancel have conservative outcomes. A permission
  request holds for Craig. The journal is single writer, scratch-only and
  not a production ledger or a power-loss/concurrent writer guarantee.
- `sdk_schema.py` checks SDK response data without creating a client.
  It reads `openai_codex.types.TurnCompletedNotification` and
  `ThreadReadResponse`, correlates synthetic IDs and maps typed states.
  Raw provider text, payloads and paths do not become audit output.
- The CLI safety tests place import and audit fences around import/help/dry-run
  and disallowed live arguments; this is regression coverage, not an OS sandbox.
  The ordinary suite needs no credentials, network or Codex process.

## Candidate bridge for separate Phase B approval

The [official SDK guide](https://learn.chatgpt.com/docs/codex-sdk),
[App Server protocol](https://learn.chatgpt.com/docs/app-server) and pinned SDK
source describe these surfaces. Nothing below is called by this experiment.

| Candidate | Evidence or use |
| --- | --- |
| `Codex.thread_start` | Fresh Lead context with explicit `Sandbox.read_only` and `ApprovalMode.deny_all`; confirm effective sandbox and existing managed sign-in/model policy, never inherit defaults. |
| Typed low-level `request` with `review/start` | The installed low-level CodexClient exposes `request(method, params, response_model=...)`; protocol response has `reviewThreadId` and `turn.id`. Store correlated IDs only after acknowledgement. A protocol request ID is not a durable idempotency key. |
| `thread_read(..., include_turns=True)`, `turn/interrupt`, `turn/completed` | Reconcile a known thread/turn, never replay an uncertain launch. An interrupt response alone is not interruption evidence; require matching terminal observation. |
| `item/completed` with `exitedReviewMode` | Candidate end-of-review output; not a GitHub receipt or authorization. |
| `ExternalMessage` and repository instructions | Keep Issue/PR content as external data under controlling instructions; never treat it as permission, readiness or a scope change. |

Sandbox enforcement, account/model/runtime availability, approval handling,
and exact review-output attribution remain unproved on a real run. Any
unavailable or mismatched setting is a stop, not a reason to change permissions,
use auto approval, reuse a chat, or add a billing path. The model context never
receives GitHub App credentials; publication, if separately approved, is
attributed through a separate narrowly scoped Lead publisher.

## Phase B approval-packet template (disabled, not authorization)

| Field | Required before any live action |
| --- | --- |
| Owner approval and renewed readiness | Craig's concrete approval reference and Lead's renewed attributed readiness covering these exact fields. |
| Exact test target | One Lighthouse PR URL, exact head, repository/base, expected Dot author and approved Issue/repository instruction snapshot. Recheck head and authority immediately before any effect. |
| Execution boundary | Separate Lead checkout/context, selected pinned SDK and bundled runtime, effective read-only access, denial of automatic escalation, existing approved managed sign-in/model policy, concrete maximum calls and elapsed time. No fallback identity or settings. |
| Receipt/recovery | Private receipt location, bounded stable dispatch marker, thread/turn IDs if confirmed, final status and interruption/hold evidence. No automatic replay if acceptance is unknown. |
| Only proposed GitHub action | One exact-head COMMENT review as the verified Codex App, via separate scoped publisher; no approval, change request, merge or release. Observe and reconcile its attributed review ID. |
| Evidence and stopping | Report real provider/model/runtime and exact-head receipts only if executed and verified. Do not admit T02; Gate A acceptance and merge remain Craig's. |

This table is not a live configuration. The template cannot enable a run.
