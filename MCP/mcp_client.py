"""MCP-protocol client — JSON-RPC 2.0 over the streamable-HTTP transport.

The generic executor in ``routes.py`` forwards plain HTTP GET/POST, which
cannot talk to a real MCP server (e.g. https://api.agentic-news.ai/mcp).
MCP servers expect an ``initialize`` handshake, ``Mcp-Session-Id``
propagation, an ``Accept: application/json, text/event-stream`` header, and
JSON-RPC messages such as ``tools/list`` / ``tools/call`` — with responses
that may arrive as server-sent events. This module implements just enough
of the protocol (version 2025-03-26) to list and call tools, using only
``requests``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

import requests as _req

PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "homee-mcp-client", "version": "1.0"}

_ACCEPT = "application/json, text/event-stream"
_TIMEOUT = 30


class MCPError(Exception):
    """Transport- or protocol-level failure talking to an MCP server.

    ``status_code`` is set when the server answered with an HTTP error or a
    JSON-RPC error (callers surface it like the generic executor does);
    ``None`` means the server could not be reached at all.
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _parse_sse(body: str) -> List[Dict[str, Any]]:
    """Extract JSON-RPC messages from a ``text/event-stream`` body."""
    messages: List[Dict[str, Any]] = []
    for block in re.split(r"\r?\n\r?\n", body):
        data = [line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")]
        if not data:
            continue
        try:
            msg = json.loads("\n".join(data))
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict):
            messages.append(msg)
    return messages


def _pick_response(messages: List[Dict[str, Any]], req_id: Any) -> Optional[Dict[str, Any]]:
    """Choose the JSON-RPC response to ``req_id`` out of a parsed stream."""
    for msg in messages:
        if msg.get("id") == req_id and ("result" in msg or "error" in msg):
            return msg
    for msg in reversed(messages):  # fall back to the last response-shaped message
        if "result" in msg or "error" in msg:
            return msg
    return None


def _post(endpoint: str, headers: Dict[str, str], payload: Dict[str, Any],
          timeout: int, session_id: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str], int]:
    """POST one JSON-RPC message; returns ``(message, session_id, status)``.

    ``message`` is ``None`` for accepted notifications (202/204 or empty body).
    """
    hdrs = {"Content-Type": "application/json", "Accept": _ACCEPT, **(headers or {})}
    if session_id:
        hdrs["Mcp-Session-Id"] = session_id
    try:
        resp = _req.post(endpoint, headers=hdrs, json=payload, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        raise MCPError(f"MCP server unreachable: {e}") from e

    session_id = resp.headers.get("Mcp-Session-Id", session_id)
    if resp.status_code >= 400:
        detail = ""
        try:
            body = resp.json()
            detail = body.get("message") or body.get("error") or ""
        except ValueError:
            detail = resp.text.strip()[:200]
        hint = ""
        if resp.status_code in (401, 403):
            hint = " (authentication required — set the server's API key/token in its headers)"
        suffix = f": {detail}" if detail else ""
        raise MCPError(f"MCP endpoint returned status {resp.status_code}{hint}{suffix}",
                       status_code=resp.status_code)
    if resp.status_code in (201, 202, 204) or not resp.content:
        return None, session_id, resp.status_code

    ctype = resp.headers.get("Content-Type", "")
    if "text/event-stream" in ctype:
        msg = _pick_response(_parse_sse(resp.text), payload.get("id"))
        return msg, session_id, resp.status_code
    try:
        parsed = resp.json()
    except ValueError as e:
        raise MCPError(f"MCP server returned a non-JSON response ({ctype or 'unknown content-type'})",
                       status_code=resp.status_code) from e
    if isinstance(parsed, list):  # batched JSON-RPC
        return _pick_response([m for m in parsed if isinstance(m, dict)], payload.get("id")), session_id, resp.status_code
    return parsed, session_id, resp.status_code


def _raise_if_error(msg: Dict[str, Any], status: int, context: str) -> Any:
    if "error" in msg:
        err = msg["error"] if isinstance(msg["error"], dict) else {}
        raise MCPError(f"MCP {context} failed: {err.get('code', '?')}: {err.get('message', msg['error'])}",
                       status_code=status)
    return msg.get("result")


class MCPSession:
    """One short-lived MCP session: initialize → notify → requests."""

    def __init__(self, endpoint: str, headers: Optional[Dict[str, str]] = None, timeout: int = _TIMEOUT):
        self.endpoint = endpoint
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self._next_id = 0
        self._initialized = False

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Any, int]:
        self._next_id += 1
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        msg, self.session_id, status = _post(self.endpoint, self.headers, payload,
                                             self.timeout, self.session_id)
        if msg is None:
            raise MCPError(f"MCP server sent no response to {method}", status_code=status)
        return _raise_if_error(msg, status, method), status

    def _notify(self, method: str) -> None:
        payload = {"jsonrpc": "2.0", "method": method}
        _, self.session_id, _ = _post(self.endpoint, self.headers, payload,
                                      self.timeout, self.session_id)

    def initialize(self) -> None:
        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self._notify("notifications/initialized")
        self._initialized = True

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    def list_tools(self) -> Tuple[List[Dict[str, Any]], int]:
        self._ensure_initialized()
        result, status = self._request("tools/list")
        return (result or {}).get("tools", []), status

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        self._ensure_initialized()
        result, status = self._request("tools/call", {"name": name, "arguments": arguments})
        return result or {}, status

    def send_raw(self, payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], int]:
        """Forward a hand-crafted JSON-RPC payload inside a real session."""
        self._ensure_initialized()
        msg, self.session_id, status = _post(self.endpoint, self.headers, payload,
                                             self.timeout, self.session_id)
        return msg, status


