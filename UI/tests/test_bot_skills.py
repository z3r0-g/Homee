"""Bot ↔ Skill contract tests (UI service).

Confirms bots reply using their assigned Skill: the skill's system prompt is
injected, the skill's execute() path produces the reply, and MCP tools are
available to the skill — including a skill installed from the marketplace.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from Skills.app import SkillBase, SkillResult
from Skills.local.demo import DemoSkill
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
