# Lighthouse Verification Contract

## Current scope

The project contains governing documentation and an installable Python CLI
foundation. Verification commands below remain offline. The [T01 capability
report](../../experiments/codex-review/README.md) separately records one exact-head,
owner-authorized live proof and COMMENT. This contract grants no live authority.
The [T02 Phase A assessment](../../experiments/dot-events/README.md) and known-worker experiment authorize no live setup or execution. No production orchestration or CI is configured.

Run the following commands from the repository root in PowerShell. A failed
command is a failed check. Record the checked commit and working-tree state in
the PR; describe self-review as self-review.

## Documentation checks

For an uncommitted change, check whitespace with:

```powershell
git diff --check
git diff --cached --check
```

For a committed task branch targeting `development`, check the whole PR change:

```powershell
git diff --check origin/development...HEAD
```

Check local Markdown file targets with this block. It covers the root entry
points and documentation tree, skips external URLs and same-file fragments,
and checks file or directory existence. Heading anchors and link meaning still
require review.

```powershell
$markdownFiles = @('README.md', 'AGENTS.md', '__ai__.md')
$markdownFiles += @(Get-ChildItem -LiteralPath 'docs' -Recurse -File -Filter '*.md' |
    Select-Object -ExpandProperty FullName)
$markdownFiles += @('experiments/codex-review/README.md', 'experiments/codex-review/__ai__.md', 'experiments/dot-events/README.md', 'experiments/dot-events/__ai__.md')
$brokenLinks = @(
    foreach ($file in $markdownFiles) {
        $resolved = (Get-Item -LiteralPath $file).FullName
        $content = Get-Content -Raw -LiteralPath $resolved
        foreach ($match in [regex]::Matches($content, '(?<!!)\[[^\]]+\]\(([^)]+)\)')) {
            $target = ($match.Groups[1].Value -split '#', 2)[0]
            if (-not $target -or $target -match '^[A-Za-z][A-Za-z0-9+.-]*:') {
                continue
            }
            $destination = Join-Path (Split-Path -Parent $resolved) $target
            if (-not (Test-Path -LiteralPath $destination)) {
                '{0}: {1}' -f $file, $target
            }
        }
    }
)
if ($brokenLinks.Count -gt 0) {
    $brokenLinks
    throw 'Broken Markdown file targets.'
}
Write-Output ('Markdown file targets: PASS ({0} documents)' -f $markdownFiles.Count)
```

For standards adoption or later standards updates, compare the complete change
with the approved source and explicitly authorized adaptations. Review each
affected document as a whole to confirm its meaning remains intact. Architecture
and planning documents must preserve the distinction between observed capability,
approved design, unproven candidates and bounded implementation authority.

## Windows Python foundation

