"""Selected controller-to-coordinator-to-role capture graph with in-memory OS ports."""

from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread, local
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
import t02_capture_coordinator_windows as coordinator
import t02_capture_host_entry as supervisor
import t02_capture_native_composition as selected
import t02_capture_native_cutoff as cutoff
import t02_capture_native_peer as peer
import t02_capture_owned_jobs as jobs
import t02_capture_roles as roles
import t02_capture_windows_ownership as ownership
import t02_event_loopback as loopback
import t02_event_windows as windows
from t02_capture_bootstrap import ENVIRONMENT_KEY
from t02_capture_composition import open_existing_capture
from t02_capture_packet import CapturePacket
from t02_capture_pipe_owner import CapturePipeHandles
from t02_event_evidence import API_ROOT, MAX_PROVIDER_BYTES, ProviderReply
from t02_event_types import EVENT, VERSION, encode
from t02_events_probe import SECRET
from test_t02_capture_coordinator import source
from test_t02_capture_evidence import ACTIVATION, Provider
from test_t02_capture_lifecycle import local_observation, record

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows canonical fixture paths")


class Pipe:
    def __init__(self, incoming: Queue[bytes], outgoing: Queue[bytes], stop: Event) -> None:
        self.incoming, self.outgoing, self.stop = incoming, outgoing, stop
        self.buffer = bytearray()

    def write(self, data: bytes, _deadline: int) -> None:
        self.outgoing.put(data)

    def read(self, length: int, _deadline: int) -> bytes:
        if not self.buffer:
            self.buffer.extend(self.incoming.get(timeout=5))
        data = bytes(self.buffer[:length])
        del self.buffer[:length]
        return data

    def terminal_deadline(self, normal: int) -> int:
        return normal

    def stopped(self) -> bool:
        return self.stop.is_set()

    def signal_stop(self) -> None:
        self.stop.set()


class MemoryTcp:
    """Substitute the socket boundary but keep the selected RPC and listener adapter."""

    def __init__(self) -> None:
        self.pending: Queue[Connection] = Queue()
        self.closed = Event()

    def bind(self, address: tuple[str, int]) -> None:
        assert address == ("127.0.0.1", 8765)

    def listen(self, size: int) -> None:
        assert size == 1

    def setsockopt(self, *_: object) -> None:
        pass

    def settimeout(self, _seconds: float) -> None:
        pass

    def accept(self) -> tuple[Connection, tuple[str, int]]:
        if self.closed.is_set():
            raise OSError("fake closed")
        try:
            return self.pending.get(timeout=0.025), ("127.0.0.1", 50000)
        except Empty:
            raise TimeoutError from None

    def close(self) -> None:
        self.closed.set()

    def fileno(self) -> int:
        return -1 if self.closed.is_set() else 1

    def __enter__(self) -> MemoryTcp:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def request(self, content: dict[str, object]) -> bytes:
        request = Connection(content)
        self.pending.put(request)
        return request.reply.get(timeout=1)


class Connection:
    def __init__(self, content: dict[str, object]) -> None:
        body = encode(content)
        self.message = (
            b"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:8765\r\nContent-Type: application/json\r\n"
            b"Accept: application/json, text/event-stream\r\nMCP-Protocol-Version: "
            + VERSION.encode() + b"\r\nAuthorization: Bearer " + b"T" * 32 + b"\r\nContent-Length: "
            + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        self.reply: Queue[bytes] = Queue()

    def settimeout(self, _seconds: float) -> None:
        pass

    def recv(self, length: int) -> bytes:
        result, self.message = self.message[:length], self.message[length:]
        return result

    def sendall(self, data: bytes) -> None:
        self.reply.put(data)

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *_: object) -> None:
        pass