def _normalize_content(result: Dict[str, Any]) -> Tuple[str, Optional[list]]:
    """Split MCP tool-result content into ``(joined_text, non_text_items)``."""
    content = result.get("content")
    if content is None:
        return "", None
    if not isinstance(content, list):
        return str(content), None
    texts = [item.get("text", "") for item in content
             if isinstance(item, dict) and item.get("type") == "text"]
    other = [item for item in content
             if not (isinstance(item, dict) and item.get("type") == "text")]
    return "\n".join(t for t in texts if t), (other or None)


def execute_mcp(mcp: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    """Run one agent-callable execution against an MCP-protocol server.

    ``args`` shapes the call:
    - ``{"jsonrpc": ..., "method": ...}`` — raw JSON-RPC passthrough (inside
      an initialized session, with protocol headers).
    - ``{"tool": "<name>", "arguments": {...}}`` — ``tools/call``. Any extra
      top-level keys are merged into the arguments as a convenience.
    - anything else — ``tools/list`` so the caller can discover tool names.
    """
    args = args if isinstance(args, dict) else {}
    session = MCPSession(mcp.get("endpoint", ""), headers=mcp.get("headers", {}))

    if "jsonrpc" in args and "method" in args:
        msg, status = session.send_raw(args)
        if msg is None:
            return {"result": "Notification accepted", "status_code": status}
        return {"result": _raise_if_error(msg, status, str(args.get("method"))),
                "status_code": status}

    tool = args.get("tool") or args.get("tool_name")
    if not tool:
        tools, status = session.list_tools()
        return {
            "result": {
                "tools": [
                    {
                        "name": t.get("name"),
                        "description": t.get("description", ""),
                        "input_schema": t.get("inputSchema", {}),
                    }
                    for t in tools
                ],
                "hint": "Call again with 'tool' set to one of these names and "
                        "'arguments' as an object matching its input_schema.",
            },
            "status_code": status,
        }

    arguments = args.get("arguments")
    if arguments is None:
        arguments = {k: v for k, v in args.items() if k not in ("tool", "tool_name")}
    if not isinstance(arguments, dict):
        arguments = {}
    result, status = session.call_tool(str(tool), arguments)

    text, other = _normalize_content(result)
    if result.get("isError"):
        out: Dict[str, Any] = {"error": text or "Tool reported an error",
                               "is_error": True, "status_code": status, "tool": str(tool)}
        if other:
            out["content"] = other
        return out
    value: Any = text or result.get("structuredContent") or other or result
    out = {"result": value, "status_code": status, "tool": str(tool)}
    if text and other:
        out["content"] = other
    return out
