"""Provider-shaped capture approval fixtures; no live transport."""

import pytest
from t02_capture_evidence import PREFIX, SCOPE, CaptureApprovalTarget, CaptureEvidence
from t02_event_evidence import API_ROOT, MAX_PROVIDER_BYTES, ProviderReply
from t02_event_gate import LEAD, LEAD_APP, OWNER
from t02_event_types import encode

ACTIVATION = 1_700_000_001_000
TARGET = CaptureApprovalTarget("a" * 40, "c" * 64, ACTIVATION, ACTIVATION + 100)


class Provider:
    """Return bounded fixture records and optionally advance time inside a read."""

    def __init__(self) -> None:
        self.now = ACTIVATION
        self.calls = 0
        self.late = False
        self.expected_deadline = TARGET.cutoff_ms
        self.records: dict[str, dict[str, object]] = {
            "/issues/5": {"number": 5, "state": "open", "labels": []},
            "/pulls/15": {"number": 15, "state": "open", "draft": True, "merged": False,
                          "head": {"sha": TARGET.head}, "base": {"ref": "development"}},
        }
        for ref, actor, app, kind, time in (
            (1, OWNER, None, "User", "2023-11-14T22:13:19Z"),
            (2, LEAD, LEAD_APP, "Bot", "2023-11-14T22:13:20Z"),
        ):
            self.records[f"/issues/comments/{ref}"] = {
                "id": ref, "user": {"id": actor, "type": kind},
                "issue_url": "https://api.github.com" + API_ROOT + "/issues/5",
                "performed_via_github_app": None if app is None else {"id": app},
                "created_at": time, "updated_at": time, "body": PREFIX + encode({
                    "head": TARGET.head, "digest": TARGET.digest, "scope": SCOPE,
                    "not_before": ACTIVATION, "expires": TARGET.cutoff_ms,
                }).decode(),
            }

    def read(self, path: str, *, deadline_ms: int, limit: int) -> ProviderReply:
        assert limit == MAX_PROVIDER_BYTES and deadline_ms == self.expected_deadline
        self.calls += 1
        if self.late and self.calls == 4:
            self.now = deadline_ms
        return ProviderReply(200, encode(self.records[path.removeprefix(API_ROOT)]))


def test_capture_approval_positive_and_invalid_selectors() -> None:
    fixture = Provider()
    evidence = CaptureEvidence(fixture, lambda: fixture.now)
    assert not evidence.allows(TARGET, 2, 1) and fixture.calls == 0
    assert evidence.allows(TARGET, 1, 2) and fixture.calls == 4


@pytest.mark.parametrize(("path", "change"), [
    ("/issues/5", {"labels": [{"name": "lighthouse:blocked"}]}),
    ("/pulls/15", {"draft": False}),
    ("/pulls/15", {"head": {"sha": "b" * 40}}),
    ("/pulls/15", {"body": "é" * MAX_PROVIDER_BYTES}),
    ("/issues/comments/1", {"performed_via_github_app": {"id": LEAD_APP}}),
    ("/issues/comments/2", {"performed_via_github_app": None}),
    ("/issues/comments/2", {"issue_url": "https://api.github.com" + API_ROOT + "/issues/6"}),
    ("/issues/comments/2", {"updated_at": "2023-11-14T22:13:21Z"}),
    ("/issues/comments/2", {"body": 'Lighthouse-T02 approval: {"scope":"event"}'}),
    ("/issues/comments/2", {"created_at": "2023-11-14T22:13:18Z", "updated_at": "2023-11-14T22:13:18Z"}),
])
def test_nonmatching_or_oversize_records_hold(path: str, change: dict[str, object]) -> None:
    fixture = Provider()
    fixture.records[path].update(change)
    assert not CaptureEvidence(fixture, lambda: fixture.now).allows(TARGET, 1, 2)


def test_evidence_completing_at_cutoff_is_denied() -> None:
    fixture = Provider()
    fixture.late = True
    assert not CaptureEvidence(fixture, lambda: fixture.now).allows(TARGET, 1, 2)
    assert fixture.calls == 4
