# Codex review experiment: T01 Phase A

This experiment is the offline-verified preparation for [Lighthouse issue #4](https://github.com/craigholland/lighthouse/issues/4).
It proves recovery behavior with synthetic data, not an actual Codex run,
GitHub review, production adapter, or acceptance of Gate A. The opt-in adapters are implemented but live activation remains held.

## Run

From the repository root, use the
[experiment verification contract](../../docs/development/verification-contract.md)
with existing Windows AMD64 CPython 3.14.x. The only authorized preparation verification commands are `proof.py --help` and `proof.py --dry-run`. Dry-run drives the
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
  permits marker lookup, not another fake POST. A stale target does not erase
  the persisted attempt. The original attributed receipt can be reconciled
  separately without treating the current stale target as ready or posting again.
- Timeouts, stale heads, unavailable capability, duplicate/out-of-order
  observations and uncertain cancel have conservative outcomes. A permission
  request holds for Craig. The journal is single writer, scratch-only and
  not a production ledger or a power-loss/concurrent writer guarantee.
- `sdk_schema.py` checks SDK response data without creating a client.
  It reads `openai_codex.types.TurnCompletedNotification` and
  `ThreadReadResponse`, correlates synthetic IDs and maps typed states. Thread-level approval and
  system errors hold for the owner or Lead, respectively. In-progress turns
  do not clear a hold unless their thread is actively running without flags.
  Raw provider text, payloads and paths do not become audit output.
- The CLI safety tests place import and audit fences around import/help/dry-run
  and disallowed live arguments; this is regression coverage, not an OS sandbox.
  The ordinary suite needs no credentials, network or Codex process.


## Offline supervisor and authorization preparation

The preparation contract is [Lead's pinned clarification](https://github.com/craigholland/lighthouse/issues/4#issuecomment-7116121458).
This change exercises the fail-closed control and authorization boundaries
without authorizing an actual live invocation.

- `supervisor.py` drives three injected job roles on one monotonic budget:
  verifier cutoff 30s; interrupt 780s; force review 810s; review shutdown and
  latest publication start 840s; force publisher 870s; hard failure at 900s
  without confirmed local shutdown. A control error prevents stage advancement
  but keeps bounded local force/observation active until cleanup is confirmed
  or the hard deadline expires. The parent only observes or controls owned jobs.
- `windows_job.py` is currently wired only to a fixed, harmless Python
  fixture for native verification, never an arbitrary command or a PID. The
  native test observes the worker plus two descendant levels, forcibly
  terminates only the owned job, and verifies the retained worker handle is
  signaled and job active count is zero. Local process shutdown cannot prove
  a provider stopped; unknown remote disposition cannot be replayed.
- `authorization.py` checks a strict private packet plus a structured,
  authenticated exact-comment attestation and fresh exact PR facts through
  a trusted read-only transport boundary. Canonical SHA-256, unedited and
  unexpired matching scope, exact numeric Lead/App identity and current PR
  head are mandatory. Missing App attribution is a hold. It never resolves
  a real transport, credentials, or a caller-supplied host. The canonical
  private claim consumes the authorization's one launch allowance.
- Original-head COMMENT receipt lookup is independent of current-head
  freshness; a stale-target hold may keep historical attributed evidence
  but cannot issue a second POST or advance the task.


## Prepared opt-in composition (live execution remains held)

The implementation now connects the actual adapters, but the installed
Codex client, provider and GitHub write path have **not** been exercised.
Ordinary import, help and dry-run do not construct a client, retrieve a
credential or start a child job. Only a separately selected Lead operator
invocation may enter the verifier; no committed configuration enables it.

- `live.py` validates a separately configured private file and its fixed
  sibling packet, context and instruction files before creating a child
  job. The canonical packet binds the exact invoked command, private receipt
  root, context/instruction hashes, immutable target and expiry. An incomplete
  local file is not approval.
- `live_stage.py` assigns verifier, review, fresh re-verifier and publisher
  roles to separate owned jobs and exchanges bounded, private challenge-bound
  signals. The review may not dispatch until the independent re-verifier
  rechecks the current attestation and exact head. The publisher cannot
  start until identified review completion, worker exit and zero active
  processes are confirmed. Unknown shutdown blocks advancement.
- `sdk_worker.py` defers construction of the exact pinned SDK and bundled
  runtime until the contained review role. It requires the existing
  managed sign-in from a separately configured Codex home, verifies returned
  account/model/provider, workspace, exact Git head and effective read-only
  sandbox/approval behavior. External Issue/PR data cannot grant authority.
  The model worker never receives a GitHub credential or its path.
- `github_transport.py` uses fixed GitHub API origin, distinct least-privilege
  installation-token roles, bounded transport, numeric App attribution and
  exact immutable target checks. Publisher authorization is renewed before
  its one COMMENT attempt. The canonical claim and separate durable COMMENT
  intent survive restart; uncertain POST permits only an attributed lookup
  of the original attempted head and cannot become a new POST.
- Review interruption is best-effort within the one global 900-second
  budget. Local Job termination cannot establish provider-side cancellation.

### Disabled final execution packet (template only)

Lead must privately supply the canonical packet and operator configuration,
a separate verified checkout and managed Codex home, fresh role-specific
short-lived Lead App JWT sources for the verifier and later publisher,
an existing private receipt directory, and a canonical absolute path to the
existing trusted Git executable in the private operator `git_executable`
binding. The exact command and SHA,
context hashes, managed account/model, access settings, time limits, and
receipt binding must be completed and independently reviewed. Craig's
approval of that final SHA/packet and a new attributed Lead attestation
are still required. No sample credentials, operator paths, or approved
live command are committed. Missing, edited, stale or unattributed
approval holds; absent metadata is never inferred from a login or file.

## Candidate bridge surfaces (not exercised live)

The [official SDK guide](https://learn.chatgpt.com/docs/codex-sdk),
[App Server protocol](https://learn.chatgpt.com/docs/app-server) and pinned SDK
source describe these surfaces. None of these provider operations was executed during offline verification.

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
| Private history retention | Explicit owner approval for one fresh non-ephemeral thread in the dedicated private Codex home. Disclose that it may contain the approved input and output; identify the access and retention/deletion plan in the exact private packet. Never inspect existing sessions, publish raw history, or reuse the home/thread as a review target. |
| Receipt/recovery | Private receipt location, bounded stable dispatch marker, thread/turn IDs if confirmed, final status and interruption/hold evidence. No automatic replay if acceptance is unknown. |
| Only proposed GitHub action | One exact-head COMMENT review as the verified Codex App, via separate scoped publisher; no approval, change request, merge or release. Observe and reconcile its attributed review ID. |
| Evidence and stopping | Report real provider/model/runtime and exact-head receipts only if executed and verified. Do not admit T02; Gate A acceptance and merge remain Craig's. |

This table is not a live configuration. The template cannot enable a run.

### Exact-head review follow-up

Offline tests assert that approval expiry is checked again after delayed
verification, after the review handoff, and before COMMENT. A permission
request writes a correlated private owner-attention signal before SDK
cleanup; generic provider errors never appear in that signal. Checkout
references are reduced to repository-relative paths, and other machine-path
references hold the output before publication. The publisher independently
checks the sanitized text and never retries a held or ambiguous POST.
These are fixture results, not evidence that the live roles were exercised.

### Historical Phase B hold and offline diagnostics

The [Lead outcome](https://github.com/craigholland/lighthouse/issues/4#issuecomment-7119574422)
reports that the one authorized attempt at `ac2bbd05e06392f4d2afd95dbbf2caeac6b1f3be`
consumed its claim, then stopped before review dispatch. No model review or
trial COMMENT occurred. The retained evidence does not establish which startup
check failed. The old authorization remains consumed; this revision grants no
retry or approval.

The review role records only fixed startup checkpoints, failure categories and
a separate cleanup observation, correlated to the private dispatch, head and
packet digest. It writes a failure before SDK cleanup; cleanup failure does
not replace it. Raw SDK payloads, exception text, account details, paths and
credentials are excluded. A checkpoint is not policy validation or an inference
about the preceding real attempt.

Offline inspection of the installed Python SDK's `client.py` and the runtime
package shows the SDK resolves the bundled executable by package location, not
by searching PATH. It prepends the package's helper directory to the narrowly
allowlisted child environment. On the checked Windows package that helper
directory does not supply Git; no general operator PATH is passed through.
That observation is separate from the fresh-thread response: the pinned
[rust-v0.171.0 snapshot builder](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/app-server/src/request_processors/thread_processor.rs#L6851)
initializes the Git annotation as absent, and the
[thread/start response construction](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/app-server/src/request_processors/thread_processor.rs#L1642-L1694)
returns that thread without supplying it. Adding Git discovery is not shown to
satisfy this response-level gate. Typed offline fixtures hold on absent/null
annotation and on an incorrect identity in that historical revision.

### Trusted checkout proof (offline verification only)

The [Lead checkout-proof decision](https://github.com/craigholland/lighthouse/issues/4#issuecomment-7134473669)
authorizes a bounded correction, not a retry. The private operator binds an
existing canonical `git.exe`; the contained worker uses a fixed argument
vector and minimal environment rather than inheriting PATH. Read-only Git
checks confirm the canonical root, allowed repository origin, exact packet
head and clean tracked/untracked (non-ignored) review content. Common and
worktree Git configuration are considered together. Multiple origin values,
includes, filters, and fetch URL rewrites hold rather than falling back to
common config or following an include. A changed checkout discovered by
the second proof retains a private correlated failure before cleanup.
The check
runs before SDK startup and again under the same deadline after fresh
review authority and before writing intent. The thread must still report
the approved working directory and effective read-only/deny-all policy.
Absent annotation cannot substitute for this proof; any conflicting supplied
identity holds. Proof failures are sanitized and stop before review dispatch.
No real client or trial COMMENT was executed for this correction.

### Snapshot admission and inert operator preflight

The [replacement attempt outcome](https://github.com/craigholland/lighthouse/issues/4#issuecomment-7136211698)
records that the run at `4a007e21bd8eaf8eec8f51afb355b2a48f2dd446`
consumed its claim and held before review dispatch. Its 301,566-byte context
and 99,397-byte instructions exceeded the old worker-only 64,000-byte cap.
That historical packet remains consumed and this revision authorizes no retry.

For inert private preflight, call `live.load_request(config_path, command)`
using the exact prospective operator config and command. It reads and validates
the immutable snapshot bytes without starting a job, contacting GitHub,
opening a credential, or granting authority. Entry, contained review stage
and worker use the same inclusive limits: 524,288 UTF-8 bytes for complete
context and 262,144 for governing instructions. Both must be nonempty,
nonblank valid UTF-8, free of NUL, and match the approved SHA-256 values.
Nothing is truncated. Invalid initial material holds before verification or
claim; invalid material independently observed after copy retains a fixed
private correlated rejection code without raw exception or snapshot content.
The bounds are verified offline, not evidence of provider/model capacity.

### Pinned initialization wire compatibility

The [Lead initialization decision](https://github.com/craigholland/lighthouse/issues/4#issuecomment-7137162662)
covers a source-identified blocker, not another live attempt or proof of
the first attempt's lost reason. The pinned [wire type](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/app-server-protocol/src/protocol/v1.rs#L71-L81)
and [response builder](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/app-server/src/request_processors/initialize_processor.rs#L203-L209)
return public `userAgent` build metadata, not `serverInfo`. The
[source-backed prefix](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/login/src/auth/default_client.rs#L138-L164)
places the compiled build version before platform and other suffixes.
The low-level initialized response is checked at the worker boundary
against the exact approved runtime pin, not the requested SDK client
version or SDK internals. Missing, malformed, prerelease, conflicting
or wrong build metadata retains the fixed private initialization failure
and does not reach account, thread, or review effects. No raw metadata
is retained. A pinned SDK method with an inert RPC double demonstrates
the wire shape; this is not evidence of a live runtime or available model.

### Historical private history collection (superseded)

The [Lead outcome](https://github.com/craigholland/lighthouse/issues/4#issuecomment-7138364585)
records startup and an attributed review acknowledgement at `9028e60`,
followed by a hold. Completion, provider cancellation and a trial COMMENT
were not established. The pinned runtime rejects full turn history for an
ephemeral thread. The repaired collector requires a fresh non-ephemeral
thread in the dedicated private Codex home, with no older thread or turns
reused. The next exact packet must disclose private history retention,
access and removal terms to Craig for separate approval. Do not open or
inspect existing history locations; only the one acknowledged thread is
queried through the public SDK. Both prior gates remain intact.

The [fourth live outcome](https://github.com/craigholland/lighthouse/issues/4#issuecomment-7140050881)
records an acknowledgement at 70362da followed by a generic attribution
hold. The exact failing check is not known. All four historical claims and
attestations remain intact. The public pinned
[review/start handler](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/app-server/src/request_processors/turn_processor.rs#L415-L438)
returns the submitted turn ID on the requested thread. The
[loaded-thread history reader](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/app-server/src/request_processors/thread_processor.rs#L3368-L3430)
returns reconstructed legacy turns or hydrated paginated turns. Pinned
[review item reconstruction](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/app-server-protocol/src/protocol/thread_history.rs#L2334-L2407)
shows that a completed turn may carry fixed display fallback text instead
of review output. The collector rejects that fallback. Source and inert
fixtures support matching history shapes, not an alternate ID mapping or
a recovered cause for the prior live hold.

Initial unmaterialized or empty visibility may be observed again with the
same thread ID under the existing deadline and a finite initial poll cap.
Foreign thread ID, conflicting effective persistent mode, incorrect turn
count, unrelated turn ID and disappearance of an established turn hold
with distinct fixed codes. The receipt retains only acknowledged IDs
and existing approval correlation. Late permission attention and failed
cleanup cannot erase the primary collection disposition. No raw response,
history, provider errors, prompts or machine paths are retained.
No history read repeats review/start; neither local cleanup nor its receipt
proves remote cancellation. Offline SDK-method fixtures are not live proof.

### Public stdio collection (offline only)

The [fifth held attempt](https://github.com/craigholland/lighthouse/issues/4#issuecomment-7140567269)
recorded a mismatching projected turn ID after acknowledgement. The actual
differing ID was deliberately not retained. Separately, the [Lead decision](https://github.com/craigholland/lighthouse/issues/4#issuecomment-7141253406)
and inert SDK regression demonstrate that generic review/start can lose
typed lifecycle events arriving before registration. This was not the
mechanism used in the fifth trial.

The experiment now uses the [public App Server stdio JSONL protocol](https://learn.chatgpt.com/docs/app-server)
for its already-managed worker; SDK public schema and bundled runtime stay
at 0.171.0. No PATH expansion, executable override, SDK private router,
history reads, alternate review API, or recovery dispatch is used.
The [pinned review handler](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/app-server/src/request_processors/turn_processor.rs#L415-L438)
returns the review thread and dispatched turn. The
[pinned core review lifecycle](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/core/src/session/review.rs)
does not promise a normal parent turn/started. The review items carry
independent item IDs; only the explicit envelope thread/turn and matching
terminal turn identify the run. The terminal can have no items.

One ordered reader arms capture before the review request is written.
Before and after acknowledgement it retains only review-mode item
completions and terminal signals, limited to 16 events and 256 KiB of
retained UTF-8 projection (plus a per-record reserve charged to that cap).
An entered-review hint is parsed under the raw frame cap but its text is
not retained or charged as lifecycle text. The frame cap is 1 MiB,
outgoing request cap is 4 MiB, and at most
two request IDs are pending (one reserved for cooperative interruption).
The existing parent cutoff remains authoritative. Only one matching
entered/exited pair with substantive review text and a successful matching
terminal can complete. Invalid framing, mismatches, duplicates, overflow,
server error, loss before terminal, no output and permission requests hold.
The existing fixed private correlation and separate late attention/cleanup
receipts apply. Reader shutdown and validation precede the worker's result;
the parent must still observe worker exit and zero active job processes
before publication. Local shutdown does not establish provider cancellation.

The [sixth held attempt](https://github.com/craigholland/lighthouse/issues/4#issuecomment-7143181216)
acknowledged review/start and reported collection_buffer_overflow, without
completion or publication. The pinned native custom target uses the full
instructions as a display hint, both in acknowledgement userMessage and
enteredReviewMode. The actual provider frame was not retained. The prior
raw-frame accounting reproduced the hold offline with a 383,589-byte
synthetic context. Its target was 406,068 UTF-8 bytes, compact shaped ack
451,016 bytes, entered frame 451,006 bytes and outgoing request 450,825
bytes (all figures are synthetic). The repaired wire attributes that
same source-shaped echo sequence.

The shared pure budget owner checks the actual thread/review writes,
compact pinned acknowledgement and entered representations (including
worst allowed ID lengths and a 1 KiB envelope reserve) before any verifier
or claim, and repeats validation for the copied inputs and worker.
Raw snapshots remain capped at 512/256 KiB, but heavily escaped evidence
can exceed the encoded echo budget before the raw cap. A synthetic
all-quote context admits 261,667 bytes and rejects 261,668 with no claim.
The worker sends the entire decoded approved input, using UTF-8 inside
the JSON text rather than escaping ordinary Unicode twice. Output caps,
exact IDs, one dispatch, permissions and shutdown gates are unchanged.

This is offline evidence only. All six historical claims remain consumed.
The dedicated fresh non-ephemeral home and approved retention conditions
remain unchanged; the wire does not open old sessions or query history.
No new trial, merge, Gate A acceptance or T02 admission is authorized.
