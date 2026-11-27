"""Offline tests of the pinned App Server wire; no processes or provider access."""

import json
from collections import deque
from pathlib import Path

import pytest

from lighthouse.adapters.codex.stdio import ReviewRequest, Shutdown, StdioReviewWorker

THREAD = "thread-proof"
TURN = "turn-proof"
HEAD = "a" * 40


def encode(value: dict[str, object]) -> bytes:
    return (json.dumps(value) + "\n").encode()


def notify(kind: str, item: dict[str, object], *, thread: str = THREAD) -> bytes:
    return encode({"method": kind, "params": {"threadId": thread, "turnId": TURN, **item}})


ENTER = notify("item/completed", {"item": {"type": "enteredReviewMode", "review": "untrusted echo"}})
EXIT = notify("item/completed", {"item": {"type": "exitedReviewMode", "review": "Looks good in src/f.py."}})
DONE = notify("turn/completed", {"turn": {"id": TURN, "status": "completed", "error": None}})
ACK = encode({"id": 4, "result": {"reviewThreadId": THREAD, "turn": {"id": TURN, "status": "inProgress"}}})


def exact_request(tmp_path: Path) -> ReviewRequest:
    return ReviewRequest("owner/repo", 3, 4, HEAD, tmp_path, "fixture-model.1",
                         "  Inert untrusted fixture evidence.  ", "Fixture read-only instructions.", "artifact:verify-test")


class FakeSession:
    def __init__(
        self, target: ReviewRequest, *, review_frames: tuple[bytes, ...] = (ENTER, EXIT, DONE, ACK),
        cleanup: Shutdown = Shutdown(True, True), policy: object = False, user_agent: str = "codex/0.171.0",
    ) -> None:
        self.target = target
        self.review_frames = review_frames
        self.cleanup = cleanup
        self.policy = policy
        self.user_agent = user_agent
        self.queue: deque[bytes] = deque()
        self.sent: list[dict[str, object]] = []
        self.trace: list[str] = []

    def write(self, data: bytes, deadline: float) -> None:
        assert deadline == 20.0 and data.endswith(b"\n")
        message = json.loads(data)
        self.sent.append(message)
        method = message.get("method")
        if method == "initialize":
            response: dict[str, object] = {"userAgent": self.user_agent}
        elif method == "account/read":
            response = {"account": {"type": "chatgpt"}}
        elif method == "thread/start":
            response = {
                "sandbox": {"type": "readOnly", "networkAccess": self.policy}, "approvalPolicy": "never",
                "approvalsReviewer": "user", "model": self.target.model, "modelProvider": "openai",
                "cwd": str(self.target.workspace),
                "thread": {"cwd": str(self.target.workspace), "ephemeral": False, "turns": [], "id": THREAD},
            }
        elif method == "review/start":
            self.queue.extend(self.review_frames)
            return
        else:
            assert method in (None, "initialized")
            return
        self.queue.append(encode({"id": message["id"], "result": response}))

    def read(self, max_bytes: int, deadline: float) -> bytes | None:
        assert max_bytes == 1_048_576 and deadline == 20.0
        return self.queue.popleft() if self.queue else None

    def shutdown(self, deadline: float) -> Shutdown:
        assert deadline in (20.0, 22.0)
        self.trace.append("shutdown")
        return Shutdown(self.cleanup.root_exited, self.cleanup.contained_empty, (*self.queue, *self.cleanup.frames))


