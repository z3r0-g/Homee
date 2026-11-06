"""Bot ↔ Skill contract tests (UI service).

Confirms bots reply using their assigned Skill: the skill's system prompt is
injected, the skill's execute() path produces the reply, and MCP tools are
available to the skill — including a skill installed from the marketplace.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from Skills.app import SkillBase, SkillResult
from Skills.local.mastodon import DemoSkill
from Skills.local.homekeeper import HomeKeeperSkill


class _FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


@pytest.fixture
def fake_ollama(monkeypatch):
    """Patch module-level ollama.chat (used by SkillBase.execute)."""
    import ollama

    captured = []

    def _chat(model=None, messages=None, tools=None, **kwargs):
        captured.append({"model": model, "messages": messages, "tools": tools})
        return SimpleNamespace(message=_FakeMessage("skill reply", []))

    monkeypatch.setattr(ollama, "chat", _chat)
    return captured


def _create_bot(client, **overrides):
    payload = {"name": "Skill Bot", "enabled": False}
    payload.update(overrides)
    resp = client.post("/api/bots", json=payload)
    assert resp.status_code == 201
    return resp.get_json()["bot"]["id"]


# ════════════════════════════════════════════════════════════════
# Bots reply using their assigned Skill
# ════════════════════════════════════════════════════════════════

def test_bot_replies_with_assigned_skill(client, fake_ollama):
    bot_id = _create_bot(client, skill_id="Demo (System Skill)")
    resp = client.post(f"/api/bots/{bot_id}/chat", json={"message": "hello"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["response"] == "skill reply"
    assert body["skill"] == "Demo (System Skill)"
    # The skill's system prompt leads the messages sent to the LLM.
    first = fake_ollama[0]["messages"][0]
    assert first["role"] == "system"
    assert first["content"] == DemoSkill.system_prompt
    assert "helpful" not in first["content"].lower() or DemoSkill.system_prompt != SkillBase.system_prompt


def test_bot_without_skill_uses_base_prompt(client, fake_ollama):
    bot_id = _create_bot(client)
    resp = client.post(f"/api/bots/{bot_id}/chat", json={"message": "hello"})
    assert resp.status_code == 200
    assert resp.get_json()["response"] == "skill reply"
    assert fake_ollama[0]["messages"][0]["content"] == SkillBase.system_prompt


def test_base_flow_injects_date_aware_cache_and_tool_policy(client, fake_ollama):
    bot_id = _create_bot(client)
    resp = client.post(f"/api/bots/{bot_id}/chat", json={"message": "hello"})
    assert resp.status_code == 200
    policy = fake_ollama[0]["messages"][1]["content"]
    assert "today's date is" in policy
    assert "first check the local knowledge cache" in policy
    assert "second, use an available Skill or MCP tool" in policy


def test_failed_skill_uses_disclosed_local_knowledge_fallback(client, monkeypatch):
    from UI.routes import bots

    bot_id = _create_bot(client)
    monkeypatch.setattr(
        SkillBase,
        "execute",
        lambda *args, **kwargs: SkillResult(content="", error="skill unavailable"),
    )
    monkeypatch.setattr(
        bots.llm_router,
        "chat",
        lambda *args, **kwargs: {"message": {"content": "fallback reply"}},
    )

    resp = client.post(f"/api/bots/{bot_id}/chat", json={"message": "hello"})
    assert resp.status_code == 200
    assert "fallback reply" in resp.get_json()["response"]
    assert "local model knowledge only" in resp.get_json()["response"]


def test_fallback_still_advertises_and_executes_tools(client, monkeypatch):
    """When the skill path fails, the router fallback keeps the bot's tools:
    specs are advertised and tool calls are dispatched through the MCP gate."""
    from UI.routes import bots

    bot_id = _create_bot(client, skill_id="Demo (System Skill)")
    monkeypatch.setattr(
        SkillBase,
        "execute",
        lambda *args, **kwargs: SkillResult(content="", error="skill unavailable"),
    )

    chats = []

    def _chat(messages, tools=None, model=None, **kwargs):
        chats.append({"messages": messages, "tools": tools})
        if any(m.get("role") == "tool" for m in messages):
            return {"message": {"role": "assistant",
                                "content": "fallback with tools", "tool_calls": []}}
        return {"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "mcp_system_disk", "arguments": {}}}]}}

    monkeypatch.setattr(bots.llm_router, "chat", _chat)

    resp = client.post(f"/api/bots/{bot_id}/chat", json={"message": "disk?"})
    assert resp.status_code == 200
    body = resp.get_json()["response"]
    assert "fallback with tools" in body
    assert "local model knowledge only" in body
    assert chats[0]["tools"], "fallback dropped tool specs"
    tool_names = {t["function"]["name"] for t in chats[0]["tools"]}
    assert "mcp_system_disk" in tool_names
    tool_msgs = [m for m in chats[1]["messages"] if m.get("role") == "tool"]
    assert tool_msgs and tool_msgs[0].get("tool_name") == "mcp_system_disk"


def test_bot_with_saved_skill_uses_saved_prompt(client, fake_ollama):
    resp = client.post("/api/skills", json={
        "name": "Pirate", "system_prompt": "Ye be a pirate assistant."})
    assert resp.status_code == 201
    skill_id = resp.get_json()["skill"]["id"]
    bot_id = _create_bot(client, skill_id=skill_id)
    resp = client.post(f"/api/bots/{bot_id}/chat", json={"message": "ahoy"})
    assert resp.status_code == 200
    assert fake_ollama[0]["messages"][0]["content"] == "Ye be a pirate assistant."


def test_bot_run_uses_assigned_skill(client, fake_ollama):
    bot_id = _create_bot(client, skill_id="Demo (System Skill)",
                         task_prompt="check disk space")
    resp = client.post(f"/api/bots/{bot_id}/run", json={})
    assert resp.status_code == 200
    assert resp.get_json()["response"] == "skill reply"
    assert fake_ollama[0]["messages"][0]["content"] == DemoSkill.system_prompt


def test_homekeeper_bot_replies_deterministically(client, monkeypatch):
    """A HomeKeeper bot replies through its skill without any LLM call."""
    import ollama

    def _boom(**kwargs):
        raise AssertionError("HomeKeeper must not call the LLM")

    monkeypatch.setattr(ollama, "chat", _boom)
    bot_id = _create_bot(client, skill_id=HomeKeeperSkill.name)
    resp = client.post(f"/api/bots/{bot_id}/chat", json={"message": "check disk status"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert "HomeKeeper" in body["response"]
    assert "Disk" in body["response"]


def test_bot_chat_history_recorded(client, fake_ollama):
    bot_id = _create_bot(client, skill_id="Demo (System Skill)")
    client.post(f"/api/bots/{bot_id}/chat", json={"message": "first question"})
    resp = client.get(f"/api/bots/{bot_id}")
    history = resp.get_json()["conversation_history"]
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "first question"
    assert history[1]["content"] == "skill reply"


# ════════════════════════════════════════════════════════════════
# Marketplace skill: install → assign → bot replies with its instructions
# ════════════════════════════════════════════════════════════════

def test_marketplace_skill_install_and_reply(client, fake_ollama):
    # 1. Marketplace is synced (cached snapshot; no network in tests).
    resp = client.get("/api/skills/marketplace")
    assert resp.status_code == 200
    entries = resp.get_json()["skills"]
    assert entries, "marketplace snapshot is empty"
    entry = entries[0]

    # 2. One-click install (same payload the frontend sends).
    resp = client.post("/api/skills", json={
        "name": entry["name"],
        "description": entry.get("description", ""),
        "skills": [],
        "abilities": [],
        "system_prompt": f"You are {entry['name']}. {entry.get('description', '')}".strip(),
    })
    assert resp.status_code == 201
    skill = resp.get_json()["skill"]
    assert entry["name"] in skill["system_prompt"]

    # 3. Assign to a bot and confirm the reply comes from that skill.
    bot_id = _create_bot(client, skill_id=skill["id"])
    resp = client.post(f"/api/bots/{bot_id}/chat", json={"message": "what are you?"})
    assert resp.status_code == 200
    assert resp.get_json()["response"] == "skill reply"
    prompt = fake_ollama[0]["messages"][0]["content"]
    assert entry["name"] in prompt
    assert entry["description"][:40] in prompt


# ════════════════════════════════════════════════════════════════
# Tool-less models: bots keep answering (and disclose no-tool use)
# ════════════════════════════════════════════════════════════════

def test_bot_chat_survives_tool_less_model(client, monkeypatch):
    """Regression: on a model without tool support (e.g. gemma3:4b), chat used
    to return the raw "does not support tools" error instead of an answer."""
    import ollama

    def _chat(model=None, messages=None, tools=None, **kwargs):
        if tools:
            raise Exception("gemma3:4b does not support tools (status code: 400)")
        return SimpleNamespace(message=_FakeMessage("tool-less reply", []))

    monkeypatch.setattr(ollama, "chat", _chat)
    bot_id = _create_bot(client, skill_id="Demo (System Skill)")
    resp = client.post(f"/api/bots/{bot_id}/chat", json={"message": "hi"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["response"] == "tool-less reply"
    assert "does not support tools" not in body["response"]
    assert body["sources"] == []


def test_bot_run_survives_tool_less_model(client, monkeypatch):
    """Scheduled/manual task runs recover the same way as chat."""
    import ollama

    def _chat(model=None, messages=None, tools=None, **kwargs):
        if tools:
            raise Exception("gemma3:4b does not support tools (status code: 400)")
        return SimpleNamespace(message=_FakeMessage("task reply", []))

    monkeypatch.setattr(ollama, "chat", _chat)
    bot_id = _create_bot(client, skill_id="Demo (System Skill)",
                         task_prompt="check disk space")
    resp = client.post(f"/api/bots/{bot_id}/run", json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["response"] == "task reply"
    assert body["sources"] == []


# ════════════════════════════════════════════════════════════════
# Sources: tool/MCP use is reported for citation
# ════════════════════════════════════════════════════════════════

def test_bot_chat_response_includes_sources(client, monkeypatch):
    import ollama

    def _chat(model=None, messages=None, tools=None, **kwargs):
        if not any(m.get("role") == "tool" for m in messages):
            tc = SimpleNamespace(
                function=SimpleNamespace(name="get_disk_space", arguments={}))
            return SimpleNamespace(message=_FakeMessage("", [tc]))
        return SimpleNamespace(message=_FakeMessage("disk report", []))

    monkeypatch.setattr(ollama, "chat", _chat)
    bot_id = _create_bot(client, skill_id="Demo (System Skill)")
    resp = client.post(f"/api/bots/{bot_id}/chat", json={"message": "disk?"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["response"] == "disk report"
    assert {s["name"] for s in body["sources"]} == {"get_disk_space"}
    # The assistant history entry carries the sources too.
    history = client.get(f"/api/bots/{bot_id}").get_json()["conversation_history"]
    assert history[-1]["role"] == "assistant"
    assert {s["name"] for s in history[-1]["sources"]} == {"get_disk_space"}


def test_bot_chat_labels_mcp_sources(client, monkeypatch):
    """MCP sources get the MCP's display name for citation, when available."""
    import ollama
    from UI.routes import bots

    def _chat(model=None, messages=None, tools=None, **kwargs):
        if not any(m.get("role") == "tool" for m in messages):
            tc = SimpleNamespace(
                function=SimpleNamespace(name="mcp_weather", arguments={"query": "x"}))
            return SimpleNamespace(message=_FakeMessage("", [tc]))
        return SimpleNamespace(message=_FakeMessage("sunny", []))

    monkeypatch.setattr(ollama, "chat", _chat)
    monkeypatch.setattr(
        bots, "_get_mcp_executor_and_tools",
        lambda bot: (
            lambda mcp_id, args: {"result": "sunny, 72F"},
            [{"id": "weather", "name": "Weather Service", "description": "wx"}],
        ),
    )
    bot_id = _create_bot(client, skill_id="Demo (System Skill)", mcps=["weather"])
    resp = client.post(f"/api/bots/{bot_id}/chat", json={"message": "weather?"})
    assert resp.status_code == 200
    sources = resp.get_json()["sources"]
    assert sources == [{"name": "mcp_weather", "kind": "mcp", "label": "Weather Service"}]


def test_create_bot_does_not_wipe_other_bots(client):
    """Multi-worker gunicorn: each worker keeps its own in-memory repo and
    save() writes the worker's whole dict — a stale worker must reload before
    saving, or bots created/deleted since its last load disappear."""
    from UI.models import bots_repo

    bot_a = _create_bot(client, name="Existing Bot")
    # Simulate a second gunicorn worker whose memory predates bot A.
    bots_repo._bots.clear()
    bot_b = _create_bot(client, name="New Bot")
    ids = {b["id"] for b in client.get("/api/bots").get_json()["bots"]}
    assert {bot_a, bot_b} <= ids
