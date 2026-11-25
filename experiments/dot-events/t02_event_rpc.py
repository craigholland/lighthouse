"""Pinned Streamable HTTP lifecycle with a single discovery-only event."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock

from t02_event_source import EventSource
from t02_event_types import EVENT, MARKER, VERSION, Hold, decode, encode

SOURCE_PATH = "/mcp"
PROBE_HOST = "127.0.0.1:8765"


@dataclass(frozen=True)
class RpcResponse:
    status: int
    body: bytes = b""


class ProbeRpc:
    """No tools are available; the external auth adapter owns caller identity."""

    def __init__(self, source: EventSource) -> None:
        self._source = source
        self._initialized = False
        self._ready = False
        self._lock = Lock()

    def serve(
        self, method: str, path: str, headers: Mapping[str, str],
        body: bytes, authenticated_principal: str | None,
    ) -> RpcResponse:
        """Consume bounded requests from a verified loopback HTTP adapter."""
        h = {key.lower(): value for key, value in headers.items()}
        if len(h) != len(headers) or h.get("host") != PROBE_HOST:
            return RpcResponse(403)
        if h.get("origin") not in (None, "http://" + PROBE_HOST):
            return RpcResponse(403)
        try:
            self._source.check_principal(authenticated_principal, allow_stopped=True)
        except Hold:
            return RpcResponse(403)
        if path != SOURCE_PATH:
            return RpcResponse(404)
        if method != "POST":   # No server-initiated SSE or MCP sessions.
            return RpcResponse(405)
        if h.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            return RpcResponse(415)
        accepted = {token.strip().split(";")[0] for token in h.get("accept", "").split(",")}
        if not {"application/json", "text/event-stream"} <= accepted:
            return RpcResponse(406)
        try:
            request = decode(body)
        except Hold:
            return self._error(None, -32700)
        request_id = request.get("id")
        rpc_method = request.get("method")
        if (
            not request.keys() <= {"jsonrpc", "method", "params", "id"}
            or request.get("jsonrpc") != "2.0" or not isinstance(rpc_method, str)
            or ("id" in request and type(request_id) not in (int, str))
        ):
            return self._error(None, -32600)
        params = request.get("params", {})
        if not isinstance(params, dict):
            return self._error(request_id, -32602)
        if rpc_method != "initialize" and h.get("mcp-protocol-version") != VERSION:
            return RpcResponse(400)
        if rpc_method == "initialize" and h.get("mcp-protocol-version") not in (None, VERSION):
            return RpcResponse(400)
        with self._lock:
            return self._rpc(rpc_method, request_id, params, authenticated_principal)

    def _rpc(
        self, method: str, rid: object, params: dict[str, object], principal: str | None,
    ) -> RpcResponse:
        if method == "initialize":
            if (
                rid is None or params.get("protocolVersion") != VERSION
                or not isinstance(params.get("clientInfo"), dict)
                or not isinstance(params.get("capabilities"), dict)
            ):
                return self._error(rid, -32602)
            self._initialized = True
            self._ready = False
            return self._success(rid, {
                "protocolVersion": VERSION, "capabilities": {"events": {}},
                "serverInfo": {"name": "lighthouse-t02-event-probe", "version": "1"},
            })
        if method == "notifications/initialized":
            if not self._initialized or rid is not None or params:
                return self._error(rid, -32600)
            self._ready = True
            return RpcResponse(202)
        if rid is None:
            return RpcResponse(400)
        if not self._ready:
            return self._error(rid, -32600)
        if method in ("events/list", "events/subscribe"):
            try:
                self._source.check_principal(principal)
            except Hold:
                return RpcResponse(403)
        if method == "events/list" and not params:
            proof = {"type": "string", "const": self._source.binding.proof_id}
            return self._success(rid, {"events": [{
                "name": EVENT, "description": "Single inert eligibility probe",
                "delivery": ["webhook"],
                "inputSchema": {"type": "object", "properties": {"proof_id": proof},
                                "required": ["proof_id"], "additionalProperties": False},
                "payloadSchema": {"type": "object", "properties": {
                    "proof_id": proof, "marker": {"type": "string", "const": MARKER}},
                    "required": ["proof_id", "marker"], "additionalProperties": False},
            }]})
        if method == "ping" and not params:
            return self._success(rid, {})
        try:
            if method == "events/subscribe":
                return self._success(rid, self._source.subscribe(principal, params))
            if method == "events/unsubscribe":
                self._source.unsubscribe(principal, params)
                return self._success(rid, {})
        except Hold:
            return self._error(rid, -32015)
        return self._error(rid, -32602 if method in ("events/list", "ping") else -32601)

    @staticmethod
    def _success(rid: object, result: object) -> RpcResponse:
        return RpcResponse(200, encode({"jsonrpc": "2.0", "id": rid, "result": result}))

    @staticmethod
    def _error(rid: object, code: int) -> RpcResponse:
        messages = {-32700: "Parse error", -32600: "Invalid request",
                    -32601: "Method not found", -32602: "Invalid params", -32015: "Probe held"}
        return RpcResponse(200, encode({"jsonrpc": "2.0", "id": rid,
                                       "error": {"code": code, "message": messages[code]}}))