Use existing CPython 3.14.x on Windows AMD64. From the repository root, create
a fresh `.venv` with that interpreter (`python -m venv .venv`). Run:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
.\.venv\Scripts\python.exe -m lighthouse --help
.\.venv\Scripts\python.exe -m lighthouse --version
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src/lighthouse
```

Use a second, fresh venv created by the same interpreter in a new temporary
directory outside the checkout. Run the same commands from the checkout with
that venv's absolute Python path. Compare the two `python -m pip list
--format=freeze` outputs by package and version; they must match. Also use the
second venv from outside the repository root to run both `python -m lighthouse
--help` and `python -m lighthouse --version`, without changing `PYTHONPATH`.
Verify an invalid argument exits nonzero. Tests exercise these installed CLI
paths and guard against integration side effects.

Record the exact checks and exit statuses, interpreter and tool versions,
checked commit and tree state, and current review head in the PR. This is local
verification, not CI or evidence of a live integration.

### Regenerate the development lock deliberately

In a clean scratch venv on the supported target, use the pip version pinned in
the current lock (or review an intentional change to that pin). Resolve the
build requirements and development extras listed in `pyproject.toml`, including
their dependencies, against a trusted package index. Do not install Lighthouse
in this resolver venv. Capture `python -m pip list --format=freeze`, review
the resulting versions including pip and transitive dependencies, and update
`requirements-dev.lock` with exact pins only. Update the declared direct
requirements if their pins change. Never include local paths, credential-bearing
index URLs, or editable entries. Validate by repeating the two fresh installs
and checks above. This establishes version repeatability on the documented
target, not a byte-identical or offline build guarantee.

## Offline Codex review experiment

From the repository root on Windows AMD64 with existing CPython 3.14.x, use
a fresh experiment venv. The lock is separate from the foundation lock.

```powershell
python -m venv experiments/codex-review/.venv
.\experiments\codex-review\.venv\Scripts\python.exe -m pip install --no-deps -r experiments/codex-review/requirements.lock
.\experiments\codex-review\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
.\experiments\codex-review\.venv\Scripts\python.exe -m pip check
.\experiments\codex-review\.venv\Scripts\python.exe -m pytest -q tests experiments/codex-review
.\experiments\codex-review\.venv\Scripts\python.exe -m ruff check .
.\experiments\codex-review\.venv\Scripts\python.exe -m mypy src/lighthouse experiments/codex-review
.\experiments\codex-review\.venv\Scripts\python.exe experiments/codex-review/proof.py --help
.\experiments\codex-review\.venv\Scripts\python.exe experiments/codex-review/proof.py --dry-run
git diff --check origin/development...HEAD
git diff --cached --check
```

Retain the foundation installed-module smoke from outside the checkout. The
experiment's SDK package is installed for offline schema verification only.
Do not run an executable from its runtime package. Any requests for a live
runtime launch, sign-in, approval, real review or publication are out of
scope here. The [experiment report](../../experiments/codex-review/README.md)
distinguishes fake coverage from the completed one-use live proof. Its consumed
packet is not approval for another run.

The experiment test suite includes fake-clock role-cutoff and authenticated
attestation tests, and on Windows one harmless Python-only Job Object test.
The fixture verifies local containment and shutdown, never an SDK or remote
provider lifecycle. The ordinary CLI does not start subprocesses.

The same offline suite exercises the operator entry and private child roles
through injected job, transport and SDK doubles. Do not supply real operator
settings or execute the opt-in entry as part of preparation verification.

For the offline startup diagnostics, cover startup, initialization/runtime,
managed account, thread start and policy/identity validation, permission hold
and SDK close failure using fresh synthetic inputs. Verify private records are
correlated to dispatch, exact head and packet digest, and the primary reason is
present before close and unchanged if close fails. Assert no review intent,
model call or publisher effect on these early holds. Tool discovery checks
must use installed source or inert package metadata only; do not execute the
bundled runtime.

For the separate checkout proof, inject fake Git and SDK responses. Include
absent thread Git metadata with valid proof; reject conflicting metadata,
wrong root/origin/head/cwd, dirty review content, unavailable or malformed
tool results, stale proof before dispatch, and elapsed time. The private
`git_executable` setting is not an authorization record or model input. No
real SDK or external Git discovery is needed in these fixtures.

Snapshot boundary verification must exercise the exact immutable bytes through the inert load_request preflight, entry, private stage and typed fake SDK. Cover prepared sizes, each inclusive UTF-8 byte cap, one byte over, invalid encoding/hash/text, no initial claim or role for rejected inputs, complete input delivery for accepted bytes, and a fixed private correlated rejection after copied-input drift. Never use real operator settings, snapshots or credentials.

For pinned initialize metadata, run the public JSONL startup request
against an inert wire through the wrapper and worker. Verify matching
public userAgent-only build metadata reaches only typed fake gates, and
missing, malformed, prerelease, mismatched or contradictory metadata
cannot reach account, thread or review activity. The correlated fixed
initialization failure must survive a fake close failure. Do not read a
private SDK version attribute or use the client-requested version as
runtime evidence.

For review collection, inject inert JSONL byte streams/process factories
through the assembled adapter, worker and private stage. Compare the pinned
SDK's actual pre-acknowledgement notification loss with the public wire
retaining source-shaped matching item/completion signals in that order.
Exercise post-acknowledgement/interleaved orders, terminal with no items,
no parent turn/started, foreign/duplicate/conflicting IDs or output, missing
and fallback output, malformed frames, count/byte overflow, server errors,
EOF, permission before acknowledgement and during blocking collection,
deadlines, exact interruption and failed cleanup. Assert no replay,
no publication on holds and no bypass of parent-confirmed shutdown even
for an exact terminal and private completion. Do not inspect existing
private history, start the actual runtime or infer the old mismatching ID.

For the custom-target budget, synthetic request, acknowledgement
userMessage and enteredReviewMode must share the same complete target.
Exercise at least 383,589 raw input bytes with escaping and multibyte
text, accepted raw and encoded boundaries, and the first unsupported
encoding. Verify outgoing thread/review envelope sizes and both known
pinned echoes before verifier/claim, with no provider imports in inert
entry. Test raw-frame, retained-projection and event-count limits
separately. The sixth observed overflow is not raw provider-frame evidence.

## Offline Dot known-worker experiment

Use the unchanged Windows experiment lock in both existing verification
environments. From the root, extend the existing offline suite and run:

```powershell
.\experiments\codex-review\.venv\Scripts\python.exe -m pytest -q tests experiments/codex-review experiments/dot-events
.\experiments\codex-review\.venv\Scripts\python.exe -m mypy src/lighthouse experiments/codex-review experiments/dot-events
.\experiments\codex-review\.venv\Scripts\python.exe experiments/dot-events/t02_proof.py --help
.\experiments\codex-review\.venv\Scripts\python.exe experiments/dot-events/t02_proof.py --dry-run
```

Repeat with the other environment's exact executable and retain both pip checks,
package/version comparison, Ruff, T01 help/dry-run, outside-checkout installed
foundation CLI smoke, local Markdown targets, whitespace and exact-head checks.
Record the SQLite library version and observe actual fixture effects after
contention and restart. A fake acknowledgement, attributable fake turn,
committed intent and local marker receipt are distinct observations. Only
bounded Python test helpers may spawn; no real task continuation, service,
history, runtime, network or credentials belong to these checks.

## Offline event-eligibility preparation

Run the unchanged two-environment offline verification above. From the
repository root in each, additionally run:

```powershell
.\experiments\codex-review\.venv\Scripts\python.exe experiments/dot-events/t02_events_probe.py --help
.\experiments\codex-review\.venv\Scripts\python.exe experiments/dot-events/t02_events_probe.py
.\experiments\codex-review\.venv\Scripts\python.exe experiments/dot-events/t02_events_probe.py --dry-run
.\experiments\codex-review\.venv\Scripts\python.exe experiments/dot-events/t02_events_probe.py --live
```

The final command must reject with exit 2 before constructing anything; it
is not a live test. The combined pytest and mypy targets already cover the
probe. Verify request effects, one durable stop, exact-byte signatures and
shared send budget across synthetic restart. The fake provider/lifecycle
assertions do not establish actual authority, private eligibility, runtime
containment or coordinator receipt.

The assembly tests use provider-shaped responses and injected loopback,
DNS/TLS and lifecycle doubles; assert exact effect order, deny construction
for bad packet/evidence, and deny new effects if any authority read returns
after expiry. Already-attempted roles still require independent terminal
confirmation under the original deadline. No actual provider request, socket,
process, evidence from real approval records or private files is allowed.

Run the dormant backend checks as part of both full suites. Replace standard
library HTTP, TLS, socket and Win32 operations at their boundaries. Count real
adapter-method calls under fakes. The disabled public entry must reject before
opening private files or constructing a provider or process role. No successful
live admission or provider compatibility is asserted by the offline checks.


### Designated T02 native ownership fixture

On Windows and in each retained environment, run this named group to retain
witness timings for the same process owner used by the fixed vendor role:

```powershell
.\experiments\codex-review\.venv\Scripts\python.exe -m pytest -q -s experiments/dot-events/test_t02_event_native.py
```

There are three sequential cases: explicit stop, owner-process loss, and a
fixture-only negative control with kill-on-close disabled. Each
has at most three fixed harmless Python processes (supervisor, root and
descendant), a 20-second outer deadline plus a 3-second cleanup reserve.
No vendor, sockets, credentials, installation or runtime setup is involved.
The parent witness holds both exact process handles before release and
requires both exit signals within a separate two-second causal window before
helper fallback. The negative control must fail that same condition, and its
separate fixture-owned cleanup must be witnessed. A request is not proof. The
backend network and Win32 exception tests and the capture tests remain fake
only. Run the full suite and prior inert CLI checks unchanged.

## Offline capture-only preparation

Use the dedicated hold-only entry in both retained Windows environments:

```powershell
.\experiments\codex-review\.venv\Scripts\python.exe experiments/dot-events/t02_capture_operator.py --help
.\experiments\codex-review\.venv\Scripts\python.exe experiments/dot-events/t02_capture_operator.py --dry-run
.\experiments\codex-review\.venv\Scripts\python.exe experiments/dot-events/t02_capture_operator.py --execute
```

The last command must exit 2. No packet reads, networking, listener, runtime,
subscription, or callback transport belongs to this entry. The capture evidence
fixture verifies the fixed approval scope, current issue/PR metadata, trusted
records and expiry, including oversized UTF-8 envelopes under the existing 32 KiB
cap. It checks an exact digest projection only; it does not parse a real operator
packet at the CLI, attest a local host or checkout, execute a real one-use run, or
prove startup, durable stop and independently bounded shutdown. No operational
prepare/status/run commands exist yet. Do not infer vendor or hosted readiness.

The dormant capture operator model now includes version 1 strict packet parsing,
domain-separated SHA-256 over sorted compact ASCII JSON, and a single
operation-bound SQLite store. The packet binds the fixed repository, issue, PR,
scope, protocol, loopback address, event and runtime version; the exact head,
opaque identities, local file references, pinned artifact hashes, and bounded
activation, intake and cleanup times complete the digest. Syntax checks on
Windows path text do not attest a checkout, reparse status, executable or key.

The fake composition passes the canonical digest into the capture-specific
provider verifier, commits a single run claim before starting any roles, and
seals intake through the existing candidate store. A fresh read confirms sealed
intake only, never process shutdown. The injected role owner receives one
original monotonic cutoff; the application signals all attempted roles before
waiting, and a failed or late independent observation returns cleanup unknown.
Tests do not establish a real independent watchdog or Windows containment for
this operator. An actual operator must not be exposed until that owner exists
and is independently verified. The command above continues to reject execute.

The separate watchdog policy is fake-verified only. Its future host must own
the listener and runtime independently of the application controller. It must
observe both exact role exits under the same cutoff even if controller or
handler work stalls. The current in-process listener and synchronous Windows
role adapter are not that host. Do not enable execution based on these tests.

The dormant Windows host adapter requests creation-time Job membership
(STARTUPINFOEX / PROC_THREAD_ATTRIBUTE_JOB_LIST) before resume. It is tested
with a fake kernel only, with no fallback to late assignment. The supervisor
state machine and controller reject late or contradictory role receipts in
synthetic tests. The fixed native host entry still denies direct invocation:
private native control transport, exact listener/runtime-owned handles and
independent scheduling are not connected. A fake status receipt is not native
quiescence evidence.

The Windows channel components provision two private one-way overlapped pipes
and a separate manual stop event. Only the three intended child handles may
appear in the process startup inheritance list. The controller and host use
bounded, correlated, ordered frames with no caller-selected executable or
target. Timeout stops ordinary I/O; an unconfirmed cancelled operation stays
quarantined. Job/root pairs can move to one watchdog owner without reopening
by PID. Exact exit and empty Job are required; a closed handle is not evidence.

All new calls are tested with injected fake I/O or fake kernel capabilities.
The concrete peer bootstrap, separately owned listener role, pinned runtime
composition, and integrated native cessation proof are not connected.

The fixed peer bootstrap is exercised only with injected capability events
and role endpoints. It accepts the provisioned child handle tuple, runs a
bounded fixed message sequence and stops both roles. The native helper entry
does not yet consume a real authenticated descriptor or implement simultaneous
stop-event / overlapped-command waiting. The separate listener and pinned
runtime are not bound to that entry. No claim of real readiness or native
quiescence follows from this checkpoint.

The exact opaque Dot profile route is validated and preserved in the packet
digest without making a request or deriving worker identity. The vendor archive
must match the existing tracked pin. The fixed role factories select only the
capture receiver over local loopback and the reviewed pinned runtime with
creation-time Job binding.

The native peer can wait on overlapped I/O and the independent stop event
together; the sole supervisor terminal owner seals and verifies the canonical
SQLite store, without a controller finalizer in that mode. Test these boundaries
with fake Win32 and simulated clock/capabilities. These are still dormant code
components, not a complete native executable graph. The authenticated child
descriptor/bootstrap, an independently owned listener process and detached
deadline supervision through stalled native role startup remain open.

The remaining native causal proof requires a closed harmless Python-only fixture
with two fixed stand-in roles and a deliberately stalled controller, in both
retained Windows environments. Capture exact handles before the stall, verify
both root exit signals and empty Job accounting before the original deadline,
and exercise a no-containment negative followed by separately witnessed cleanup.
Do not substitute vendor execution, socket binding, real private inputs, or
self-expiry. No such native case was executed for this checkpoint.

The bounded capture witness command is opt-in. From the root, set
`LIGHTHOUSE_T02_CAPTURE_NATIVE_PROOF=1` for the test process and run
`python -m pytest -v experiments/dot-events/test_t02_capture_native_proof.py`
using the two retained Windows verifiers. It starts only two fixed isolated
Python sleepers per case. The positive witnesses confirm exact root exits
and empty Jobs in the fixed window while the controller thread is idle; the
negative disables watchdog signaling, observes both roots alive at the same
cutoff and exercises independent explicit cleanup. This is a native Job and
handle witness, not proof of the detached multi-process production graph.

The inherited descriptor is bounded and compared to the claimed operation.
Separate fixed listener/helper logic, dormant local path/artifact checks and
detached cleanup policy are present and checked with fakes. Direct entry still
refuses operation. The native process graph must bridge the trusted child
descriptor into the admitted packet/store, deliver initial role capabilities
to a detached watchdog before a blocked start, and prove its termination path
without substituting the thread-stall fixture for production readiness.

Capture bootstrap now bounds both inherited monotonic cutoffs against a fresh
conservative sample of the approved wall window. A normal stop preserves the
one overlapped read for terminal status, with no partial-frame reread.
The detached Job owner's two original Job handles remain retained; the fixed
helper launch inherits only the three pipe/event endpoints and two child
Job duplicates. The canonical packet and exact claimed store file identity
are authenticated over the same private pipe, and SQLite consumes the
one child transfer before any listener/runtime factory. Offline fakes exercise
the parent authoring/sending and child transfer/admission/role ordering together.
No native child graph or production local binding is certified; the executable
entry remains hard denied, and allocating a Job does not certify role exit.
