---
title: "Lighthouse Integration Assessment"
created_date: 2026-11-23
update_date: 2026-11-23
status: PROPOSED
---

# Lighthouse Integration Assessment

This records evidence and candidates, not a completed integration. Read it with
the [architecture proposal](proposal.md) and [initial plan](../development/initial-plan.md).

## Observed bootstrap facts

- PR #1 is merged into `development`; `main` remains the release branch.
- The Codex App is `Codex lead engineer`, App ID `5869282`, bot actor `359712317`.
  The Dot App is `craig codex dot`, App ID `5869344`, bot actor `359713928`.
  Their separate installations now include Lighthouse and Koios Cold.
- Codex's App identity and a Lighthouse-only token were tested. Codex also
  published PR #1 with its own identity. Test/publication tokens were revoked.
- Dot's installation scope was inspected. Its cloud-side authentication,
  event subscription, local-worker dispatch and receipt chain remain untested
  by this bootstrap session.
- Local CLI inspection reports `codex-cli 0.171.0-alpha.13`. Its App Server
  command exists; `openai_codex` is not installed in the Lighthouse environment.

These are observations as of 2026-11-23, not a supported-version policy. Machine
paths, credentials and active profile configuration are deliberately absent.

## Codex candidate

Craig accepted dedicated local review sessions on 2026-11-23. Prefer a pinned
Python SDK/App Server combination for the proof. The documented Python SDK
controls App Server through JSON-RPC and bundles a pinned CLI runtime. Selecting
the installed alpha executable instead is an explicit compatibility choice.
[Codex SDK](https://learn.chatgpt.com/docs/codex-sdk).

App Server provides thread/turn identities, stored-state reads, completion status,
and approval requests. Use these to design receipt reconciliation; the reviewed
documentation did not establish idempotent launch semantics. Prefer the local
stdio boundary for the proof. [App Server](https://learn.chatgpt.com/docs/app-server).

Local `codex queue --help` also documents existing-session delivery. Its `--resume`
can warn about a failed resume while the command still succeeds. CLI exit success
alone is therefore insufficient dispatch evidence. That route is unnecessary
for the accepted dedicated-session design and remains untested here.

T01 must prove a fresh review context can obtain the Issue, repository standards,
PR and exact head; use the Lead identity; produce an attributed review; and
recover or hold safely after interruption or an acknowledgement gap. No desktop
conversation reuse, inherited context, or model availability is assumed.

## Dot candidate and connectivity

MCP Events is documented for dots and supported Work/Cloud chats. It uses an
authenticated MCP endpoint for discovery/subscription and signed webhook
delivery to ChatGPT's callback. This product integration does not support its
draft protocol's polling or streaming modes. Event payloads are data; subscriber
behavior comes from the user's authorized instructions.
[MCP Events](https://developers.openai.com/plugins/build/mcp-events).

Propose a small Dot adapter that exposes work availability and a claim/status
surface. Its claim is checked against the ledger and returns a stable dispatch
identity. A notification acknowledgement is not proof of worker acceptance or
completion. T02 must prove the full cloud-to-local chain and duplicate handling.

Secure MCP Tunnel offers an outbound-HTTPS connection to a private MCP server.
It requires appropriate Platform/workspace associations and tunnel permissions.
It is a connectivity candidate, not verified MCP Events interoperability in
Craig's account. Inspect availability, supported host build, operational needs
and cost before selection. [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

Dot's local computer access is a separately configured product capability; a
connected, permitted computer is required for local execution. This does not
make a Codex session and a Dot session interchangeable.
[Dot local access](https://learn.chatgpt.com/docs/enterprise/cloud-local-access).

Do not create a tunnel, plugin connection, credential, public endpoint or paid
resource under this proposal. Craig must approve the concrete setup when its
requirements are known. If the candidate fails, record the blocker and return
to Craig before selecting another transport.

## GitHub observation candidate

The repository activity feed can be delayed by up to six hours and is bounded
by event count and age. It cannot be the sole completion or authorization source.
Reconcile current Issue/PR resources and attributed records instead.
[GitHub Events API](https://docs.github.com/en/rest/activity/events).

Use conditional reads, complete pagination, serialized requests, and server
rate-limit/backoff instructions. Propose a 60-second initial interval, adjustable
within the shared installation budget and any endpoint minimum.
[REST practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api),
[rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).

Compare alternatives: direct GitHub webhooks need a reachable receiver and
delivery verification; a relay adds an operated dependency. Local reconciliation
fits the initial desktop deployment. Webhooks can later supply hints to the same
application reconciliation path, without changing core rules.

## Proof gates

| Gate | Required evidence | A failed or inconclusive result means |
| --- | --- | --- |
| Codex | Local session, exact-head review, actor identity, receipt/status and interruption behavior | Revise the adapter contract; no automated review dispatch |
| Dot | Authorized subscription, cloud wake, one local claim/worker, status/completion and repeat-delivery behavior | No automated implementation dispatch |
| Connectivity | A supported approved path usable from Dot while the local host remains private | Revisit transport with Craig; no automatic public exposure |
| Live profile | Confirmed branches, separate checkouts, roles, labels and verification contract | Keep that profile inactive |

The [decision register](../decisions/open-questions.md) records who must resolve
or explicitly delegate these gates. Product documentation is capability evidence;
it is not proof that the complete Lighthouse integration has run.

## Proposed agent boundary

The application needs submission and observation of a durable dispatch. The
proofs must validate this contract rather than expose provider SDK objects inward.

| Record | Required meaning |
| --- | --- |
| Dispatch identity | Project ID, work-order ID, stable dispatch ID, operation (implement/revise/review), assigned role and profile fingerprint |
| Target and context | Repository and Issue IDs; PR and expected head for revision/review; captured authorized scope; repository instructions and verification reference; workspace reference |
| Submission receipt | Same dispatch ID; pending, accepted, rejected or unknown; external execution identity when established; attributed sender and reason |
| Run observation | Queued, running, needs approval, completed, failed, cancelled or unknown; correlation IDs and bounded evidence references |

Credentials are resolved in the assigned context and excluded from these records.
A delivery acknowledgement maps to pending until worker acceptance is established.
Completion must be checked against GitHub before advancing the workflow. Reusing
a dispatch ID returns its existing claim or status. Cancellation is capability-
checked; unsupported or unconfirmed cancellation keeps the work reserved until
the earlier execution is reconciled or confirmed quiescent.
