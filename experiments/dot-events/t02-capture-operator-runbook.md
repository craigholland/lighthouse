# Capture-only operator runbook

This draft is offline evidence, not authorization to execute. The checked-in
operator prints help by default, and a complete direct execute command is held
before the packet is opened. There is no environment setting, CLI flag or
operator assertion that enables the reviewed release gate. Do not run the
listener, pinned runtime, or provider proof until an independently reviewed
release and separate exact owner and Lead approvals exist.

## Inert commands

From the isolated checkout, the following list or describe only synthetic
preparation. They do not read a packet, credentials, or provider records:

~~~powershell
python experiments/dot-events/t02_capture_operator.py
python experiments/dot-events/t02_capture_operator.py --help
python experiments/dot-events/t02_capture_operator.py --dry-run
~~~

The following examples are for a **disposable synthetic** packet and state
path only. They do not contact a provider, bind a listener, or start any helper:

~~~powershell
python experiments/dot-events/t02_capture_operator.py --prepare --packet C:\synthetic\packet.json
python experiments/dot-events/t02_capture_operator.py --status --packet C:\synthetic\packet.json
~~~

Prepare exclusively creates one new empty, bound SQLite store at the exact
packet state path. It cannot claim, overwrite, repair or reset a store. Status
opens an existing store read-only and reports run state and candidate
disposition only. It rejects missing, foreign, corrupt, and observed path
changes; it does not authenticate pre-run approval or substitute for the
native file-identity witness during transfer. No candidate URL, secret,
private selector or local path should appear in output. Keep the database
private. Never copy or replace it to restart a claim.

## Exact private packet and approval format

The [packet parser](t02_capture_packet.py) is the schema authority. Use a
canonical ASCII JSON file, at most 8,192 bytes, at an absolute local Windows
path. Canonical bytes are JSON with keys sorted, no extra separators or
whitespace, and ASCII escapes. The digest is SHA-256 over the literal domain
lighthouse-t02-callback-capture-only/packet-v1, then a single NUL byte,
then those canonical bytes. Reordering fields or reformatting a packet is not
a way to create another approval.

The packet fixes version 1, repository craigholland/lighthouse, Issue 5,
PR 15, the capture-only scope, protocol 2025-11-25, 127.0.0.1:8765/mcp,
event lighthouse.t02.probe, and the existing Windows AMD64 runtime v0.0.21.
It also binds the complete 40-character head, the workspace, organization,
tunnel, host, opaque Dot profile URL, synthetic proof identity, principal,
unique operation ID, and the exact proof-ID-only filter. Include the six
distinct absolute local paths (checkout, archive, executable, platform key,
loopback bearer and SQLite state), the tracked archive digest, the exact
executable digest, and activation, intake cutoff and cleanup cutoff in UTC
epoch milliseconds. Intake is at most ten minutes and cleanup at most
fifteen minutes from activation. Use the exact field names and constraints in
the parser; there are no override fields.

The [approval reader](t02_capture_evidence.py) checks two distinct unedited
single-line comments on Issue 5. The owner must be the actual GitHub user and
the Lead must be the actual Lead App actor, in that order. Both must bind the
same full head, digest, scope and approved window, with the approval timestamp
at or before activation. The issue must stay open and unblocked and the exact
PR head must remain open, unmerged, draft, and based on development. A
synthetic example of the required one-line grammar (not an approval):

~~~text
Lighthouse-T02 capture approval: {"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","scope":"lighthouse-t02-callback-capture-only","not_before":2000000000000,"expires":2000000300000}
~~~

The exact held execute shape is shown for future authorized use only:

~~~powershell
python experiments/dot-events/t02_capture_operator.py --execute --packet C:\synthetic\packet.json --owner-comment 101 --lead-comment 102
~~~

No other arguments select a provider, command, route, credentials or policy.

## Future staged prerequisites and stop conditions

1. Verify the release independently and pin its reviewed code/config. Prepare
   a fresh operation-bound store in the isolated checkout workflow; do not
   retrofit a claimed, sealed or stopped store for another run.
2. Obtain and verify both exact approvals. Check the local clean exact head,
   host and pinned artifacts; require fresh usable managed credentials through
   the approved window. Missing, expired, unresolved or rotated credentials
   hold execution. Never paste or log key material, bearer or candidate.
3. Only the separately authorized fixed composition may admit a one-use
   claim. Arm independent bounded supervision and transfer the exact
   store/ownership once before listener or runtime startup. Scope is capture
   only, not sender setup, delivery continuation, support for other targets,
   or a scheduled workflow.
4. Stop at cutoff, on authorized stop, on a candidate, or on an in-scope
   failure; no automatic retry or replacement. The supervisor owns the
   terminal record. Treat unconfirmed admission or cleanup as a hold and do
   not relaunch. A stopped/captured report is a disposition, not disclosure
   of the endpoint or proof of downstream delivery.

The draft has no installed release binding. The standalone coordinator
executable accepts only a bounded private three-handle offer and does not
accept caller-supplied Job targets. It independently checks the same current
approvals and local bindings, consumes its one coordination reservation,
then creates the original supervisor and role Jobs before entering its
potentially blocking launch lane. The controller accepts only the exact
correlated receipt and a matching durable store disposition. If native
startup does not yield an exact root witness, emergency containment holds
the run as `cleanup-unknown`; empty Jobs alone do not certify root cessation.

Craig selected the [existing trusted operator account](t02-capture-provenance-design.md)
for the bounded feasibility fixture only. It checks exact run/role inheritance,
object type and owned duplicate relationships within that premise; it does
not isolate hostile code sharing the same principal. A protected broker,
new account, ACL or privilege change is out of scope. The release binding
stays absent, and a live operation remains separately gated. Prior closed
fixtures do not prove this selected graph. Old store layouts remain held
rather than migrated.

For the exact offline native witness, use only the separately opt-in
[selected native test](test_t02_selected_native.py) under the limits in the
[verification contract](../../docs/development/verification-contract.md).
The flag does not enable this operator or its helpers.