@pytest.mark.parametrize("case", ("public", "foreign-head", "foreign-app", "foreign-bot"))
def test_selected_graph_durably_captures_and_reopens_without_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    fields = record() | {
        "state": str(tmp_path / "capture.db"), "runtime_executable": str(tmp_path / "tunnel-client-runtime.exe"),
        "tunnel": "tunnel_" + "a" * 32, "organization": "org-fixture123",
        "intake_cutoff_ms": ACTIVATION + 3500, "cleanup_cutoff_ms": ACTIVATION + 6000,
    }
    packet = CapturePacket.parse(encode(fields))
    store = open_existing_capture(packet)
    store.prepare()
    class ExactProvider(Provider):
        def read(self, path: str, *, deadline_ms: int, limit: int) -> ProviderReply:
            assert limit == MAX_PROVIDER_BYTES and ACTIVATION < deadline_ms <= packet.intake_cutoff_ms
            self.calls += 1
            return ProviderReply(200, encode(self.records[path.removeprefix(API_ROOT)]))

    fake = ExactProvider()
    source(packet, fake)
    lead = fake.records["/issues/comments/2"]
    expected_app = lead["performed_via_github_app"]
    assert isinstance(expected_app, dict) and type(expected_app["id"]) is int
    lead["performed_via_github_app"] = None
    if case == "foreign-head":
        fake.records["/pulls/15"]["head"] = {"sha": "b" * 40}
    elif case == "foreign-app":
        lead["performed_via_github_app"] = {"id": expected_app["id"] + 1}
    elif case == "foreign-bot":
        lead["user"] = {"id": 42, "type": "Bot"}
    original = time.monotonic_ns()
    def mono() -> int:
        return (time.monotonic_ns() - original) // 1_000_000

    tcp = MemoryTcp()
    env = local()
    number = iter(range(100, 1000))
    ends: dict[tuple[int, int, int], Pipe] = {}
    stops: dict[int, Event] = {}
    root_done: dict[int, Event] = {}
    members: dict[int, set[int]] = {}
    job_alias: dict[int, int] = {}
    threads: list[Thread] = []
    launched: list[str] = []
    children: dict[str, int] = {}
    errors: Queue[BaseException] = Queue()

    def new_pipe(_clock: Callable[[], int]) -> Mock:
        ctl = (next(number), next(number), next(number))
        child = (next(number), next(number), next(number))
        incoming: Queue[bytes] = Queue()
        outgoing: Queue[bytes] = Queue()
        stop = Event()
        ends[ctl] = Pipe(incoming, outgoing, stop)
        ends[child] = Pipe(outgoing, incoming, stop)
        stops[ctl[-1]] = stops[child[-1]] = stop
        pipe_owner = Mock()
        pipe_owner.prepare.return_value = CapturePipeHandles(ctl, child)
        return pipe_owner

    def pipe_for(read: int, write: int, stop: int, _clock: Callable[[], int], **_: object) -> Pipe:
        return ends[(read, write, stop)]

    def create_job(*_: object) -> int:
        job = next(number)
        members[job] = set()
        return job

    def actual(job: int) -> int:
        return job_alias.get(job, job)

    def duplicate(handle: int, _inheritable: bool) -> int:
        copy = next(number)
        if actual(handle) in members:
            job_alias[copy] = actual(handle)
        else:
            root_done[copy] = root_done[handle]
        return copy

    def query(job: int, _class: int, data: Any, _size: int, _ignored: object) -> bool:
        observation = ctypes.cast(data, ctypes.POINTER(windows._Accounting))
        observation.contents.active = sum(not root_done[handle].is_set() for handle in members[actual(job)])
        return True

    def wait_handle(handle: int, duration: int) -> int:
        event = stops[handle] if handle in stops else root_done[handle]
        return 0 if event.wait(min(3.0, duration / 1000)) else 258

    def terminate(job: int, _code: int) -> bool:
        # Python fake helpers finish their epilogue; only vendor stub requires a synthetic kill.
        for handle in members[actual(job)]:
            if handle == runtime_root[0]:
                root_done[handle].set()
        return True

    kernel = Mock()
    kernel.CreateJobObjectW.side_effect = create_job
    kernel.SetInformationJobObject.return_value = True
    kernel.CloseHandle.return_value = True
    kernel.QueryInformationJobObject.side_effect = query
    kernel.TerminateJobObject.side_effect = terminate
    kernel.WaitForSingleObject.side_effect = wait_handle
    runtime_root: list[int] = [0]

    def spawn(
        target: windows._OwnedWindowsJob, exe: Path, args: list[str], values: dict[str, str],
        _deadline: int, *, before_resume: Callable[[int, int], None] | None = None,
        bind_at_creation: bool = False, inherited: tuple[int, ...] = (),
        preowned_job: int | None = None,
    ) -> bool:
        assert bind_at_creation and target._process is None
        job = preowned_job or create_job()
        root = next(number)
        target._job, target._process, target._k = job, root, kernel
        target._attempted = target._assigned = True
        root_done[root] = Event()
        members[actual(job)].add(root)
        if before_resume is not None:
            before_resume(job, root)
        if exe.name == "tunnel-client-runtime.exe":
            assert args[0] == "run" and preowned_job is not None and not inherited
            launched.append("runtime")
            runtime_root[0] = root
            assert b"200" in tcp.request({"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
                "protocolVersion": VERSION, "clientInfo": {}, "capabilities": {},
            }})
            assert b"202" in tcp.request({"jsonrpc": "2.0", "method": "notifications/initialized"})
            reply = tcp.request({"jsonrpc": "2.0", "method": "events/subscribe", "id": 2, "params": {
                "name": EVENT, "arguments": {"proof_id": packet.proof_id},
                "delivery": {"mode": "webhook", "url": "https://synthetic.example/candidate", "secret": SECRET},
            }})
            assert b"synthetic.example" not in reply and b"error" in reply
            return True
        name = Path(args[1]).stem
        assert exe.name == "python.exe" and set(values) == {ENVIRONMENT_KEY, trusted.CHILD_LEDGER}
        assert len(inherited) in (3, 5)
        dispatch = {
            "t02_capture_coordinator_entry": coordinator_main,
            "t02_capture_supervisor": run_native_supervisor_entry,
            "t02_capture_listener": run_native_listener_entry,
        }[name]
        launched.append(name)
        def run() -> None:
            try:
                env.environ = values
                children[name] = dispatch()
            except BaseException as exc:
                errors.put(exc)
            finally:
                root_done[root].set()
        thread = Thread(target=run, daemon=True)
        threads.append(thread)
        thread.start()
        return True

    import t02_capture_installation as installation
    import t02_capture_trusted as trusted
    from t02_capture_composition import (
        run_native_listener_entry,
        run_native_supervisor_entry,
    )
    from t02_capture_coordinator_entry import main as coordinator_main
    from t02_capture_trusted import Role

    python = tmp_path / "python.exe"
    python.write_bytes(b"inert executable data")
    checkout = Path(str(fields["checkout"]))
    profile = installation.CaptureInstallation.parse(encode({
        "version": 1, "scope": "lighthouse-t02-callback-capture-only",
        "repository": str(fields["repository"]), "roles": ["coordinator", "supervisor", "listener"],
        "checkout": str(checkout), "host": str(fields["host"]), "release": packet.approval.head,
        "git": str(tmp_path / "git.exe"), "git_sha256": "a" * 64,
        "python": str(python), "python_sha256": "b" * 64,
        "archive": str(fields["runtime_archive"]), "archive_sha256": fields["runtime_archive_sha256"],
        "runtime": str(fields["runtime_executable"]), "runtime_sha256": fields["runtime_executable_sha256"],
    }), checkout, str(fields["host"]))
    assert profile.matches(packet)
    observe = Mock(return_value=replace(local_observation(packet), canonical_non_reparse_files=tuple(
        str(fields[key]) for key in ("runtime_archive", "runtime_executable", "platform_key", "loopback_bearer", "state")
    )))

    def factory(role: Role | None = None) -> selected.InstalledCapture:
        return installation.assemble_installation(
            profile, python, role, bound_child=lambda selected_role, clock: trusted.read_child_binding(
                selected_role, clock, checks=lambda: (lambda _: True, lambda _: True, lambda _: True),
            ),
        )

    monkeypatch.setattr(selected.ReviewedHost, "observe", observe)
    monkeypatch.setattr(installation, "select_installation", factory)
    monkeypatch.setattr(trusted, "os", env)
    for mod in (selected, ownership, roles):
        monkeypatch.setattr(mod, "CapturePipeOwner", new_pipe)
    for mod in (coordinator, supervisor, ownership, peer, roles):
        monkeypatch.setattr(mod, "WindowsCapturePipe", pipe_for)
    import t02_capture_transfer as transfer
    monkeypatch.setattr(transfer, "WindowsCapturePipe", pipe_for)
    for mod in (selected, ownership, supervisor):
        monkeypatch.setattr(mod, "GitHubHttps", lambda _clock: fake)
    for mod in (cutoff, jobs):
        monkeypatch.setattr(mod, "_kernel", lambda: kernel)
    import t02_capture_role_handles as witnesses
    monkeypatch.setattr(witnesses, "_kernel", lambda: kernel)
    for mod in (selected, ownership):
        monkeypatch.setattr(mod, "os", env)
    monkeypatch.setattr(selected, "mono", mono)
    monkeypatch.setattr(selected, "wall", lambda: ACTIVATION)
    monkeypatch.setattr(ownership, "_duplicate", duplicate)
    monkeypatch.setattr(ownership, "importlib", SimpleNamespace(import_module=lambda _: kernel))
    monkeypatch.setattr(windows._OwnedWindowsJob, "_start_owned", spawn)
    monkeypatch.setattr(windows.RuntimeRole, "verified_digest", lambda *_: "e" * 64)
    monkeypatch.setattr(roles, "_read_capture_secret",
                        lambda _p, field, *_: "T" * 32 if field == "loopback_bearer" else "fixture-key")
    monkeypatch.setattr(loopback, "socket", SimpleNamespace(AF_INET=2, SOCK_STREAM=1, socket=lambda *_: tcp))
    from t02_capture_composition import execute_capture
    try:
        result = execute_capture(packet, 1, 2)
    except Empty:
        if not errors.empty():
            raise errors.get() from None
        pytest.fail(str((children, launched, store.status(), fake.calls)))
    for thread in threads:
        thread.join(4)
        assert not thread.is_alive()
    if not errors.empty():
        raise errors.get()
    if case != "public":
        assert result == "denied" and store.status() == ("prepared", "new")
        assert not launched and not stops and not members
        observe.assert_not_called()
        return
    assert result == "candidate-held", (children, launched, store.status())
    assert children == {name: 0 for name in launched if name != "runtime"}
    assert launched == ["t02_capture_coordinator_entry", "t02_capture_supervisor", "t02_capture_listener", "runtime"]
    assert store.status() == ("stopped", "captured")
    assert execute_capture(packet, 1, 2) == "admission-unknown"
    assert len(launched) == 4
