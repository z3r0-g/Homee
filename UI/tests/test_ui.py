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
    assert "skills" in data
    assert data["skills"]["enabled"] is True
    assert data["skills"]["git_url"] == ""


def test_settings_post_agents_git_url(client):
    resp = client.post(
        "/api/settings",
        json={"skills": {"git_url": "https://example.com/org/skills.git", "enabled": True}},
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert resp.get_json()["settings"]["skills"]["git_url"] == "https://example.com/org/skills.git"
    # persisted to disk and reloaded
    resp = client.get("/api/settings")
    assert resp.get_json()["skills"]["git_url"] == "https://example.com/org/skills.git"


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


def test_list_skills_empty(client):
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    assert resp.get_json()["skills"] == []


def test_create_skill(client):
    resp = client.post(
        "/api/skills",
        json={"name": "Helper", "system_prompt": "You are helpful."},
    )
    assert resp.status_code == 201
    pid = resp.get_json()["skill"]["id"]
    resp = client.get(f"/api/skills/{pid}")
    assert resp.status_code == 200


def test_list_skills(client):
    resp = client.get("/api/skills/discovered")
    assert resp.status_code == 200
    skills = resp.get_json()["skills"]
    names = {a["name"] for a in skills}
    assert "Demo (System Skill)" in names


def test_skills_refresh(client):
    resp = client.post("/api/skills/refresh")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert isinstance(body["skills"], list)

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
        "skills": {"git_url": "https://example.com/org/skills.git"},
    })
    assert resp.status_code == 200
    # Second save without mode / skills: both must survive (the old code
    # merged over defaults and reset them).
    resp = client.post("/api/settings", json={
        "llm": {"local_model": "qwen2.5:7b"},
    })
    assert resp.status_code == 200
    data = client.get("/api/settings").get_json()
    assert data["llm"]["mode"] == "local_cloud"
    assert data["skills"]["git_url"] == "https://example.com/org/skills.git"


def test_modes_rejects_unknown_mode(client):
    resp = client.post("/api/settings/modes", json={"mode": "bogus"})
    assert resp.status_code == 400


# ── Settings redesign: catalog, model delete, MCP, skills ────────────

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
                          "description": "d",
                          "endpoint": "https://built.example"}]}, 200
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


def test_mcp_remote_merges_leaderboard_and_builtin(client, monkeypatch):
    import UI.routes.mcps as mcps_routes
    monkeypatch.setattr(mcps_routes, "_proxy", _mcp_proxy_stub)
    resp = client.get("/api/mcp/remote")
    assert resp.status_code == 200
    mcps = resp.get_json()["mcps"]
    ids = [m["id"] for m in mcps]
    assert "lb-mcp-1" in ids  # leaderboard snapshot entry
    assert "built1" in ids  # proxied built-in entry
    assert "jsonplaceholder" not in ids  # retired curated catalog
    lb = [m for m in mcps if m["id"] == "lb-mcp-1"][0]
    assert lb["source"] == "Leaderboard" and lb["rank"] == 1
    assert lb["endpoint"] == ""  # no endpoint: Use-this + View, no Import


def test_mcp_import_copies_remote_entry(client, monkeypatch):
    import UI.routes.mcps as mcps_routes
    monkeypatch.setattr(mcps_routes, "_proxy", _mcp_proxy_stub)
    resp = client.post("/api/mcp/import/built1")
    assert resp.status_code == 200
    assert resp.get_json()["mcp"]["endpoint"] == "https://built.example"


def test_mcp_import_rejects_leaderboard_entry(client, monkeypatch):
    import UI.routes.mcps as mcps_routes
    monkeypatch.setattr(mcps_routes, "_proxy", _mcp_proxy_stub)
    resp = client.post("/api/mcp/import/lb-mcp-1")
    assert resp.status_code == 400
    assert "no endpoint" in resp.get_json()["error"]


def test_mcp_remote_enriches_leaderboard_endpoint(client, monkeypatch):
    """A leaderboard entry whose ID also appears in the marketplace
    gets its endpoint enriched so the card can offer Import instead of
    the manual Use-this flow."""
    import UI.routes.mcps as mcps_routes

    def _stub_with_match(method, path, json_body=None):
        if method == "GET" and path == "/api/mcp/marketplace":
            return {"mcps": [
                {"id": "built1", "name": "Built One", "endpoint": "https://built.example"},
                {"id": "lb-mcp-1", "name": "Reverse Engineer Anything", "endpoint": "https://mcp.reverse.example"},
            ]}, 200
        if method == "POST" and path == "/api/mcps":
            return {"success": True, "mcp": json_body}, 200
        return {"error": "not found"}, 404

    monkeypatch.setattr(mcps_routes, "_proxy", _stub_with_match)
    resp = client.get("/api/mcp/remote")
    assert resp.status_code == 200
    mcps = resp.get_json()["mcps"]
    lb = [m for m in mcps if m["id"] == "lb-mcp-1"][0]
    assert lb["endpoint"] == "https://mcp.reverse.example"  # enriched from marketplace
    assert lb["source"] == "Leaderboard" and lb["rank"] == 1  # leaderboard metadata preserved


