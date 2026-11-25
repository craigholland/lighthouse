# T02 Phase A: Dot notification-to-local-worker feasibility

## Offline event-eligibility probe preparation

The [renewed offline contract](https://github.com/craigholland/lighthouse/issues/5#issuecomment-7152120809)
prepares the **worker-free** event source. The existing known-worker proof
below remains independently approved at its earlier exact head, not this one.

- `t02_events_probe.py --dry-run` exercises a fixed route through the candidate
  [Streamable HTTP 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
  initialize/initialized sequence and the documented
  [MCP Events](https://developers.openai.com/plugins/build/mcp-events) discovery,
  subscription, callback challenge, deliveries and unsubscribe. Transport
  dispatch is pure: the fixture passes an already authenticated synthetic
  principal; it never opens a listener. The event carries only a proof ID
  and fixed receipt marker. No worker/tool/marker action is imported or exposed.
- Subscription identity, expiry, restart allowance, terminal stop and attempt
  counts are private, bound to one canonical disposable SQLite file. The owner
  commits verification/send intent before each injected effect and serializes
  the actual effect boundary with stop. A lost/ambiguous intent blocks new
  delivery. A known 2xx is only transport acknowledgement. Reopening a durable
  stop cannot reactivate it. There can be one planned restart, one deliberate
  duplicate of the original event, and at most three application attempts
  including explicit retries after known transient responses. No event replay,
  scheduling or automatic retry loop. Confirmed unsubscribe and observed expiry
  are durable; keep state private, local, and non-replaced.
- The callback recomputes DNS for every attempt; the complete bounded answer
  must be public. The adapter contract requires dialing that exact pinned IP
  with TLS verification against the bound hostname, no redirects, absolute
  deadlines and a bounded response. HMAC authenticates the transmitted bytes,
  including stable event ID and fresh signing time. No real callback or DNS
  was contacted. A successful signed challenge is not a coordinator receipt.
- The future composition guard independently checks current, provider-derived
  Craig and Lead evidence, exact head and packet digest before any effect-side
  factory, and rechecks before source, runtime and observation. It requires the
  adapter to attest the private binding and pinned runtime, and require
  confirmed shutdown of both attempted roles inside the original deadline.
  It has no task creation or continuation role. The later candidate is the
  [narrow runtime v0.0.21](https://github.com/openai/tunnel-client/releases/tag/v0.0.21)
  from the Lead packet, not a downloaded or verified executable here.
- **Hold for live:** a real trusted evidence reader, authenticated loopback
  HTTP and pinned-IP TLS adapters, verified executable identity and bounded
  Windows process containment/cleanup still need a separate reviewed contract
  and Craig's exact operational approval. The checked-in entry hard-rejects
  `--live`; it does not accept an arbitrary adapter, configuration or approval
  flag. Synthetic positive authorization only reaches test doubles. Tests
  observe intent/effect ordering and shutdown dispositions, not a real runtime
  or actual Dot receipt. The target account, resource and billing are unverified.
  Full T02 and Gate A remain open.

## Offline known-worker proof

The [renewed Issue #5 contract](https://github.com/craigholland/lighthouse/issues/5#issuecomment-7148129087)
replaces the prospective creation boundary in the historical report below. The
experiment starts with one prebound synthetic worker; events are hints only.
The injected port has exact-known continuation and status, no creation,
replacement or fallback. The local receiver owns the fixed marker, not an
arbitrary shell command or a bare token handed to a model.

The immutable reservation binds the project, repository, Issue, work/dispatch
identity, scope, revision, role, worker, host, checkout, authority, expiry,
canonical state file and fixed marker. Runtime opens existing state only.
Availability and the exact current trusted fixture observations are checked
before either intent. SQLite serializes write transactions with
`BEGIN IMMEDIATE` and full synchronous commit; the winner commits continuation
intent before calling the fake port, or start intent before the fixed marker.
The marker file is separate from SQLite. A persisted start without completion
remains held even when the marker file exists: observing a side effect is not
the same as a trusted final receipt. Reconciliation can record exact known
acceptance without inventing transport acknowledgement or completion.
Two otherwise valid acceptances for different turns on the same binding are
different: the owner durably latches the contradiction, retains the original
turn and consumed intent, and denies marker admission and attributed
completion. Status reads, duplicate events, reopen, competing callers and
even a repeat of either turn do not resolve it. This offline proof exposes no
conflict-clearing operation; a later owner disposition would require
conclusive authority outside this experiment.
Completion and deadlines never free the single reservation.

The facility assumes a single, private, non-replaced state path on a local
filesystem with ordinary SQLite locking and crash durability. The test-only
synthetic seed is explicit, separate from runtime, and cannot overwrite a
state file. This is not a guarantee against manual modification, deliberate
state rollback, unrelated actions, arbitrary device write failure, or
production runtime behavior. After lost commit confirmation, no effect is
performed by that call. A committed bit is visible on reopen and precludes
replay; lock contention with no admitted write reports a hold. Treat state
loss, corruption, or persistence which cannot be trusted as operator
attention, not permission to provision another file. See the
[SQLite transaction contract](https://www.sqlite.org/lang_transaction.html)
and [atomic-commit limits](https://www.sqlite.org/atomiccommit.html).

The [verification contract](../../docs/development/verification-contract.md)
exercises real disposable SQLite with multiple connections and bounded Python
processes, counting actual fake continuation and marker invocations, including
process exits before/after the marker and before the acceptance receipt.
Every provider boundary is inert. Imports and help start no work; dry-run
creates only disposable synthetic artifacts and uses no child worker.
No live selector, account, credential, installer, network, native worker or
T01-private data is involved. This proves neither actual private event
eligibility nor exact native continuation, production guard integration or
Gate A acceptance. Those remain separate Lead/owner gates.

## Phase A feasibility record

The original Issue [#5](https://github.com/craigholland/lighthouse/issues/5) packet assigned assessment
only. Baseline is merged development `d3450a3694499cd2178a19f8f0796522a9ab8186`.
Gate A remains open. At that phase this folder contained only documentation.

## Finding

**Candidate supported in parts; hold setup and execution.** ChatGPT documents
MCP Events for dots; an existing Dot coordinator already delegates ordinary
authorized work to an attached local executor. Neither fact demonstrates that
a tunneled custom plugin can supply an event to this particular coordinator
and that the resulting event task can target the established local executor.
A webhook 2xx would prove only receipt by ChatGPT, not either handoff.

### Documented product capabilities

Official product sources and release metadata inspected 2026-11-24:

- [MCP Events](https://developers.openai.com/plugins/build/mcp-events#before-you-start)
  names dots and Work Cloud as supported surfaces subject to workspace controls.
  It specifies Streamable HTTP with initialization, or MCP 2.0 HTTP protocol
  version `2026-07-28` with discovery. The `2025-03-26` initialization example is
  an illustration, not a pin for our workspace. The same authenticated MCP
  endpoint exposes `events/list`, `events/subscribe` and
  `events/unsubscribe`. ChatGPT supplies the destination and signing secret.
  The server verifies the HTTPS callback by challenge before sending
  application data, signs each exact event body using Standard Webhooks, and
  retains finite subscription state across restarts. The callback must remain
  a validated public HTTPS **OpenAI destination**, not a local listener or a
  new public ingress we operate. An active source needs outbound HTTPS for
  delivery even if its MCP endpoint is private. The docs allow bounded
  transient retries with the same event ID and fresh signatures; arrival can
  reorder and runs can batch. This integration does not support polling,
  streaming delivery, or the draft gap/terminated notifications. Replay is
  optional; use a no-replay synthetic source and report missed delivery
  explicitly. See [delivery](https://developers.openai.com/plugins/build/mcp-events#handle-delivery-responses)
  and [subscription lifecycle](https://developers.openai.com/plugins/build/mcp-events#manage-subscriptions).
- [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
  gives supported OpenAI products a request path into a private MCP server
  through a locally initiated, long-polling client. Its documented request and
  response path is distinct from the Events server's outbound signed callback;
  neither an MCP response nor a streamed tool notification is an event-task
  wake. The candidate is the Events HTTP interface through the Tunnel
  connection type, with ordinary outbound HTTPS to the platform-provided
  callback. The guide allows a private HTTP upstream; it does not certify
  Events method forwarding, negotiated protocol behavior, or event-task target
  binding for the intended dot. Evaluate with HTTP matching the Events guide;
  do not assume the Tunnel's general stdio support is Events compatibility.
  The [public v0.0.21 release](https://github.com/openai/tunnel-client/releases/tag/v0.0.21)
  lists a [Windows AMD64 client build](https://github.com/openai/tunnel-client/releases/expanded_assets/v0.0.21)
  as an available candidate, not our installed client or an adopted pin.
- [Permissions and association](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#permissions-and-access)
  distinguish the Platform organization owner/RBAC admin and ChatGPT workspace
  plugin permissions. Tunnel setup needs Tunnels Read + Manage; a restricted
  runtime key and plugin operator need Read + Use. Associate the owning
  Platform organization and the intended ChatGPT workspace. The connector
  principal must also be authorized for the exact source and filter at the
  private server; the callback secret authenticates delivery, not permission
  to start a worker. Neither GitHub App role supplies these permissions.
  The tunnel host needs local reachability to the private endpoint and
  outbound HTTPS to the documented control plane; keep the client and event
  source available for the bounded window. A published tunnel cap or request
  timeout is not a delivery SLA, worker deadline, or price.
- [Dot tasks](https://learn.chatgpt.com/docs/dots/tasks-and-memory#event-monitoring)
  support eligible events from enabled connections, not every provider or
  workflow. [Dot computer and app access](https://learn.chatgpt.com/docs/dots/computers-and-apps)
  describes local task initiation and separate local computer permission;
  [local access requirements](https://learn.chatgpt.com/docs/enterprise/cloud-local-access)
  require the connected desktop to be online with its app open and compatible
  policies, and document 26.929 as the enterprise local-access minimum.
  Disconnection does not imply automatic relocation or completion. The
  [Dots overview](https://learn.chatgpt.com/docs/dots) distinguishes
  conversation allowance from delegated Work/Codex usage. Do not assume this
  account, a Platform association/key, host uptime, or the proposed proof is
  free or entitled. Confirm the account's applicable metering, runtime and
  hosting exposure, and an owner-approved ceiling (including zero if required)
  before setup. No cost commitment or infrastructure is proposed now.

### What was actually observed

The intended coordinator is Craig's existing Lighthouse collaboration Dot; the
executor is its existing attached Windows worker in Dot's isolated Lighthouse
checkout, not Craig's or Lead's checkout and not a substitute cloud worker.
For this ordinary owner-directed Phase A assignment, the coordinator delegated
to that executor; attachment and Git root/origin inspection showed the
isolated worker checkout; own-App read verified the merged baseline. This
establishes human-directed local work only. It does not establish the app build
or entitlement for tunneled custom Events, an installed/approved tunnel client,
a subscription, an event arriving, or where an event-triggered task can dispatch.
No product settings, private sessions, credentials or callback endpoints were
probed for that assessment. Ordinary read-only repository and draft-PR
coordination use the existing Dot GitHub App, not a prospective T02 credential.

## Coordinator interface inventory

This is a metadata-only follow-up to the approved feasibility report, under
[Lead's renewed Phase A assignment](https://github.com/craigholland/lighthouse/issues/5#issuecomment-7146613425).
Lead's [pinned client assessment](https://github.com/craigholland/lighthouse/issues/5#issuecomment-7146613425)
found generic JSON-RPC forwarding at v0.0.21. This resolves the client-side
method-list question at source level, not hosted discovery or target eligibility.

| Boundary | Documented or directly visible | Unknown or unsupported on this surface |
| --- | --- | --- |
| Caller and build | Cloud Dot coordinator inspected its native interface definitions and observed an eligible Windows computer online, separately from its managed cloud. The attached Windows executor independently confirmed its isolated Lighthouse checkout, branch, clean tracked state, and task revision `7f4154fa8ac3920d782e7bbfc808df9737c21b87`. The latter is a manual local-work observation, not a cloud interface test. | No applicable desktop app build, coordinator build or workspace event entitlement verified through inert metadata. |
| Local selection | Native coordinator metadata describes selection of a connected computer by exact environment identity or a freshly listed index, with optional strict identity check and an absolute working directory within the existing grant. Desktop default may allocate a new workspace; it does not prove the intended checkout. A different selector starts a saved cloud environment, not the local checkout. Project ID is not an effective selector on this surface. | No demonstrated path from a custom-plugin event wake to these controls, no automatic identity binding to the intended checkout, and no public API/UI contract exposing these exact internal task fields for Lighthouse. |
| Launch result | Return contract distinguishes admitted execution (task and turn identities), admission unconfirmed after task creation (first turn may still start), and explicit selected-executor-offline with no task created. Environment setup can still be pending after admission. | No caller-provided idempotency key, durable reservation reference, or claim-enforcing provider input is exposed in the visible creation contract. Admission identifiers are not proof of local acceptance or completion. No create was called. |
| Claim before effect | A Lighthouse-owned reservation could guard calls made through an enforcement boundary **if** that owner actually controls the creation effect. | No visible native task-creation check of Lighthouse's durable reservation and no evidence all paths to that effect can be constrained to such an owner. Model instructions and acquiring a lock inside the already created worker do not enforce one creation. This is a blocker for implementation, not a design to work around. |
| Known status and output | Native read by exact task identity can provide recorded turn outcome and task-visible messages; records may lag. Completion/failure/interruption/disconnection notifications exist for owning task, according to the visible contract. A disconnect does not establish an ended turn. | No observed execution or receipt. The native record is not an authenticated Lighthouse acceptance/completion receipt binding dispatch, local target, checkout and revision. No existing thread content or histories read. |
| Lost acknowledgement | If the provider returned a task identity and admits uncertainty, inspect that exact task rather than creating another. | If the identity was lost, no visible exact lookup by caller dispatch or reservation, and no safe create retry. A title, time, prompt marker or thread list cannot restore identity. Retain unknown-held; owner disposition unless conclusive provider evidence appears. |
| Stop and final state | For an exact eligible visible cloud task, the archival contract describes stopping active work; return errors may leave result uncertain, and archived state can be read back for eligible targets. | Not a general stop for a local-only task, not a strong guarantee of native executor shutdown, no effect cancellation inferred, and no stop called. A future proof must bind final status to the same exact run. |
| Existing connection | Public docs describe separately enabled plugins and event-eligible connections. The coordinator's visible event surface names a closed set of built-in connector sources; it does not expose a generic custom MCP selector. | No permitted existing metadata established a matching enabled custom MCP/Tunnel connection for this coordinator. Unknown, not absent; no rescan, discovery request, activation or callback probe. |

Operation and field shapes above are capability summaries, not published
Lighthouse invocation instructions or guarantees of public access. The
outstanding decision is who can enforce the one durable claim at task creation
and conclusively reconcile lost identity. Keep the route on hold until Lead
identifies a supported boundary and intended event-target eligibility, or
records the route inconclusive. A fake can test a proposed contract but cannot
prove native enforcement, connectivity or a real status lookup.

## Proposed bounded proof (not authorized)

1. The owner approves one test workspace/coordinator, one existing Windows
   worker and isolated checkout with exact expected revision, one private
   source and synthetic event filter, TTL, maximum delivery attempts/time,
   a nonsecret evidence destination, and teardown owners. Lead records the
   supported product/build and protocol negotiation, source principal and
   target binding, or records a hold. Do not select another transport.
2. Through the approved custom plugin, ChatGPT authenticates to the exact
   private MCP resource and discovers/subscribes to one synthetic event such
   as `lighthouse.t02.probe`; the source verifies the platform callback. Store
   its finite subscription with its authorized filter. Source sends inert
   identifiers only; no embedded instructions, secrets, command text, repo
   contents or authority conveyed by an event payload. Delivery receipt is
   transport evidence only.
3. Match the real coordinator's attributed task to the approved binding and
   event. Use only the existing supported local-work path, never a listener
   or process selected by event data. Validate scope, expiry and assigned
   checkout/revision independently of payload. The coordinator owns a stable
   dispatch ID derived from the approved proof instance and authorized work
   identity, not from a webhook retry timestamp or task-run ID. A second
   subscription/delivery/task run must not derive a fresh ID for the same
   work, and a late older event must never replace the current binding.
4. At the pre-effect boundary persist one durable, exclusive experimental
   claim against that dispatch before worker creation or local work. If the
   supported host API itself creates the worker, the claim must be reserved
   before that call; a lock obtained after starting would not prove single
   dispatch. Worker acceptance is an attributed, separately correlated
   receipt identifying the chosen worker and authorized revision; it is not
   completion. The sole worker performs one harmless read-only marker task.
   Completion matches the original dispatch, claim, worker receipt and
   revision, and reports a minimal fixed marker/status. Record local evidence
   separately from source receipt and coordinator task attribution.
5. For any ambiguous creation/ack or incomplete durable write, hold and
   reconcile by exact dispatch/claim and trusted receipt. No automatic
   replacement, replay, expiry-based unlock, cloud fallback or effect retry.
   A duplicate status read is harmless. Owner disposition is required if the
   provider cannot conclusively resolve an unknown outcome. Scope this
   conflict-free claim to one experiment; it is not the production ledger.
6. End at the first authorized terminal status or deadline. Stop source
   delivery, unsubscribe or verify definitive expiry, then verify source
   restart does not reactivate it and a late delivery cannot start work.
   Retire only resources created for the proof and verify the client's
   stopped state, permission cleanup and any declared retention. Preserve
   sanitized evidence; no access to existing private histories.

### Failure and evidence matrix

| Scenario | Later inert fixture and required observation | Separate live evidence, if approved |
| --- | --- | --- |
| Duplicate or reordered event; same work with a fresh event ID | Inject both deliveries, reorder and batch them; at most one durable claim and one worker-creation call, old binding cannot replace current | Replay an exact synthetic event within the approved window; show one actual local execution and both attributed deliveries or duplicate disposition |
| Restart across claim and dispatch | Reopen durable test state before and after dispatch boundary; pending or unknown preserved; no second create | Show state persists across bounded restart, correlate existing claim and receipt or report hold |
| Lost acknowledgement or disconnect after creation | Model side effect then lost receipt, restart before response; count exactly one create across attempts, reconcile only matching results | Distinguish missing delivery 2xx from lost worker acceptance or completion; no second worker; unknown remains visible |
| Rejected, expired or wrong target | Fake invalid source, filter, deadline, coordinator, worker, revision or malformed receipt; no claim/start for rejected admission, no false completion | Confirm scoped subscription and worker evidence match; no test against unrelated target |
| Desktop offline before launch or drops mid-work | No cloud fallback; explicit not-started if proven, otherwise unknown-held | Observe the chosen desktop unavailable and later reconcile it without redispatch |
| Unsubscribe, expiry and restart | Simulate duplicate unsubscribe, post-expiry delivery and service restart; stopped source and local admission gate reject late work | Verify unsubscribed or expired source, persistence after restart, no new worker, and removal of temporary-only resources |

## Next decision and minimum experiment surface

Lead should first resolve two exact compatibility questions using supported
product evidence for the intended workspace and build: **Can a
Tunnel-connected custom plugin expose MCP Events to this dot, and can the
resulting event-triggered task select the established connected local worker
without defaulting to cloud or another task target?** Confirm how the approved
path supports a durable reservation before dispatch and how exact status is
looked up after a lost acknowledgement. If unsupported, inaccessible or
inconclusive, report that and stop; no public endpoint or alternate transport.
No build or installed tunnel version was inspected because neither is needed
for this report. A later contract should record both exact approved target
builds, negotiated event protocol and chosen official client version/checksum;
there are no new dependencies or pins in Phase A.

If those prerequisites can be resolved, seek separate Craig authorization for
the workspace/organization mapping, permissions and credentials, private
endpoint/client host and finite source window, synthetic filter, exact worker
and revision, allowed action, costs, stop/teardown and evidence retention.
A later Lead packet can then scope an **inert-only** next step to an experiment
adapter/claim/status fixture and tests under this folder, with dependency-free
standard-library durable state if the proposed contract allows it. Model the
MCP messages and callback as local fixtures, not as a running listener; inject
a fake coordinator/worker, clock and storage-failure boundary. No new pin until
a supported protocol client is genuinely needed and separately reviewed.
Proposed commands for that future slice (test path does not exist today):

```powershell
.\experiments\codex-review\.venv\Scripts\python.exe -m pytest -q experiments/dot-events/tests
.\experiments\codex-review\.venv\Scripts\python.exe -m ruff check experiments/dot-events
.\experiments\codex-review\.venv\Scripts\python.exe -m mypy experiments/dot-events
```

Phase A itself uses only the existing inert checks and the expanded local
Markdown file-target list in the [verification contract](../../docs/development/verification-contract.md).
It claims no T02 implementation, live proof, full acceptance or Gate A completion.
