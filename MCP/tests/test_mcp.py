"""Tests for the MCP service (independent Flask app, port 5002)."""

from __future__ import annotations

from MCP.app import create_mcp_app


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["service"] == "mcp"
    assert data["port"] == 5002


def test_marketplace(client):
    resp = client.get("/api/mcp/marketplace")
    assert resp.status_code == 200
    # Built-in entries were retired (dead endpoints); the marketplace is
    # served from the synced registry snapshot on the UI side.
    assert resp.get_json()["mcps"] == []


def test_mcp_crud(client):
    resp = client.post(
        "/api/mcps",
        json={"name": "Test MCP", "endpoint": "http://example.com", "method": "GET"},
    )
    assert resp.status_code == 200
    mcp_id = resp.get_json()["mcp"]["id"]

    resp = client.get("/api/mcps")
    assert resp.status_code == 200
    assert any(m["id"] == mcp_id for m in resp.get_json()["mcps"])

    resp = client.get(f"/api/mcp/{mcp_id}")
    assert resp.status_code == 200
    assert resp.get_json()["mcp"]["name"] == "Test MCP"

    resp = client.put(f"/api/mcp/{mcp_id}", json={"name": "Renamed"})
    assert resp.status_code == 200
    assert resp.get_json()["mcp"]["name"] == "Renamed"

    resp = client.delete(f"/api/mcp/{mcp_id}")
    assert resp.status_code == 200

    resp = client.get(f"/api/mcp/{mcp_id}")
    assert resp.status_code == 404


def test_execute_system_disk(client):
    resp = client.post("/api/mcp/execute/system_disk", json={})
    assert resp.status_code == 200
    result = resp.get_json()["result"]
    # The /execute/system_disk shortcut returns get_disk_space() as a string.
    assert "GB free" in result


def test_execute_system_date(client):
    resp = client.post("/api/mcp/execute/system_date", json={})
    assert resp.status_code == 200
    result = resp.get_json()["result"]
    # The shortcut returns get_current_date() as a human-readable string.
    assert "UTC" in result
    # Sanity: it parses as a UTC timestamp.
    from datetime import datetime
    datetime.strptime(result, "%Y-%m-%d %H:%M:%S UTC")


def test_execute_unknown_mcp(client):
    resp = client.post("/api/mcp/execute/does_not_exist", json={})
    assert resp.status_code == 404


def test_registry_reads_through_from_disk(client):
    """A write must be visible to a fresh reader (simulates another gunicorn
    worker whose in-memory registry was stale)."""
    import json
    import MCP.routes as routes_mod
    from MCP.config import MCPS_DIR

    _register_mcp(client, "alpha", "https://a.example", "GET")

    # Simulate a second worker: wipe in-memory state, write a different entry
    # directly to disk, then confirm a read reflects the file (not memory).
    routes_mod._mcps.clear()
    routes_mod._mcps["stale"] = {"id": "stale", "name": "Stale"}
    (MCPS_DIR / "mcps.json").write_text(
        json.dumps([{"id": "beta", "name": "Beta", "endpoint": "https://b.example",
                     "method": "POST", "auth_type": "none", "headers": {}}]),
        encoding="utf-8",
    )

    resp = client.get("/api/mcps")
    ids = {m["id"] for m in resp.get_json()["mcps"]}
    assert ids == {"beta"}, f"read did not come from disk: {ids}"


def test_reload_endpoint(client):
    """POST /api/mcp/reload reloads from disk and reports what was loaded."""
    import json
    import MCP.routes as routes_mod
    from MCP.config import MCPS_DIR

    (MCPS_DIR / "mcps.json").write_text(
        json.dumps([
            {"id": "r1", "name": "R1", "endpoint": "https://r1.example", "method": "GET"},
            {"id": "r2", "name": "R2", "endpoint": "https://r2.example", "method": "POST"},
        ]),
        encoding="utf-8",
    )
    routes_mod._mcps.clear()

    resp = client.post("/api/mcp/reload")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["count"] == 2
    assert data["ids"] == ["r1", "r2"]
    # In-memory cache refreshed too
    assert set(routes_mod._mcps.keys()) == {"r1", "r2"}


def _register_mcp(client, mcp_id, endpoint, method="GET"):
    resp = client.post(
        "/api/mcps",
        json={"id": mcp_id, "name": mcp_id, "endpoint": endpoint, "method": method},
    )
    assert resp.status_code == 200


