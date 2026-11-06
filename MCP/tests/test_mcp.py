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