def test_skills_leaderboard_returns_snapshot(client):
    resp = client.get("/api/skills/leaderboard")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["snapshot_date"] == "2026-10-27"
    assert "mcpmarket.com/tools/skills/leaderboard" in data["source_url"]
    skills = data["skills"]
    assert len(skills) == 30
    assert [s["rank"] for s in skills] == list(range(1, 31))
    for skill in skills:
        assert skill["author"] and skill["name"] and skill["description"]
        assert skill["category"] and skill["stars"]


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


def test_skills_active_has_id_and_active(client):
    resp = client.get("/api/skills/active")
    assert resp.status_code == 200
    skills = resp.get_json()["skills"]
    assert skills, "expected the real local skills to be discovered"
    for skill in skills:
        assert skill["id"] == skill["name"]
        assert skill["active"] is True  # local skills on by default
        assert skill["source"] == "local"


def test_skills_toggle_disables_then_reenables(client):
    from urllib.parse import quote
    name = client.get("/api/skills/active").get_json()["skills"][0]["name"]
    resp = client.post(f"/api/skills/toggle/{quote(name, safe='')}")
    assert resp.status_code == 200
    assert resp.get_json()["active"] is False  # first toggle disables
    skills = client.get("/api/skills/active").get_json()["skills"]
    assert [a for a in skills if a["name"] == name][0]["active"] is False
    resp = client.post(f"/api/skills/toggle/{quote(name, safe='')}")
    assert resp.get_json()["active"] is True


def test_skills_refresh_imports_remote_personality_json(client, tmp_path, monkeypatch):
    import Skills.registry as registry
    remote_root = tmp_path / "remote"
    repo = remote_root / "my-skills"
    repo.mkdir(parents=True)
    (repo / "librarian.md").write_text(
        "---\n"
        "name: Librarian\n"
        "description: Precise answers.\n"
        "---\n"
        "\n"
        "You are a careful librarian.\n"
    )
    monkeypatch.setattr(registry, "REMOTE_DIR", remote_root)
    resp = client.post("/api/skills/refresh")
    assert resp.status_code == 200
    assert resp.get_json()["skills_imported"] == 1
    data = client.get("/api/skills").get_json()
    names = [p["name"] for p in data["skills"]]
    assert "Librarian" in names


def test_llm_catalog_names_default_model(client):
    data = client.get("/api/llm/catalog").get_json()
    assert data["default_model"] == "llama3.2:3b"


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
        "skill_id": "general",
        "task_prompt": "summarize",
        "schedule_type": "interval",
        "interval_seconds": 600,
        "cron_expression": "",
    })
    assert resp.status_code == 200
    data = resp.get_json()["bot"]
    assert data["name"] == "Edited Bot"
    assert data["skill_id"] == "general"
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


def test_chat_attachment_context_not_persisted(client, monkeypatch):
    import UI.routes.bots as bots_routes

    seen = {}

    class _StubRouter:
        def chat(self, messages, model=None):
            seen["messages"] = messages
            return {"message": {"content": "based on the file"}}

    monkeypatch.setattr(bots_routes, "llm_router", _StubRouter())
    resp = client.post("/api/bots", json={"name": "File Bot", "enabled": True})
    bot_id = resp.get_json()["bot"]["id"]
    resp = client.post(f"/api/bots/{bot_id}/chat", json={
        "message": "what does it say?",
        "attachments": [{"name": "notes.txt", "content": "the garden needs water"}],
    })
    assert resp.status_code == 200
    systems = [m for m in seen["messages"] if m["role"] == "system"]
    assert any("notes.txt" in m["content"] and "the garden needs water" in m["content"]
               for m in systems)
    # Attachment context must not land in persisted history.
    history = client.get(f"/api/bots/{bot_id}").get_json()["conversation_history"]
    assert len(history) == 2
    assert all("the garden needs water" not in m["content"] for m in history)


def test_search_across_chats(client, monkeypatch):
    import UI.routes.bots as bots_routes

    class _StubRouter:
        def chat(self, messages, model=None):
            return {"message": {"content": "ok"}}

    monkeypatch.setattr(bots_routes, "llm_router", _StubRouter())
    resp = client.post("/api/bots", json={"name": "Garden Bot", "enabled": True})
    bot_id = resp.get_json()["bot"]["id"]
    client.post(f"/api/bots/{bot_id}/chat", json={"message": "how is my garden doing?"})
    resp = client.get("/api/bots/search?q=garden")
    assert resp.status_code == 200
    results = resp.get_json()["results"]
    assert len(results) >= 1
    assert results[0]["bot_id"] == bot_id
    assert "garden" in results[0]["snippet"].lower()
    resp = client.get("/api/bots/search?q=zzzznope")
    assert resp.get_json()["results"] == []
    resp = client.get("/api/bots/search")
    assert resp.get_json()["results"] == []


def test_mcp_status_running(client, monkeypatch):
    import requests

    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, timeout=None):
        if url.endswith("/api/health"):
            return _Resp(200, {"status": "ok", "service": "mcp"})
        if url.endswith("/api/mcps"):
            return _Resp(200, {"mcps": [{"id": "a"}, {"id": "b"}]})
        raise AssertionError(url)

    monkeypatch.setattr(requests, "get", fake_get)
    resp = client.get("/api/mcp/status")
    assert resp.status_code == 200
    assert resp.get_json() == {"running": True, "count": 2}


def test_mcp_status_offline(client, monkeypatch):
    import requests

    def fake_get(url, timeout=None):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "get", fake_get)
    resp = client.get("/api/mcp/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["running"] is False
