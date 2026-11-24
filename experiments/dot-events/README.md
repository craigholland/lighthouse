# T02 Phase A: Dot notification-to-local-worker feasibility

Issue [#5](https://github.com/craigholland/lighthouse/issues/5) assigns assessment
only. Baseline is merged development `d3450a3694499cd2178a19f8f0796522a9ab8186`.
Gate A remains open. This folder contains no executable bridge or active settings.

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