def test_pre_ack_lifecycle_is_kept_and_identity_written_before_cleanup(tmp_path: Path) -> None:
    target = exact_request(tmp_path)
    session = FakeSession(target)
    verified: list[int] = []

    def checkout(req: ReviewRequest, end: float) -> bool:
        assert req is target and end == 20.0
        verified.append(len(session.sent))
        return True

    def identity(thread: str, turn: str) -> None:
        assert (thread, turn) == (THREAD, TURN)
        session.trace.append("identity")

    result = StdioReviewWorker(lambda *_: session, checkout, lambda: 0.0).run(
        target, 20.0, on_identity=identity, cleanup_deadline=22.0,
    )
    assert (result.thread_id, result.turn_id, result.comment) == (THREAD, TURN, "Looks good in src/f.py.")
    assert result.owned_cleanup and result.hold_reason is None and not result.acceptance_unknown
    assert verified == [0, 4]
    assert session.trace == ["identity", "shutdown"]
    assert [frame["method"] for frame in session.sent] == [
        "initialize", "initialized", "account/read", "thread/start", "review/start",
    ]
    assert session.sent[1] == {"method": "initialized"}
    assert session.sent[2]["params"] == {"refreshToken": False}
    params = session.sent[3]["params"]
    assert isinstance(params, dict)
    assert {key: params[key] for key in ("ephemeral", "sandbox", "approvalPolicy", "approvalsReviewer")} == {
        "ephemeral": False, "sandbox": "read-only", "approvalPolicy": "never", "approvalsReviewer": "user",
    }
    review = session.sent[4]["params"]
    assert isinstance(review, dict) and review["delivery"] == "inline"
    assert review["threadId"] == THREAD and review["target"]["type"] == "custom"
    evidence = json.loads(review["target"]["instructions"].split("\n", 1)[1])
    assert evidence == {"repository": target.repository, "issue": 3, "pullRequest": 4,
                        "verification": target.verification, "context": target.context}
    assert target.context not in repr(target)
    assert result.comment is not None and result.comment not in repr(result)


@pytest.mark.parametrize(("frames", "reason", "accepted"), [
    ((ENTER, EXIT, DONE), "transport-lost", False),
    ((ACK, ENTER, EXIT), "transport-lost", True),
    ((ACK, EXIT, DONE), "event-order-invalid", True),
    ((ACK, ENTER, EXIT, notify("turn/completed", {"turn": {"id": TURN, "status": "completed"}},
                               thread="different")), "identity-mismatch", True),
    ((ACK, ENTER, EXIT, notify("turn/completed", {"turn": {"id": TURN, "status": "completed",
                                                          "error": {"message": "private text"}}})),
     "terminal-failed", True),
])
def test_unknown_or_wrong_output_never_replays(tmp_path: Path, frames: tuple[bytes, ...],
                                               reason: str, accepted: bool) -> None:
    target = exact_request(tmp_path)
    session = FakeSession(target, review_frames=frames)
    ids: list[tuple[str, str]] = []
    result = StdioReviewWorker(lambda *_: session, lambda *_: True, lambda: 0.0).run(
        target, 20.0, on_identity=lambda a, b: ids.append((a, b)),
    )
    assert result.comment is None and result.hold_reason == reason and result.owned_cleanup
    assert result.acceptance_unknown is not accepted
    assert ids == ([(THREAD, TURN)] if accepted else [])
    assert [item.get("method") for item in session.sent].count("review/start") == 1


@pytest.mark.parametrize(("shutdown", "reason", "owned"), [
    (Shutdown(True, True, (DONE,)), "terminal-conflict", True),
    (Shutdown(False, True), "cleanup-unconfirmed", False),
    (Shutdown(True, False), "cleanup-unconfirmed", False),
    (Shutdown(True, True, (b'{"method":"error","params":{}}\n',)), "server-error", True),
])
def test_confirmed_local_cleanup_and_unread_final_signal_both_required(
    tmp_path: Path, shutdown: Shutdown, reason: str, owned: bool,
) -> None:
    target = exact_request(tmp_path)
    session = FakeSession(target, cleanup=shutdown)
    result = StdioReviewWorker(lambda *_: session, lambda *_: True, lambda: 0.0).run(target, 20.0)
    assert result.comment is None and result.hold_reason == reason and result.owned_cleanup is owned
    assert (result.thread_id, result.turn_id) == (THREAD, TURN)


