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
    # Pin the configured model: this test is about status reporting,
    # not about which default the host's RAM selects.
    client.post("/api/settings", json={"llm": {"local_model": "qwen2.5:7b"}})
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


# ── Settings redesign: catalog, model delete, MCP, agents ────────────

def test_llm_catalog_shape(client):
    resp = client.get("/api/llm/catalog")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["models"] and "ollama_search_url" in data
    assert "thinking" in data["capabilities"] and "vision" in data["capabilities"]
    assert all("size_gb" in m and "capabilities" in m for m in data["models"])


class _FakeDeleteRouter:
    def __init__(self):
        self.deleted = []

    def delete_model(self, model):
        self.deleted.append(model)
        return {"success": True, "model": model}


def test_llm_delete_model_route(client, monkeypatch):
    import UI.routes.settings as settings_routes
    fake = _FakeDeleteRouter()
    monkeypatch.setattr(settings_routes, "llm_router", fake)
    resp = client.delete("/api/llm/models/qwen2.5%3A7b")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert fake.deleted == ["qwen2.5:7b"]


def _mcp_proxy_stub(method, path, json_body=None):
    if method == "GET" and path == "/api/mcps":
        return {"mcps": [{"id": "local1", "name": "Local One",
                          "description": "d", "endpoint": "https://x.example",
                          "method": "GET"}]}, 200
    if method == "GET" and path == "/api/mcp/marketplace":
        return {"mcps": [{"id": "built1", "name": "Built One",
                          "description": "d"}]}, 200
    if method == "POST" and path == "/api/mcps":
        return {"success": True, "mcp": json_body}, 200
    if method == "PUT":
        return {"success": True}, 200
    return {"error": "not found"}, 404


def test_mcp_local_defaults_enabled(client, monkeypatch):
    import UI.routes.mcps as mcps_routes
    monkeypatch.setattr(mcps_routes, "_proxy", _mcp_proxy_stub)
    resp = client.get("/api/mcp/local")
    assert resp.status_code == 200
    mcps = resp.get_json()["mcps"]
    assert mcps[0]["enabled"] is True and mcps[0]["type"] == "local"


def test_mcp_remote_merges_curated_and_builtin(client, monkeypatch):
    import UI.routes.mcps as mcps_routes
    monkeypatch.setattr(mcps_routes, "_proxy", _mcp_proxy_stub)
    resp = client.get("/api/mcp/remote")
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.get_json()["mcps"]]
    assert "jsonplaceholder" in ids  # curated, no-auth entry
    assert "built1" in ids  # proxied built-in entry


def test_mcp_import_copies_remote_entry(client, monkeypatch):
    import UI.routes.mcps as mcps_routes
    monkeypatch.setattr(mcps_routes, "_proxy", _mcp_proxy_stub)
    resp = client.post("/api/mcp/import/jsonplaceholder")
    assert resp.status_code == 200
    assert resp.get_json()["mcp"]["endpoint"] == "https://jsonplaceholder.typicode.com"


def test_mcp_disable_proxies_put(client, monkeypatch):
    import UI.routes.mcps as mcps_routes
    seen = {}
    def stub(method, path, json_body=None):
        seen.update(method=method, path=path, body=json_body)
        return {"success": True}, 200
    monkeypatch.setattr(mcps_routes, "_proxy", stub)
    resp = client.post("/api/mcp/disable/local1")
    assert resp.status_code == 200
    assert seen["method"] == "PUT" and seen["body"] == {"enabled": False}


def test_agents_active_has_id_and_active(client):
    resp = client.get("/api/agents/active")
    assert resp.status_code == 200
    agents = resp.get_json()["agents"]
    assert agents, "expected the real local agents to be discovered"
    for agent in agents:
        assert agent["id"] == agent["name"]
        assert agent["active"] is True  # local agents on by default
        assert agent["source"] == "local"


def test_agents_toggle_disables_then_reenables(client):
    from urllib.parse import quote
    name = client.get("/api/agents/active").get_json()["agents"][0]["name"]
    resp = client.post(f"/api/agents/toggle/{quote(name, safe='')}")
    assert resp.status_code == 200
    assert resp.get_json()["active"] is False  # first toggle disables
    agents = client.get("/api/agents/active").get_json()["agents"]
    assert [a for a in agents if a["name"] == name][0]["active"] is False
    resp = client.post(f"/api/agents/toggle/{quote(name, safe='')}")
    assert resp.get_json()["active"] is True


def test_agents_refresh_imports_remote_personality_json(client, tmp_path, monkeypatch):
    import json
    import Agents.registry as registry
    remote_root = tmp_path / "remote"
    repo = remote_root / "my-agents"
    repo.mkdir(parents=True)
    (repo / "librarian.json").write_text(json.dumps({
        "name": "Librarian",
        "description": "Precise answers.",
        "system_prompt": "You are a careful librarian.",
    }))
    monkeypatch.setattr(registry, "REMOTE_DIR", remote_root)
    resp = client.post("/api/agents/refresh")
    assert resp.status_code == 200
    assert resp.get_json()["personalities_imported"] == 1
    data = client.get("/api/personalities").get_json()
    names = [p["name"] for p in data["personalities"]]
    assert "Librarian" in names


def test_llm_catalog_names_default_model(client):
    data = client.get("/api/llm/catalog").get_json()
    assert data["default_model"] in ("qwen2.5:3b", "qwen2.5:7b")


def test_settings_default_model_is_ram_aware(client):
    from UI import model_catalog
    expected = model_catalog.default_model(model_catalog.host_total_ram_gb())
    data = client.get("/api/settings").get_json()
    assert data["llm"]["local_model"] == expected


def test_update_bot_via_put(client):
    resp = client.post(
        "/api/bots",
        json={"name": "Edit Me", "task_prompt": "old", "enabled": True},
    )
    bot_id = resp.get_json()["bot"]["id"]
    resp = client.put(f"/api/bots/{bot_id}", json={
        "name": "Edited Bot",
        "personality_id": "general",
        "task_prompt": "summarize",
        "schedule_type": "interval",
        "interval_seconds": 600,
        "cron_expression": "",
    })
    assert resp.status_code == 200
    data = resp.get_json()["bot"]
    assert data["name"] == "Edited Bot"
    assert data["personality_id"] == "general"
    assert data["config"]["task_prompt"] == "summarize"
    assert data["config"]["schedule_type"] == "interval"
    assert data["config"]["interval_seconds"] == 600
    resp = client.put("/api/bots/nope", json={"name": "x"})
    assert resp.status_code == 404


def test_chat_passes_model_override(client, monkeypatch):
    import UI.routes.bots as bots_routes

    seen = {}

    class _StubRouter:
        def chat(self, messages, model=None):
            seen["model"] = model
            return {"message": {"content": "hello"}}

    monkeypatch.setattr(bots_routes, "llm_router", _StubRouter())
    resp = client.post("/api/bots", json={"name": "Chat Bot", "enabled": True})
    bot_id = resp.get_json()["bot"]["id"]
    resp = client.post(
        f"/api/bots/{bot_id}/chat",
        json={"message": "hi", "model": "qwen2.5:3b"},
    )
    assert resp.status_code == 200
    assert seen["model"] == "qwen2.5:3b"
    # No model field -> router default (Fast), not an override.
    resp = client.post(f"/api/bots/{bot_id}/chat", json={"message": "hi"})
    assert resp.status_code == 200
    assert seen["model"] is None
