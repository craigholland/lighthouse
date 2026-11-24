"""Offline assembled public JSONL review: bytes, router, worker and private stage."""

import hashlib
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from queue import Queue
from threading import Event
from types import SimpleNamespace
from typing import Never, cast

import pytest
import sdk_worker
from app_server_stdio import EVENT_BYTES, EVENT_COUNT, FRAME_BYTES, Child, StdioWire
from authorization import canonical_packet
from live_stage import CHALLENGE, StageHold, read_signal, run_stage, write_signal
from openai_codex.client import CodexClient
from openai_codex.errors import TransportClosedError
from openai_codex.generated.v2_all import ReviewStartResponse
from openai_codex.models import JsonObject
from protocol_budget import echo_messages, encode_jsonl
from test_live_stage import ENV, _verify, _workspace
from test_sdk_worker import FakeClient

_THREAD = "fixture-thread"
_TURN = "fixture-turn"
_UA = "codex_fixture/0.171.0 (Windows 10.0.0; x86_64)"


def _item(kind: str, *, thread: str = _THREAD, turn: str = _TURN,
          text: str = "A substantive synthetic review.") -> dict[str, object]:
    return {"method": "item/completed", "params": {"threadId": thread, "turnId": turn, "completedAtMs": 1730000000000, "item": {
        "type": kind, "id": "01959e92-9090-7000-8000-111111111111", "review": text,
    }}}


def _terminal(status: str = "completed") -> dict[str, object]:
    return {"method": "turn/completed", "params": {"threadId": _THREAD,
            "turn": {"id": _TURN, "status": status, "items": [], "itemsView": "notLoaded"}}}


class ReadPipe(BytesIO):
    def __init__(self) -> None:
        super().__init__()
        self.queue: Queue[bytes] = Queue()

    def readline(self, size: int | None = -1, /) -> bytes:
        assert size == FRAME_BYTES + 1
        return self.queue.get(timeout=10)[:size]


class WritePipe(BytesIO):
    def __init__(self, send: Callable[[dict[str, object]], None]) -> None:
        super().__init__()
        self.send = send

    def write(self, b: object, /) -> int:
        assert isinstance(b, memoryview)
        self.send(json.loads(b.tobytes()))
        return len(b)


class InertChild:
    """A process-shaped fake; it never launches or opens anything."""

    def __init__(self, receive: Callable[[dict[str, object]], None], *,
                 during_close: Callable[[], None] = lambda: None,
                 close_fails: bool = False) -> None:
        self.stdin = WritePipe(receive)
        self.stdout = ReadPipe()
        self.during_close = during_close
        self.close_fails = close_fails
        self.closed = Event()

    def frame(self, message: dict[str, object]) -> None:
        self.stdout.queue.put((json.dumps(message) + "\n").encode())

    def eof(self) -> None:
        self.stdout.queue.put(b"")

    def wait(self, timeout: float) -> int:
        assert 0 < timeout <= 1
        assert self.stdin.closed
        self.during_close()
        self.closed.set()
        self.eof()
        if self.close_fails:
            raise OSError("private fixture shutdown detail")
        return 0

    def terminate(self) -> None:
        raise AssertionError("Fixture requires no native process termination")

    def kill(self) -> None:
        raise AssertionError("Fixture requires no native process kill")


