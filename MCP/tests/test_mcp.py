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
    ids = {m["id"] for m in resp.get_json()["mcps"]}
    assert {"github", "slack", "google_sheets"} <= ids


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


def test_execute_unknown_mcp(client):
    resp = client.post("/api/mcp/execute/does_not_exist", json={})
    assert resp.status_code == 404