def test_execute_get_forwards_args_as_query_params(client, monkeypatch):
    """GET MCPs (e.g. open-meteo) must receive args as query params."""
    import MCP.routes as routes_mod

    captured = {}

    class _Resp:
        status_code = 200
        text = '{"ok": true}'

    def _fake_request(method=None, url=None, headers=None, params=None, json=None, timeout=None):
        captured.update({"method": method, "url": url, "params": params, "json": json})
        return _Resp()

    monkeypatch.setattr(routes_mod._req, "request", _fake_request)
    _register_mcp(client, "weather", "https://api.open-meteo.com/v1/forecast", "GET")

    resp = client.post(
        "/api/mcp/execute/weather",
        json={"latitude": 32.7, "longitude": -117.2, "current_weather": True},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status_code"] == 200
    assert captured["method"] == "GET"
    assert captured["params"] == {"latitude": 32.7, "longitude": -117.2, "current_weather": True}
    assert captured["json"] is None


def test_execute_post_forwards_args_as_json_body(client, monkeypatch):
    """Non-GET MCPs (e.g. JSON-RPC servers) must receive args as a JSON body."""
    import MCP.routes as routes_mod

    captured = {}

    class _Resp:
        status_code = 200
        text = '{"result": "ok"}'

    def _fake_request(method=None, url=None, headers=None, params=None, json=None, timeout=None):
        captured.update({"method": method, "params": params, "json": json})
        return _Resp()

    monkeypatch.setattr(routes_mod._req, "request", _fake_request)
    _register_mcp(client, "groundrules", "https://law.agentlookups.ai/mcp", "POST")

    body = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
    resp = client.post("/api/mcp/execute/groundrules", json=body)
    assert resp.status_code == 200
    assert captured["method"] == "POST"
    assert captured["json"] == body
    assert captured["params"] is None


def test_execute_upstream_error_returns_clean_error(client, monkeypatch):
    """Upstream 4xx/5xx must surface as an error, not as a 'result' page."""
    import MCP.routes as routes_mod

    class _Resp:
        status_code = 404
        text = "<html>not found</html>"

    monkeypatch.setattr(routes_mod._req, "request", lambda *a, **k: _Resp())
    _register_mcp(client, "dead", "https://example.com/gone", "GET")

    resp = client.post("/api/mcp/execute/dead", json={})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status_code"] == 404
    assert "404" in data["error"]
    assert "result" not in data

# ══════════════════════════════════════════════════════════════════
# MCP-protocol servers (JSON-RPC 2.0 over streamable HTTP)
# ══════════════════════════════════════════════════════════════════

import json as _json
import threading as _threading

import pytest as _pytest


@_pytest.fixture
def fake_mcp_server():
    """In-process MCP-protocol server speaking streamable HTTP.

    Responds to initialize/tools-list/tools-call, issues a session id, and
    answers tools/call with an SSE body to exercise the event-stream parser.
    """
    from flask import Flask, Response, jsonify, request
    from werkzeug.serving import make_server

    app = Flask("fake-mcp-protocol")
    app.hits = []  # type: ignore[attr-defined]

    @app.post("/mcp")
    def mcp():
        payload = request.get_json(force=True)
        app.hits.append({  # type: ignore[attr-defined]
            "method": payload.get("method"),
            "id": payload.get("id"),
            "params": payload.get("params"),
            "session": request.headers.get("Mcp-Session-Id"),
            "accept": request.headers.get("Accept"),
            "authorization": request.headers.get("Authorization"),
        })
        method = payload.get("method")
        if method == "initialize":
            resp = jsonify({"jsonrpc": "2.0", "id": payload["id"], "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.1"},
            }})
            resp.headers["Mcp-Session-Id"] = "sess-123"
            return resp
        if method == "notifications/initialized":
            return "", 202
        if method == "tools/list":
            return jsonify({"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": [
                {"name": "search_news", "description": "Search news",
                 "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}},
            ]}})
        if method == "tools/call":
            msg = {"jsonrpc": "2.0", "id": payload["id"], "result": {
                "content": [{"type": "text", "text": "Headline: MCP lands in Homee"}],
                "isError": False,
            }}
            return Response(f"event: message\ndata: {_json.dumps(msg)}\n\n",
                            mimetype="text/event-stream")
        return jsonify({"jsonrpc": "2.0", "id": payload.get("id"),
                        "error": {"code": -32601, "message": f"No such method: {method}"}})

    @app.post("/mcp-auth")
    def mcp_auth():
        return jsonify({"error": "Unauthorized", "message": "Authentication required."}), 401

    server = make_server("127.0.0.1", 0, app)
    port = server.socket.getsockname()[1]
    thread = _threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield app, f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=5)