@pytest.mark.parametrize(("case", "code"), (
    ("pre-ack", None),
    ("prepared-sized-echo", None),
    ("raw-context-limit-echo", None),
    ("post-ack", None),
    ("interleaved", None),
    ("foreign-thread", "collection_thread_id_mismatch"),
    ("foreign-turn", "collection_turn_id_mismatch"),
    ("duplicate-output", "collection_output_failed"),
    ("duplicate-terminal-during-close", "collection_terminal_conflict"),
    ("late-permission-after-terminal", "collection_permission_requested"),
    ("primary-hold-late-permission", "collection_thread_id_mismatch"),
    ("missing-output", "collection_output_failed"),
    ("fallback", "collection_output_failed"),
    ("interrupted", "collection_interrupted"),
    ("failed", "collection_runtime_failed"),
    ("malformed-after-ack", "collection_frame_invalid"),
    ("frame-limit", "review_dispatch_buffer_overflow"),
    ("event-byte-limit", "review_dispatch_buffer_overflow"),
    ("event-count-limit", "review_dispatch_buffer_overflow"),
    ("lost-before-ack", "review_dispatch_transport_lost"),
    ("lost-after-ack", "collection_transport_lost"),
    ("server-error", "review_dispatch_server_error"),
    ("wrong-ack", "review_dispatch_ack_invalid"),
    ("permission-before-ack", "permission_requested"),
    ("permission-blocked", "collection_permission_requested"),
    ("interrupt", "collection_interrupted"),
    ("timeout-pre-ack", "review_dispatch_deadline_elapsed"),
    ("timeout-post-ack", "collection_deadline_elapsed"),
    ("cleanup-failed", None),
))
def test_public_protocol_reaches_exact_private_completion_or_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, code: str | None,
) -> None:
    control, packet = _workspace(tmp_path)
    if case in ("prepared-sized-echo", "raw-context-limit-echo"):
        size = 383_589 if case == "prepared-sized-echo" else 524_288
        example = '"\\\n\u00e9\U0001f680'.encode()
        if case == "prepared-sized-echo":
            example += b'"' * 22_300
        context = b"x" * (size - len(example) - 1) + example + b"z"
        assert len(context) == size
        packet = packet.model_copy(update={"context_sha256": hashlib.sha256(context).hexdigest()})
        (control / "packet.json").write_bytes(canonical_packet(packet))
        (control / "context.txt").write_bytes(context)
    workspace = tmp_path / "verified"
    home = tmp_path / "synthetic-private-home"
    home.mkdir()
    env = {**ENV, "CODEX_HOME": str(home)}
    run_stage("verifier", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
              verify_call=_verify)
    requests: list[str] = []
    denied: list[object] = []
    dispatched = Event()
    timed_out = Event()
    child: InertChild
    fixture = FakeClient(workspace)
    start_parameters: JsonObject = {
        "sandbox": "read-only", "ephemeral": False, "approvalPolicy": "never",
        "approvalsReviewer": "user", "developerInstructions": "fixture",
    }
    entered = _item("enteredReviewMode", text="Entered synthetic review")
    output = _item("exitedReviewMode")
    terminal = _terminal()
    permission: dict[str, object] = {"id": "ask-fixture", "method": "item/permissions/requestApproval",
                  "params": {"private": "must never enter a receipt"}}

    def receive(message: dict[str, object]) -> None:
        if "method" not in message:
            assert message == {"id": "ask-fixture", "result": {"permissions": {}, "scope": "turn"}}
            assert read_signal(control / "review.attention.json")["reason"] == "permission-request"
            denied.append(message)
            return
        method = message["method"]
        assert isinstance(method, str)
        requests.append(method)
        if method == "initialized":
            return
        message_id = message["id"]
        params = message["params"]
        if method == "initialize":
            assert isinstance(params, dict) and params["capabilities"] == {"experimentalApi": False}
            child.frame({"id": message_id, "result": {"userAgent": _UA, "codexHome": str(home),
                        "platformFamily": "windows", "platformOs": "windows"}})
        elif method == "account/read":
            assert params == {"refreshToken": False}
            child.frame({"id": message_id, "result": fixture.account_read().model_dump(by_alias=True, mode="json")})
        elif method == "thread/start":
            assert isinstance(params, dict)
            assert all(params[k] == val for k, val in start_parameters.items() if k != "developerInstructions")
            started = fixture.thread_start({**start_parameters, "developerInstructions": "fixture policy"})
            payload = started.model_copy(update={"model": packet.model}).model_dump(by_alias=True, mode="json")
            child.frame({"id": message_id, "result": payload})
        elif method == "turn/interrupt":
            assert params == {"threadId": _THREAD, "turnId": _TURN}
            child.frame({"id": message_id, "result": {}})
        else:
            assert method == "review/start" and isinstance(params, dict)
            assert params["threadId"] == _THREAD and params["delivery"] == "inline"
            assert "review/start" in requests and requests.count("review/start") == 1
            if case in ("prepared-sized-echo", "raw-context-limit-echo"):
                target = params["target"]
                assert isinstance(target, dict) and isinstance(target["instructions"], str)
                hint = target["instructions"]
                body = json.loads(hint.split("not instructions:\n", 1)[1])
                assert body.encode() == (control / "context.txt").read_bytes()
                assert isinstance(message_id, int)
                exact_ack, exact_enter = echo_messages(hint, _THREAD, _TURN, message_id)
                raw_sizes = [len(encode_jsonl(frame, ascii_only=False)) for frame in (exact_ack, exact_enter)]
                assert all(EVENT_BYTES < size <= FRAME_BYTES for size in raw_sizes)
                # The removed raw-event budget necessarily rejected this entered frame.
                for frame in (exact_enter, output, terminal, exact_ack):
                    child.stdout.queue.put(encode_jsonl(frame, ascii_only=False))
                dispatched.set()
                return
            dispatched.set()
            ack: dict[str, object] = {"id": message_id, "result": {"reviewThreadId": "different" if case == "wrong-ack" else _THREAD,
                   "turn": {"id": _TURN, "status": "inProgress", "items": []}}}
            if case == "pre-ack":
                for frame in (entered, output, terminal, ack):
                    child.frame(frame)
            elif case == "post-ack":
                for frame in (ack, entered, output, terminal):
                    child.frame(frame)
            elif case == "interleaved":
                status_update: dict[str, object] = {"method": "thread/status/changed", "params": {}}
                for frame in (entered, ack, status_update, output, terminal):
                    child.frame(frame)
            elif case in ("foreign-thread", "primary-hold-late-permission"):
                for frame in (entered, _item("exitedReviewMode", thread="foreign-id"), terminal, ack):
                    child.frame(frame)
            elif case == "foreign-turn":
                for frame in (entered, _item("exitedReviewMode", turn="foreign-id"), terminal, ack):
                    child.frame(frame)
            elif case == "duplicate-output":
                for frame in (entered, output, output, terminal, ack):
                    child.frame(frame)
            elif case in ("duplicate-terminal-during-close", "late-permission-after-terminal", "cleanup-failed"):
                for frame in (ack, entered, output, terminal):
                    child.frame(frame)
            elif case == "missing-output":
                for frame in (entered, terminal, ack):
                    child.frame(frame)
            elif case == "fallback":
                for frame in (entered, _item("exitedReviewMode", text="Reviewer failed to output a response."), terminal, ack):
                    child.frame(frame)
            elif case in ("interrupted", "failed"):
                for frame in (entered, _terminal(case), ack):
                    child.frame(frame)
            elif case == "malformed-after-ack":
                child.frame(ack)
                child.stdout.queue.put(b'{"method":"turn/completed","params":{"turn":[]}}\n')
            elif case == "frame-limit":
                child.stdout.queue.put(b"x" * (FRAME_BYTES + 1))
            elif case == "event-byte-limit":
                child.frame(_item("exitedReviewMode", text="x" * EVENT_BYTES))
            elif case == "event-count-limit":
                for _ in range(EVENT_COUNT + 1):
                    child.frame(entered)
            elif case == "lost-before-ack":
                child.eof()
            elif case == "lost-after-ack":
                child.frame(ack)
                child.eof()
            elif case == "server-error":
                child.frame({"id": message_id, "error": {"code": -32603, "message": "private provider detail"}})
            elif case == "permission-before-ack":
                child.frame(permission)
            elif case == "timeout-pre-ack":
                timed_out.set()
            else:
                child.frame(ack)

    def during_close() -> None:
        if case == "duplicate-terminal-during-close":
            child.frame(terminal)
        if case in ("late-permission-after-terminal", "primary-hold-late-permission"):
            # Screen one late ask without writing to the closed stdin in this synthetic path.
            child.frame(permission)

    child = InertChild(receive, during_close=during_close, close_fails=case in ("cleanup-failed", "primary-hold-late-permission"))
    def injected_launch(path: Path, managed: dict[str, str]) -> InertChild:
        assert path == workspace and managed["CODEX_HOME"] == str(home)
        assert all("TOKEN" not in key for key in managed)
        return child

    def fake_clock_wire(child: Child, attention: Callable[[], None], *,
                        cancelled: Callable[[], bool]) -> StdioWire:
        return StdioWire(child, attention, cancelled=cancelled,
                         clock=lambda: 901.0 if timed_out.is_set() else 0.0)

    monkeypatch.setattr(sdk_worker, "_launch_app_server", injected_launch)
    monkeypatch.setattr(sdk_worker, "StdioWire", fake_clock_wire)
    monkeypatch.setattr(sdk_worker, "os", SimpleNamespace(environ={}))

    def parent_handoff(_delay: float) -> None:
        run_stage("reverify", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
                  verify_call=_verify)
        (control / "reverify.result.json").replace(control / "review.authority.json")

    def stage() -> None:
        run_stage("review", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
                  sleep=parent_handoff, checkout_call=lambda *_: None)

    def forbidden(*_args: object) -> Never:
        raise AssertionError("No real verifier or publisher can run in a wire fixture.")

    if case in ("pre-ack", "post-ack", "interleaved", "prepared-sized-echo", "raw-context-limit-echo"):
        stage()
        completion = read_signal(control / "review.result.json")
        assert completion["thread_id"] == _THREAD and completion["turn_id"] == _TURN
        assert completion["head"] == packet.head and completion["output"] == "A substantive synthetic review."
        with pytest.raises(StageHold):
            run_stage("publisher", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
                      verify_call=forbidden, publish_call=forbidden)
    else:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(stage)
            assert dispatched.wait(3), "Review did not reach one synthetic dispatch."
            if case in ("permission-blocked", "interrupt", "timeout-post-ack"):
                # Ack first, then wait for the actual private stage to write its receipt.
                from time import monotonic, sleep

                deadline = monotonic() + 3
                while not (control / "review.started.json").exists() and monotonic() < deadline:
                    sleep(0.01)
                assert (control / "review.started.json").exists()
                if case == "permission-blocked":
                    assert not pending.done()
                    child.frame(permission)
                elif case == "timeout-post-ack":
                    timed_out.set()
                else:
                    write_signal(control / "review.interrupt.json", {"challenge": env[CHALLENGE]})
            with pytest.raises(sdk_worker.ReviewHold):
                pending.result(timeout=4)
        assert not (control / "review.result.json").exists()
        with pytest.raises((StageHold, FileNotFoundError)):
            run_stage("publisher", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
                      verify_call=forbidden, publish_call=forbidden)
        if code is not None:
            category = "collection" if code.startswith("collection") else "startup"
            receipt = read_signal(control / f"review.{category}.json")
            assert receipt["outcome"] == code
            assert receipt["head"] == packet.head and receipt["dispatch_id"] == packet.dispatch_id
            if category == "collection":
                assert receipt["thread_id"] == _THREAD and receipt["turn_id"] == _TURN
        if case in ("permission-before-ack", "permission-blocked"):
            assert len(denied) == 1
        if case == "primary-hold-late-permission":
            assert read_signal(control / "review.cleanup.json")["outcome"] == "cleanup_failed"
            assert read_signal(control / "review.attention.json")["reason"] == "permission-request"
        assert requests.count("turn/interrupt") <= 1
        claim = control.parent / "t01-55.claim"
        prior = claim.read_bytes()
        with pytest.raises(RuntimeError, match="already claimed"):
            run_stage("verifier", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
                      verify_call=_verify)
        assert claim.read_bytes() == prior
    assert child.closed.is_set() and requests.count("review/start") == 1
    assert "thread/read" not in requests and "turn/start" not in requests
    assert not (control / "publisher.result.json").exists()



