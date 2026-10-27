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
    assert "Demo (System Agent)" in names


def test_agents_refresh(client):
    resp = client.post("/api/agents/refresh")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert isinstance(body["agents"], list)

# ── LLM status / pull endpoints (ollama-first) ─────────────────────────

class _FakeOllamaClient:
    """Minimal ollama.Client stand-in for endpoint tests."""

    def __init__(self, models=(), pull_block=None):
        self.models = list(models)
        self.pull_block = pull_block
        self.pulled = []

    def list(self):
        return {"models": [{"name": name} for name in self.models]}

    def pull(self, model, stream=False):
        self.pulled.append(model)
        if self.pull_block is not None:
            self.pull_block.wait(timeout=10)
        if stream:
            return iter(())
        return None


def _patch_llm_router(monkeypatch):
    from UI.llm import LLMRouter
    from UI.routes import settings as settings_routes
    return settings_routes, LLMRouter


def test_llm_status_endpoint(client, monkeypatch):
    settings_routes, LLMRouter = _patch_llm_router(monkeypatch)
    monkeypatch.setattr(
        settings_routes, "llm_router",
        LLMRouter(client=_FakeOllamaClient(models=["qwen2.5:7b"])))
    resp = client.get("/api/llm/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["running"] is True
    assert data["configured_model_installed"] is True
    assert data["models"] == ["qwen2.5:7b"]


def test_llm_pull_flow(client, monkeypatch):
    import time
    settings_routes, LLMRouter = _patch_llm_router(monkeypatch)
    monkeypatch.setattr(
        settings_routes, "llm_router",
        LLMRouter(client=_FakeOllamaClient()))
    resp = client.post("/api/llm/pull", json={"model": "qwen2.5:7b"})
    assert resp.status_code == 202
    deadline = time.time() + 5
    job = {}
    while time.time() < deadline:
        job = client.get("/api/llm/pull").get_json()["job"]
        if job["state"] in ("done", "error"):
            break
        time.sleep(0.02)
    assert job["state"] == "done"
    assert job["model"] == "qwen2.5:7b"


def test_llm_pull_conflict(client, monkeypatch):
    import threading
    settings_routes, LLMRouter = _patch_llm_router(monkeypatch)
    block = threading.Event()
    monkeypatch.setattr(
        settings_routes, "llm_router",
        LLMRouter(client=_FakeOllamaClient(pull_block=block)))
    try:
        first = client.post("/api/llm/pull", json={"model": "qwen2.5:7b"})
        assert first.status_code == 202
        second = client.post("/api/llm/pull", json={"model": "llama3.1:8b"})
        assert second.status_code == 409
    finally:
        block.set()


# ── Settings save must preserve fields the form does not send ────────

def test_settings_save_preserves_mode_and_git_url(client):
    resp = client.post("/api/settings/modes", json={"mode": "local_cloud"})
    assert resp.status_code == 200
    resp = client.post("/api/settings", json={
        "llm": {"local_model": "qwen2.5:7b"},
        "agents": {"git_url": "https://example.com/org/agents.git"},
    })
    assert resp.status_code == 200
    # Second save without mode / agents: both must survive (the old code
    # merged over defaults and reset them).
    resp = client.post("/api/settings", json={
        "llm": {"local_model": "qwen2.5:7b"},
    })
    assert resp.status_code == 200
    data = client.get("/api/settings").get_json()
    assert data["llm"]["mode"] == "local_cloud"
    assert data["agents"]["git_url"] == "https://example.com/org/agents.git"


def test_modes_rejects_unknown_mode(client):
    resp = client.post("/api/settings/modes", json={"mode": "bogus"})
    assert resp.status_code == 400
