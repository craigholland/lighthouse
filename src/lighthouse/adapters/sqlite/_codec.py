"""Explicit v1 JSON shapes for T04 state and inert ledger evidence."""

import json
from dataclasses import asdict
from typing import Any

from lighthouse.application.ledger import Change, Intent, IntentStatus
from lighthouse.domain.workflow import Binding, Decision, Outcome, State, Work


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def encode_state(state: State) -> dict[str, object]:
    return {
        "repository": state.repository, "version": state.version,
        "work": asdict(state.work) if state.work else None, "outcome": state.outcome.value,
        "action_keys": sorted((o.value, h, n, e) for o, h, n, e in state.action_keys),
    }


def state_from(data: dict[str, Any]) -> State:
    raw = data["work"]
    work = None
    if raw is not None:
        b = raw["binding"]
        work = Work(_number(raw["issue"]), _text(raw["order"]),
                    Binding(_text(b["scope"]), _text(b["profile"]), _text(b["verification"])),
                    None if raw["pr"] is None else _number(raw["pr"]))
    keys = frozenset(
        (Outcome(o), _text(h), _number(n), _text(e)) for o, h, n, e in data["action_keys"]
    )
    if keys and work is None:
        raise ValueError
    state = State(_text(data["repository"]), _number(data["version"], minimum=0),
                  work, Outcome(data["outcome"]), keys)
    if _canonical(data) != _canonical(encode_state(state)):
        raise ValueError
    return state


def encode_intent(intent: Intent) -> dict[str, object]:
    return {**asdict(intent), "status": intent.status.value}


def intent_from(data: dict[str, Any]) -> Intent:
    pr = data["pr"]
    head = data["head"]
    if (pr is None) != (head is None):
        raise ValueError
    intent = Intent(
        _text(data["dispatch_id"]), _text(data["order"]), _text(data["operation"]),
        None if pr is None else _number(pr), None if head is None else _text(head),
        IntentStatus(data["status"]),
    )
    if _canonical(data) != _canonical(encode_intent(intent)):
        raise ValueError
    return intent


def encode_change(change: Change) -> dict[str, object]:
    d = change.decision
    return {
        "observation": change.observation, "expected": change.expected,
        "state": encode_state(d.state), "outcome": d.outcome.value, "reason": d.reason,
        "actor": d.actor, "evidence": list(d.evidence),
        "intent": encode_intent(change.intent) if change.intent else None,
    }


def change_from(data: dict[str, Any]) -> Change:
    intent = data["intent"]
    actor = data["actor"]
    result = Change(
        _number(data["expected"], minimum=-1), _text(data["observation"]),
        Decision(state_from(data["state"]), Outcome(data["outcome"]), _text(data["reason"]),
                 None if actor is None else _number(actor),
                 tuple(_text(e) for e in data["evidence"])),
        None if intent is None else intent_from(intent),
    )
    if _canonical(data) != _canonical(encode_change(result)):
        raise ValueError
    return result


def _number(value: object, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError
    return value