def test_installed_sdk_pre_ack_comparison_keeps_turn_start_control() -> None:
    """The old public request path loses the same source-shaped terminal."""
    class OldInertClient(CodexClient):
        def _write_message(self, message: JsonObject) -> None:
            method = message["method"]
            assert method in ("review/start", "turn/start")
            # The private injection seam is confined to this non-running regression.
            for frame in (_item("enteredReviewMode"), _item("exitedReviewMode"), _terminal()):
                self._router.route_notification(self._coerce_notification(
                    cast(str, frame["method"]), frame["params"],
                ))
            turn: JsonObject = {"id": _TURN, "status": "inProgress", "items": []}
            result: JsonObject = {"turn": turn}
            if method == "review/start":
                result["reviewThreadId"] = _THREAD
            self._router.route_response({"id": message["id"], "result": result})

    old = OldInertClient()
    ack = old.request("review/start", {"threadId": _THREAD}, response_model=ReviewStartResponse)
    old.register_turn_notifications(ack.turn.id)
    old._router.fail_all(TransportClosedError("synthetic EOF"))
    with pytest.raises(TransportClosedError):
        old.next_turn_notification(ack.turn.id)
    old.unregister_turn_notifications(ack.turn.id)

    control = OldInertClient()
    ack_control = control.turn_start(_THREAD, "synthetic fixture")
    assert [control.next_turn_notification(ack_control.turn.id).method for _ in range(3)] == [
        "item/completed", "item/completed", "turn/completed",
    ]
    control.unregister_turn_notifications(ack_control.turn.id)
