"""Capture-only operator command surface; default execution is held."""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Never

from t02_capture_local_windows import _canonical
from t02_capture_packet import MAX_PACKET_BYTES, CapturePacket, _fixed_path
from t02_event_capture import CaptureBinding, CaptureStore
from t02_event_types import Hold, decode

Execute = Callable[[CapturePacket, int, int], str]
_STATES = {"prepared", "claimed", "sealed", "stopped", "cleanup-unknown"}
_DISPOSITIONS = {"new", "reserved", "captured", "held"}
_EXECUTE_OUTCOMES = {"denied", "admission-unknown", "held", "candidate-held", "cleanup-unknown"}


class SelectorError(ValueError):
    """A malformed selector must not echo a private caller string."""


class Parser(argparse.ArgumentParser):
    """Use a fixed program and sanitized errors even with a private argv."""

    def error(self, message: str) -> Never:
        raise SelectorError("Capture operator selectors held.")


def _parser() -> Parser:
    parser = Parser(
        prog="t02_capture_operator.py", allow_abbrev=False,
        description="Lighthouse capture-only operator preparation and private status.",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="show synthetic offline readiness")
    modes.add_argument("--prepare", action="store_true", help="create only a new exact unclaimed store")
    modes.add_argument("--status", action="store_true", help="read dispositions only; never disclose a candidate")
    modes.add_argument("--execute", action="store_true", help="request separately approved exact execution (held)")
    parser.add_argument("--packet", metavar="PRIVATE_PACKET", help="canonical local approved packet file")
    parser.add_argument("--owner-comment", metavar="ID", help="exact owner approval comment ID")
    parser.add_argument("--lead-comment", metavar="ID", help="exact Lead approval comment ID")
    return parser


def _comment(value: str | None) -> int:
    if value is None or not re.fullmatch(r"[1-9][0-9]{0,18}", value):
        raise SelectorError("Capture operator selectors held.")
    result = int(value)
    if result >= 2**63:
        raise SelectorError("Capture operator selectors held.")
    return result


def read_packet(path: Path) -> CapturePacket:
    """Read only the explicit local packet file under the packet byte limit."""
    if not path.is_absolute():
        raise Hold("Private capture packet path held.")
    _fixed_path(str(path))
    _canonical(path, directory=False)
    before = path.stat()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(MAX_PACKET_BYTES + 1)
        if not raw or len(raw) > MAX_PACKET_BYTES or len(raw) != before.st_size or opened != before:
            raise Hold("Private capture packet read held.")
        if os.fstat(stream.fileno()) != opened or path.stat() != opened:
            raise Hold("Private capture packet changed.")
    _canonical(path, directory=False)
    packet = CapturePacket.parse(raw)
    if raw != packet.canonical:
        raise Hold("Private capture packet is not canonical.")
    return packet


def capture_store(packet: CapturePacket) -> CaptureStore:
    """Bind the only admissible store to the exact packet state path."""
    fields = decode(packet.canonical, MAX_PACKET_BYTES)
    raw = fields["state"]
    if not isinstance(raw, str):
        raise Hold("Private capture store path held.")
    path = Path(raw)
    if not path.is_absolute():
        raise Hold("Private capture store path held.")
    _canonical(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        _canonical(path, directory=False)
    target = packet.approval
    return CaptureStore(
        path, CaptureBinding(target.head, packet.proof_id, packet.principal,
                             target.activation_ms, packet.intake_cutoff_ms),
        operation_digest=target.digest,
    )


def main(argv: Sequence[str] | None = None, *, execute: Execute | None = None) -> int:
    """Prepare/status are inert; fixed execute composition has no approved default."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    try:
        keys = [value.split("=", 1)[0] for value in arguments if value.startswith("--")]
        if len(keys) != len(set(keys)):
            raise SelectorError("Capture operator selectors held.")
        args = parser.parse_args(arguments)
        if not (args.prepare or args.status or args.execute):
            if args.packet is not None or args.owner_comment is not None or args.lead_comment is not None:
                raise SelectorError("Capture operator selectors held.")
            if args.dry_run:
                print("Synthetic offline preparation only; no packet, provider, listener or runtime was opened.")
            else:
                parser.print_help()
            return 0
        if not args.packet or not Path(args.packet).is_absolute():
            raise SelectorError("Capture operator selectors held.")
        if args.execute:
            owner, lead = _comment(args.owner_comment), _comment(args.lead_comment)
            if owner >= lead:
                raise SelectorError("Capture operator selectors held.")
            if execute is None:
                from t02_capture_composition import execute_capture, released

                if not released():
                    print("Held: capture-only execution is disabled.", file=sys.stderr)
                    return 2
                execute = execute_capture
            outcome = execute(read_packet(Path(args.packet)), owner, lead)
            if outcome not in _EXECUTE_OUTCOMES:
                raise Hold("Capture execution disposition held.")
            print(f"Capture execution: {outcome}.")
            return 0 if outcome == "candidate-held" else 1
        if args.owner_comment is not None or args.lead_comment is not None:
            raise SelectorError("Capture operator selectors held.")
        store = capture_store(read_packet(Path(args.packet)))
        if args.prepare:
            store.prepare()
            print("Capture store: prepared; no claim or capture was attempted.")
        else:
            before = store.path.stat()
            state, disposition = store.status()
            _canonical(store.path, directory=False)
            if store.path.stat() != before:
                raise Hold("Private capture store changed during status.")
            if state not in _STATES or disposition not in _DISPOSITIONS:
                raise Hold("Private capture store disposition held.")
            print(f"Capture store: {state}; candidate disposition: {disposition}.")
        return 0
    except SelectorError:
        print("Held: invalid or incomplete capture selectors.", file=sys.stderr)
        return 2
    except (Hold, OSError, RuntimeError, ValueError, KeyboardInterrupt):
        print("Held: private capture operation not confirmed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