def _register_protocol_mcp(client, mcp_id, endpoint, **extra):
    payload = {"id": mcp_id, "name": mcp_id, "endpoint": endpoint, "protocol": "mcp"}
    payload.update(extra)
    resp = client.post("/api/mcps", json=payload)
    assert resp.status_code == 200


def test_register_mcp_stores_and_validates_protocol(client):
    _register_protocol_mcp(client, "news", "https://news.example/mcp")
    resp = client.get("/api/mcp/news")
    assert resp.get_json()["mcp"]["protocol"] == "mcp"

    resp = client.post("/api/mcps", json={"id": "bad", "endpoint": "https://x.example",
                                          "protocol": "carrier-pigeon"})
    assert resp.status_code == 400

    # Default stays generic HTTP so existing behavior is preserved.
    _register_mcp(client, "plain", "https://plain.example", "GET")
    assert client.get("/api/mcp/plain").get_json()["mcp"]["protocol"] == "http"


def test_execute_mcp_protocol_calls_tool(client, fake_mcp_server):
    """Full handshake: initialize → initialized → tools/call, session and
    auth headers propagated, SSE response normalized to plain text."""
    app, base = fake_mcp_server
    _register_protocol_mcp(client, "news", f"{base}/mcp",
                           headers={"Authorization": "Bearer test-key"})

    resp = client.post("/api/mcp/execute/news",
                       json={"tool": "search_news", "arguments": {"query": "ai"}})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["result"] == "Headline: MCP lands in Homee"
    assert data["tool"] == "search_news"
    assert data["status_code"] == 200

    methods = [h["method"] for h in app.hits]
    assert methods == ["initialize", "notifications/initialized", "tools/call"]
    assert app.hits[0]["session"] is None
    assert all(h["session"] == "sess-123" for h in app.hits[1:])
    assert all("text/event-stream" in h["accept"] for h in app.hits)
    assert all(h["authorization"] == "Bearer test-key" for h in app.hits)
    call = app.hits[-1]["params"]
    assert call["name"] == "search_news"
    assert call["arguments"] == {"query": "ai"}


def test_execute_mcp_protocol_lists_tools_when_no_tool(client, fake_mcp_server):
    app, base = fake_mcp_server
    _register_protocol_mcp(client, "news", f"{base}/mcp")

    resp = client.post("/api/mcp/execute/news", json={"query": "ai"})
    assert resp.status_code == 200
    data = resp.get_json()
    tools = data["result"]["tools"]
    assert tools[0]["name"] == "search_news"
    assert tools[0]["input_schema"]["properties"]["query"]["type"] == "string"
    assert "tool" in data["result"]["hint"]
    assert [h["method"] for h in app.hits] == ["initialize", "notifications/initialized", "tools/list"]


def test_execute_mcp_protocol_jsonrpc_passthrough(client, fake_mcp_server):
    """Hand-crafted JSON-RPC bodies keep working, inside a real session."""
    app, base = fake_mcp_server
    _register_protocol_mcp(client, "news", f"{base}/mcp")

    resp = client.post("/api/mcp/execute/news",
                       json={"jsonrpc": "2.0", "id": 9, "method": "tools/list"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["result"]["tools"][0]["name"] == "search_news"
    assert [h["method"] for h in app.hits] == ["initialize", "notifications/initialized", "tools/list"]
    assert app.hits[-1]["id"] == 9  # caller's id preserved


def test_execute_mcp_protocol_jsonrpc_error_is_clean(client, fake_mcp_server):
    _, base = fake_mcp_server
    _register_protocol_mcp(client, "news", f"{base}/mcp")

    resp = client.post("/api/mcp/execute/news",
                       json={"jsonrpc": "2.0", "id": 1, "method": "boom"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "No such method: boom" in data["error"]
    assert "result" not in data


def test_execute_mcp_protocol_auth_error_is_clean(client, fake_mcp_server):
    """A 401 (e.g. missing API key) surfaces as an error with status_code."""
    _, base = fake_mcp_server
    _register_protocol_mcp(client, "news", f"{base}/mcp-auth")

    resp = client.post("/api/mcp/execute/news", json={})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status_code"] == 401
    assert "401" in data["error"]
    assert "Authentication required" in data["error"]
    assert "result" not in data


def test_execute_mcp_protocol_unreachable_returns_502(client):
    _register_protocol_mcp(client, "down", "http://127.0.0.1:1/mcp")
    resp = client.post("/api/mcp/execute/down", json={})
    assert resp.status_code == 502
    assert "error" in resp.get_json()