def test_server_permission_is_denied_and_never_dispatches_again(tmp_path: Path) -> None:
    target = exact_request(tmp_path)
    attention = encode({"id": "p1", "method": "item/permissions/requestApproval", "params": {}})
    session = FakeSession(target, review_frames=(attention, ACK, ENTER, EXIT, DONE))
    result = StdioReviewWorker(lambda *_: session, lambda *_: True, lambda: 0.0).run(target, 20.0)
    assert result.hold_reason == "permission-attention" and result.acceptance_unknown and result.comment is None
    assert session.sent[-1] == {"id": "p1", "result": {"permissions": {}, "scope": "turn"}}


@pytest.mark.parametrize(("agent", "network", "reason"), [
    ("codex/0.171.0-rc1", False, "runtime-unverified"),
    ("codex/0.171.0", True, "policy-unverified"),
    ("codex/0.171.0", None, "policy-unverified"),
])
def test_unverified_runtime_or_effective_policy_holds_before_review(
    tmp_path: Path, agent: str, network: object, reason: str,
) -> None:
    target = exact_request(tmp_path)
    session = FakeSession(target, user_agent=agent, policy=network)
    result = StdioReviewWorker(lambda *_: session, lambda *_: True, lambda: 0.0).run(target, 20.0)
    assert result.hold_reason == reason and not result.acceptance_unknown and result.owned_cleanup
    assert not any(item.get("method") == "review/start" for item in session.sent)



@pytest.mark.parametrize("output", [
    "Reviewer failed to output a response.",
    "Look at C:\\outside\\private.txt.",
    "Look at file%3A%2F%2F%2Fprivate%2Ffixture.txt.",
    "Look at ../../private.txt.",
])
def test_unattributable_or_private_output_cannot_become_comment(tmp_path: Path, output: str) -> None:
    target = exact_request(tmp_path)
    exit_frame = notify("item/completed", {"item": {"type": "exitedReviewMode", "review": output}})
    session = FakeSession(target, review_frames=(ACK, ENTER, exit_frame, DONE))
    result = StdioReviewWorker(lambda *_: session, lambda *_: True, lambda: 0.0).run(target, 20.0)
    assert result.hold_reason == "output-invalid" and result.comment is None and result.owned_cleanup


def test_approved_absolute_checkout_reference_is_normalized(tmp_path: Path) -> None:
    target = exact_request(tmp_path)
    output = f"Point to \x60{tmp_path / 'src' / 'file.py'}\x60."
    exit_frame = notify("item/completed", {"item": {"type": "exitedReviewMode", "review": output}})
    session = FakeSession(target, review_frames=(ACK, ENTER, exit_frame, DONE))
    result = StdioReviewWorker(lambda *_: session, lambda *_: True, lambda: 0.0).run(target, 20.0)
    assert result.comment == "Point to \x60src/file.py\x60."



def test_pre_ack_events_have_independent_retention_budget(tmp_path: Path) -> None:
    target = exact_request(tmp_path)
    session = FakeSession(target, review_frames=(*[ENTER] * 17, ACK))
    result = StdioReviewWorker(lambda *_: session, lambda *_: True, lambda: 0.0).run(target, 20.0)
    assert result.hold_reason == "event-budget" and result.acceptance_unknown
    assert result.comment is result.turn_id is None and result.owned_cleanup


def test_lost_start_is_not_proof_that_nothing_ran(tmp_path: Path) -> None:
    target = exact_request(tmp_path)

    def unknown_open(*_: object) -> FakeSession:
        raise OSError("private fixture detail")

    result = StdioReviewWorker(unknown_open, lambda *_: True, lambda: 0.0).run(target, 20.0)
    assert result.hold_reason == "transport-lost" and result.acceptance_unknown and not result.owned_cleanup
    assert result.session_started and "private fixture detail" not in repr(result)
