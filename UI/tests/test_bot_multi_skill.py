"""Multi-skill bot tests — bots are no longer 1:1 with skills.

A bot can combine several skills (composite system prompt + union of tools)
plus several MCP servers, and always keeps adhoc chat.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from Skills.app import SkillBase
from Skills.local.burgundy import BurgundySkill
from Skills.local.demo import DemoSkill
from Skills.local.homekeeper import HomeKeeperSkill
from UI.models import Bot
from UI.routes.bots import _resolve_bot_skills


class _FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


@pytest.fixture
def fake_ollama(monkeypatch):
    import ollama

    captured = []

    def _chat(model=None, messages=None, tools=None, **kwargs):
        captured.append({"model": model, "messages": messages, "tools": tools})
        return SimpleNamespace(message=_FakeMessage("multi reply", []))

    monkeypatch.setattr(ollama, "chat", _chat)
    return captured


def _create_bot(client, **overrides):
    payload = {"name": "Multi Bot", "enabled": False}
    payload.update(overrides)
    resp = client.post("/api/bots", json=payload)
    assert resp.status_code == 201
    return resp.get_json()["bot"]


# ════════════════════════════════════════════════════════════════
# Model: migration + sync
# ════════════════════════════════════════════════════════════════

def test_bot_model_migrates_legacy_skill_id():
    bot = Bot.from_dict({"id": "b1", "name": "Old", "skill_id": "demo"})
    assert bot.skill_ids == ["demo"]
    assert bot.skill_id_list() == ["demo"]
    d = bot.to_dict()
    assert d["skill_id"] == "demo"  # legacy readers keep working
    assert d["skill_ids"] == ["demo"]


def test_bot_model_set_skills_syncs_primary():
    bot = Bot(id="b2", name="B")
    bot.set_skills(["a", "b"])
    assert bot.skill_id == "a"
    assert bot.skill_id_list() == ["a", "b"]
    bot.set_skills([])
    assert bot.skill_id == ""
    assert bot.to_dict()["skill_ids"] == []


# ════════════════════════════════════════════════════════════════
# Resolution: composite skill
# ════════════════════════════════════════════════════════════════

def test_resolve_zero_skills_is_base():
    cls, prompt = _resolve_bot_skills([])
    assert cls is SkillBase
    assert prompt == SkillBase.system_prompt


def test_resolve_single_skill_preserves_custom_execute():
    cls, prompt = _resolve_bot_skills([HomeKeeperSkill.name])
    assert cls.name == HomeKeeperSkill.name
    assert cls.execute is not SkillBase.execute  # deterministic execute kept


def test_resolve_multiple_skills_composite():
    cls, prompt = _resolve_bot_skills([DemoSkill.name, BurgundySkill.name])
    skill = cls()
    assert "Demo" in skill.name and "Burgundy" in skill.name
    assert "helpful local system assistant" in prompt
    assert "Stay classy" in prompt
    specs = {s["function"]["name"] for s in skill._build_tool_specs()}
    assert {"get_disk_space", "run_shell", "get_weather_forecast", "knowledge_base"} <= specs


def test_composite_dedupes_shared_tools():
    cls, _ = _resolve_bot_skills([DemoSkill.name, DemoSkill.name])
    specs = [s["function"]["name"] for s in cls()._build_tool_specs()]
    assert specs.count("get_disk_space") == 1


def test_composite_with_homekeeper_uses_llm_path():
    """HomeKeeper's deterministic execute is single-skill only; in a
    composite its prompt and tools join the shared LLM turn."""
    cls, prompt = _resolve_bot_skills([HomeKeeperSkill.name, DemoSkill.name])
    assert cls.execute is SkillBase.execute
    assert "HomeKeeper" in prompt
    assert "helpful local system assistant" in prompt


# ════════════════════════════════════════════════════════════════
# API: create / update / chat with multiple skills
# ════════════════════════════════════════════════════════════════

def test_create_bot_with_multiple_skills_and_mcps(client):
    bot = _create_bot(client, skill_ids=[DemoSkill.name, BurgundySkill.name],
                      mcps=["system_disk", "system_shell"])
    assert bot["skill_ids"] == [DemoSkill.name, BurgundySkill.name]
    assert bot["skill_id"] == DemoSkill.name  # primary for legacy readers
    assert bot["mcps"] == ["system_disk", "system_shell"]

    resp = client.get(f"/api/bots/{bot['id']}")
    assert resp.get_json()["skill_ids"] == [DemoSkill.name, BurgundySkill.name]


def test_create_bot_legacy_skill_id_still_works(client):
    bot = _create_bot(client, skill_id=DemoSkill.name)
    assert bot["skill_ids"] == [DemoSkill.name]
    assert bot["skill_id"] == DemoSkill.name


def test_update_bot_skill_ids(client):
    bot = _create_bot(client, skill_ids=[DemoSkill.name])
    resp = client.put(f"/api/bots/{bot['id']}", json={
        "skill_ids": [BurgundySkill.name, HomeKeeperSkill.name],
        "mcps": ["system_disk"],
    })
    assert resp.status_code == 200
    data = resp.get_json()["bot"]
    assert data["skill_ids"] == [BurgundySkill.name, HomeKeeperSkill.name]
    assert data["skill_id"] == BurgundySkill.name
    assert data["mcps"] == ["system_disk"]


def test_multi_skill_bot_replies_with_combined_prompt(client, fake_ollama):
    bot = _create_bot(client, skill_ids=[DemoSkill.name, BurgundySkill.name])
    resp = client.post(f"/api/bots/{bot['id']}/chat", json={"message": "hello"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["response"] == "multi reply"
    assert body["skills"] == [DemoSkill.name, BurgundySkill.name]
    assert body["skill"] == DemoSkill.name

    prompt = fake_ollama[0]["messages"][0]["content"]
    assert "helpful local system assistant" in prompt
    assert "Stay classy" in prompt
    tool_names = {t["function"]["name"] for t in fake_ollama[0]["tools"]}
    assert {"get_disk_space", "get_weather_forecast"} <= tool_names


def test_multi_skill_bot_with_saved_marketplace_skill(client, fake_ollama):
    resp = client.post("/api/skills", json={
        "name": "Background Coding Agent",
        "description": "Delegates complex coding tasks to background CLI workers.",
    })
    skill_id = resp.get_json()["skill"]["id"]
    bot = _create_bot(client, skill_ids=[skill_id, BurgundySkill.name])
    resp = client.post(f"/api/bots/{bot['id']}/chat", json={"message": "hi"})
    assert resp.status_code == 200
    prompt = fake_ollama[0]["messages"][0]["content"]
    assert "Background Coding Agent" in prompt
    assert "Stay classy" in prompt


def test_multi_skill_bot_run_uses_composite(client, fake_ollama):
    bot = _create_bot(client, skill_ids=[DemoSkill.name, BurgundySkill.name],
                      task_prompt="morning check")
    resp = client.post(f"/api/bots/{bot['id']}/run", json={})
    assert resp.status_code == 200
    assert resp.get_json()["response"] == "multi reply"
    prompt = fake_ollama[0]["messages"][0]["content"]
    assert "helpful local system assistant" in prompt
    assert "Stay classy" in prompt


def test_multi_skill_bot_mcp_tools_gated(client, monkeypatch):
    """Assigned MCPs are advertised; unassigned ones stay blocked.
    (Built-in system_disk/system_shell are intentionally available to every
    bot, so the unassigned case uses a non-builtin MCP id.)"""
    import ollama

    calls = []

    def _chat(model=None, messages=None, tools=None, **kwargs):
        calls.append({"messages": messages, "tools": tools})
        if tools:
            tc = SimpleNamespace(function=SimpleNamespace(
                name="mcp_fetch", arguments={"query": "x"}))
            return SimpleNamespace(message=_FakeMessage("", [tc]))
        return SimpleNamespace(message=_FakeMessage("done", []))

    monkeypatch.setattr(ollama, "chat", _chat)

    bot = _create_bot(client, skill_ids=[DemoSkill.name, BurgundySkill.name],
                      mcps=["system_disk"])  # fetch NOT assigned
    resp = client.post(f"/api/bots/{bot['id']}/chat", json={"message": "fetch x"})
    assert resp.status_code == 200
    advertised = {t["function"]["name"] for t in calls[0]["tools"]}
    assert "mcp_system_disk" in advertised
    assert "mcp_fetch" not in advertised
    tool_msgs = [m for m in calls[1]["messages"] if m.get("role") == "tool"]
    assert tool_msgs and "not available" in tool_msgs[0]["content"]
