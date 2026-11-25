# T02 Windows capability provenance: decision note

**Proposal only.** The release binding and direct entry points stay disabled.
This note specifies no installation procedure and grants no use of native
processes, real capture credentials, provider access, or a live operation.

## Decision

Decide whether a process running as the interactive Windows user is outside
the trusted computing base. Recommended: **yes**. Have Lead choose a narrowly
privileged, separately identified Windows principal for a protected broker,
and define an equivalent isolation option only if it enforces the same
boundary. If Lead instead trusts all code running as the operator principal,
record that different threat model explicitly; do not present it as
independent same-user provenance.

## Proposed trust boundary

- A protected broker is authorized to start only the reviewed coordinator,
  supervisor and listener roles; it is not a general launch, delegation or
  termination facility. It starts them using reviewed, pinned artifacts and
  configuration that the operator identity cannot modify. Pin the interpreter,
  fixed entry sources and dependencies, and role configuration as one reviewed
  release. The broker does not hold the capture provider secret or acquire
  access to unrelated processes or state.
- The interactive client may request only the existing exact capture packet
  and approval references through the designated local channel. It cannot
  supply trusted object handles or launch targets. The broker/independent
  coordinator supplies only its own run- and role-bound capabilities. Kernel
  object type, process image, a claimed database and packet MAC are supporting
  checks, not substitutes for authenticated operating-system provenance.
- The broker never substitutes for independent owner and Lead source approval,
  the exact local checkout binding, the durable one-use reservation, or the
  original cutoffs. A timeout, incomplete handoff or uncertain cleanup remains
  held; an empty Job is not positive evidence of a root exit never observed.

## Acceptance, before any release

1. Show in a synthetic policy harness that untrusted caller-origin input,
   unsupported role, wrong release pin, wrong run binding, stale authorization,
   duplicate start and missing/changed receipt are denied without starting a
   role. Test that broker failure remains fail-closed.
2. A fixture for the selected topology can be **authored now** using fake
   provider and provenance decisions and fixed harmless stand-ins at the
   capture-role boundary. Exercise the same dispatch, child handoff, durable
   ownership, receipts and cutoff path; it must not introduce a bypass or
   activate the real listener/tunnel. Such a fixture can prove composition,
   not the chosen Windows principal or pin policy.
3. A new separately authorized bounded native fixture must verify the chosen
   provenance model and selected Windows process/Job graph with harmless
   stand-ins. Include positive exact-root/empty-Job observations while
   startup is stalled, an independent cleanup witness, and an unconfirmed
   case that reports `cleanup-unknown`. Use no live provider, network role,
   production keys, or operational packet. An earlier fixture testing a
   different graph does not count.

Lead must supply the approved trust boundary and supported protected-executor
model, plus the exact harmless native fixture contract. Deployment, release
pins for real assets, and operation approval remain separate.
