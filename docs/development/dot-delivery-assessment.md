# Dot delivery assessment

**Decision: no-go for production T08.** The complete Lighthouse-to-existing-Dot
delivery path is **not established**. The supported pieces are event
notification and local work on a connected and permitted device. Neither the
public contract nor the inspected capability metadata exposes a supported
operation for Lighthouse to submit a specific revision to the existing Dot,
bind it to the intended local worker and retrieve that worker's durable claim
using Lighthouse's own dispatch ID. This is a conclusion about the reviewed
surface, not a claim that OpenAI cannot provide such an operation elsewhere.

Recommend keeping the existing Craig-to-Dot handoff while retaining Lighthouse
as the source of reconciliation evidence. Do not add a bridge to compensate
for the missing operation.

## What is supported

Public OpenAI product documentation reviewed on 2026-11-27 is rolling
documentation; no fixed product revision is exposed on these pages. The local
capability inspection below is a same-date observation, not a supported API
version or a promise about other accounts.

| Surface and operation | Where it goes and what it acknowledges | Missing for this path |
| --- | --- | --- |
| [MCP Events](https://developers.openai.com/plugins/build/mcp-events): send a signed event to the callback registered by ChatGPT for an authorized subscription. | Dots and eligible Work/Cloud chats can subscribe via a connected plugin. A successful HTTP response acknowledges delivery to ChatGPT only. The subscriber processes asynchronously and may batch delivered events. | The callback does not choose a local worker, reserve execution, or acknowledge a worker claim. Reusing the event ID is not proof of an exactly-once worker effect. |
| [Local computer access for Work Cloud and dots](https://learn.chatgpt.com/docs/enterprise/cloud-local-access): grant a Dot access to a connected computer through its desktop settings and use that access for supported local tasks. | The grant makes a specific computer eligible. Offline leaves the grant intact but blocks work requiring the device. Disconnect or revocation does not attest that an in-flight local effect stopped; local work does not automatically migrate to cloud. | This is an access and execution capability, not a public Lighthouse submission or dispatch-key status operation. |
| [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels): connect supported OpenAI products to a private MCP server over an outbound tunnel. | A Platform tunnel, runtime key, reachable private server, correct associations and tunnel and workspace permissions are separate prerequisites. | Establishes connectivity if configured; does not establish a custom event path in this account, select a worker, or provide a claim or cleanup receipt. |

### Inert capability observations in the authorized context

- A connected local computer was visible separately from the cloud one.
  Manual local task creation can select an eligible computer and request a
  checkout directory for a **new** child. This is distinct from an external
  caller submitting an idempotent task to a bound implementation worker.
- The task reference returned by successful admission can be used for exact
  status or recorded outcome. A list/search result is not that receipt.
  No caller-supplied idempotency key, reserve-before-effect operation, or
  authoritative lookup by Lighthouse dispatch ID was exposed by the inspected
  creation/read surfaces. If the admission response is lost, no safe automatic
  re-submission follows. Neither disconnection nor a task stop action proves
  that a particular local effect ceased.
- Visible event-source metadata covers named built-in connectors. It did not
  expose a custom MCP source, subscription selector or connection inventory.
  An execution preference is not proof of a custom event trigger, the active
  checkout, or the identity of a local worker. Account eligibility and
  interoperability were not tested.

No notification, subscription, tunnel, local task, cancellation, provider SDK,
or integration runtime was invoked in this assessment. Existing access was
observed, not modified. Checkout/GitHub collaboration for this documentation PR
is not bridge operation evidence.

## What Lighthouse has actually shown

- [Parked T02 / PR #15](https://github.com/craigholland/lighthouse/pull/15)
  remains frozen at `834713f006fb8962c0cd42b64825bd8c767ad509`. Its retained
  offline fakes and harmless Windows stand-ins address bounded ownership and
  cleanup for those fixtures. Preserve recorded failures and unknowns. They do
  not establish hosted callback acceptance, cloud wake, worker binding, or
  duplicate delivery safety on the actual Dot path.
- [T01's controlled proof](../../experiments/codex-review/README.md) is
  historical evidence of a Codex review and attributed COMMENT for its
  authorized exact head. The Codex review session is not the Dot
  implementation worker. That proof does not establish Dot delivery or
  authorize another run.
- The [merged T07 interfaces](runtime-bindings.md) supply inward contracts and a
  read-only existing-ledger status command. They are usable as documentary
  inputs under the [Lead's scoped resolution](https://github.com/craigholland/lighthouse/issues/11#issuecomment-7228718408).
  Status reports Lighthouse's records; it cannot look up an uncorrelated
  remote submission. T07 operational acceptance remains pending.

## Minimum contract before a bridge could be accepted

Reuse the [work intake](work-intake.md), [ledger](ledger.md) and
[reconciliation](reconciliation.md) concepts. Separate transport delivery,
coordinator admission and actual worker claim; never turn evidence for one into
a status for another. This is an acceptance contract, not a new schema or
provider API.

1. **Identity and target.** Bind stable dispatch ID to repository identity,
   Issue and work order, captured approved scope/profile, authorizing actor,
   operation, assigned Dot role and intended checkout. For a revision bind
   the existing PR and exact expected head; it is not a new PR. Reject a
   different payload using an existing dispatch ID.
2. **Authority.** The coordinator rechecks the current target, prior hold or
   claim, permitted worker and scope before admission. The worker rechecks the
   exact checkout and target before effects. Target drift or unverifiable
   authority is a hold, not implicit approval. Dot writes as its own App from
   its isolated checkout; Lead reviews as its own App; Craig merges.
3. **Single durable claim.** Reserve before any effect. Duplicate or reordered
   delivery under the same stable ID may only return the existing reservation
   or outcome. A second writer cannot claim while the first is reserved.
   The coordinator must be able to reconcile the exact claim by stable ID
   without relying on successful delivery of the first response.
4. **Receipt and status.** Include the stable dispatch ID and attributable
   receipt, with run/worker reference only when identified. Observe the known
   run by that exact reference, keeping worker completion separate from
   repository acceptance.
5. **Completion and uncertainty.** Preserve bounded evidence of the actual
   PR and resulting head; verify GitHub before advancing. Lost response,
   unavailable host, cancellation request, stale target or unknown status
   never release an uncertain execution. No automatic replay or cloud
   replacement; reconcile the earlier run or establish attributable
   quiescence before Craig decides what to do next.

| State | What Lighthouse may conclude |
| --- | --- |
| Pending | Notification receipt or queue admission only; there is no verified worker claim. |
| Accepted | One durable claim by the intended worker is verified, with an exact run/worker reference. |
| Rejected | Definitive refusal before effects, with a reason attributable to the exact dispatch. |
| Unknown | Admission, claim, execution or stop evidence is missing or contradictory. Retain reservation and require reconciliation. |
| Running / needs approval | Known worker executing or waiting at an explicit gate; neither grants authority for new work. |
| Completed / failed / cancelled | Attributed terminal observation for the exact run. Completion still needs repository evidence; failed or cancelled without confirmed quiescence remains on hold. |

## Craig's decision

**Keep manual Dot handoffs for now.** Craig can continue authorizing one exact
Issue or revision in the existing Dot conversation. Dot can use its selected
local checkout, report the PR and head, and leave independent review and merging
where they are. This adds no access or subscription cost and preserves the
current role model, but does not remove the manual handoff. Retain the automated
Dot dispatch gate and seek a supported dispatch-key-to-local-claim contract
before reconsidering it.

One alternative worth evaluating **only if Craig chooses to change the role
model** is the [Workspace Agents trigger API](https://developers.openai.com/workspace-agents/trigger-runs).
It targets a separately published workspace agent, supports a caller-supplied
idempotency key, and acknowledges a queued trigger, not an existing Dot or
local worker claim. It requires a published agent and authorized access token;
it would require Craig to approve replacing the coordinator for this path,
confirm workspace eligibility, permissions and cost, and separately establish
the supported binding to a worker with an exact claim. It is not a drop-in
substitution, and this assessment did not verify its account availability or
exercise it.

No end-to-end trial is justified on the reviewed route. Reconsider one exact,
separately owner-approved harmless trial only when a supported operation can
bind the intended worker and correlate its claim after an acknowledgement gap.
Full T07 operational acceptance, T02 production capability acceptance, and
T08 implementation, setup and execution remain gated; no proof is accepted
or authority granted by this assessment.
