"""Tests for the UI service (independent Flask app, port 5001)."""

from __future__ import annotations

from UI.app import create_ui_app


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["service"] == "ui"
    assert data["port"] == 5001


def test_settings_defaults(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "llm" in data
    assert "scheduler" in data
    assert "mcp_service_url" in data
    assert "agents" in data
    assert data["agents"]["enabled"] is True
    assert data["agents"]["git_url"] == ""


def test_settings_post_agents_git_url(client):
    resp = client.post(
        "/api/settings",
        json={"agents": {"git_url": "https://example.com/org/agents.git", "enabled": True}},
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert resp.get_json()["settings"]["agents"]["git_url"] == "https://example.com/org/agents.git"
    # persisted to disk and reloaded
    resp = client.get("/api/settings")
    assert resp.get_json()["agents"]["git_url"] == "https://example.com/org/agents.git"


def test_list_bots_empty(client):
    resp = client.get("/api/bots")
    assert resp.status_code == 200
    assert resp.get_json()["bots"] == []
    assert resp.get_json()["count"] == 0


def test_create_and_get_bot(client):
    resp = client.post(
        "/api/bots",
        json={"name": "Test Bot", "task_prompt": "check disk space", "enabled": False},
    )
    assert resp.status_code == 201
    bot_id = resp.get_json()["bot"]["id"]
    resp = client.get(f"/api/bots/{bot_id}")
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Test Bot"


def test_list_personalities_empty(client):
    resp = client.get("/api/personalities")
    assert resp.status_code == 200
    assert resp.get_json()["personalities"] == []


def test_create_personality(client):
    resp = client.post(
        "/api/personalities",
        json={"name": "Helper", "system_prompt": "You are helpful."},
    )
    assert resp.status_code == 201
    pid = resp.get_json()["personality"]["id"]
    resp = client.get(f"/api/personalities/{pid}")
    assert resp.status_code == 200


def test_list_agents(client):
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    agents = resp.get_json()["agents"]
    names = {a["name"] for a in agents}
    assert "Demo System Agent" in names


def test_agents_refresh(client):
    resp = client.post("/api/agents/refresh")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert isinstance(body["agents"], list)