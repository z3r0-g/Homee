"""Skill contract tests — every local skill must honour the SkillBase contract.

The bot chat/run routes call ``execute(user_message, conversation_history=…,
knowledge_path=…, mcp_executor=…, mcp_tools=…, images=…)`` and read back a
``SkillResult``. These tests pin that contract for each local skill so a bot
assigned any of them always replies through its skill (PLAN.md — bots reply
using their assigned skill).
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from Skills.app import SkillBase, SkillResult
from Skills.local.burgundy import BurgundySkill
from Skills.local.demo import DemoSkill
from Skills.local.homekeeper import HomeKeeperSkill
from Skills.local.shipwright import ShipwrightSkill
from Skills.registry import skill_registry

ALL_LOCAL_SKILLS = [DemoSkill, BurgundySkill, HomeKeeperSkill, ShipwrightSkill]

EXECUTE_KWARGS = dict(
    conversation_history=[{"role": "user", "content": "earlier turn"}],
    knowledge_path=None,
    mcp_executor=lambda mcp_id, args: {"error": "no MCP in contract tests"},
    mcp_tools=[{"id": "system_disk", "name": "system_disk", "description": "disk"}],
    images=None,
)


class _FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def _patch_ollama(monkeypatch, captured, reply="contract reply", tool_calls=None):
    """Patch module-level ollama.chat used by SkillBase.execute."""
    import ollama

    def _chat(model=None, messages=None, tools=None, **kwargs):
        captured.append({"model": model, "messages": messages, "tools": tools})
        return SimpleNamespace(message=_FakeMessage(reply, tool_calls))

    monkeypatch.setattr(ollama, "chat", _chat)


# ════════════════════════════════════════════════════════════════
# Contract: shape
# ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("skill_cls", ALL_LOCAL_SKILLS, ids=lambda c: c.__name__)
def test_skill_is_skillbase_subclass(skill_cls):
    assert issubclass(skill_cls, SkillBase)
    skill = skill_cls()
    assert skill.name and isinstance(skill.name, str)
    assert skill.description and isinstance(skill.description, str)
    assert skill.system_prompt and isinstance(skill.system_prompt, str)


@pytest.mark.parametrize("skill_cls", ALL_LOCAL_SKILLS, ids=lambda c: c.__name__)
def test_skill_execute_signature_matches_contract(skill_cls):
    """execute() must accept exactly the kwargs the bot routes pass."""
    params = set(inspect.signature(skill_cls.execute).parameters)
    assert {"self", "user_message", "conversation_history", "knowledge_path",
            "mcp_executor", "mcp_tools", "images"} <= params


@pytest.mark.parametrize("skill_cls", ALL_LOCAL_SKILLS, ids=lambda c: c.__name__)
def test_skill_execute_returns_skill_result(skill_cls, monkeypatch, tmp_path):
    """A full execute turn with the bot-route kwargs must not raise and
    must return a SkillResult with content."""
    captured = []
    _patch_ollama(monkeypatch, captured)
    skill = skill_cls()
    kwargs = dict(EXECUTE_KWARGS)
    kwargs["knowledge_path"] = str(tmp_path / "kb.md")
    result = skill.execute("check disk status", **kwargs)
    assert isinstance(result, SkillResult)
    assert result.error is None
    assert isinstance(result.content, str) and result.content


@pytest.mark.parametrize("skill_cls", ALL_LOCAL_SKILLS, ids=lambda c: c.__name__)
def test_skill_discovered_in_registry(skill_cls):
    skills = skill_registry.list_skills()
    by_name = {s["name"]: s for s in skills}
    skill = skill_cls()
    assert skill.name in by_name, f"{skill.name} not discovered by the registry"
    assert by_name[skill.name]["source"] == "local"


# ════════════════════════════════════════════════════════════════
# Contract: LLM-backed skills inject their system prompt first
# ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("skill_cls", [DemoSkill, BurgundySkill, ShipwrightSkill],
                         ids=lambda c: c.__name__)
def test_llm_skill_sends_system_prompt_first(skill_cls, monkeypatch):
    captured = []
    _patch_ollama(monkeypatch, captured)
    skill = skill_cls()
    result = skill.execute("hello there")
    assert result.content == "contract reply"
    assert captured, "ollama.chat was not called"
    first = captured[0]["messages"][0]
    assert first["role"] == "system"
    assert first["content"] == skill.system_prompt


def test_homekeeper_replies_without_llm(monkeypatch):
    """HomeKeeper is deterministic: no ollama call, instant reply."""
    import ollama

    def _boom(**kwargs):
        raise AssertionError("HomeKeeper must not call the LLM")

    monkeypatch.setattr(ollama, "chat", _boom)
    skill = HomeKeeperSkill()
    result = skill.execute("check disk status", mcp_executor=lambda mid, args: {"result": "42 GB free out of 233 GB"})
    assert result.error is None
    assert "HomeKeeper" in result.content
    assert "Disk" in result.content


# ════════════════════════════════════════════════════════════════
# Contract: MCP tools are exposed to the LLM as mcp_<id> specs
# ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("skill_cls", ALL_LOCAL_SKILLS, ids=lambda c: c.__name__)
def test_mcp_tools_advertised_to_llm(skill_cls):
    skill = skill_cls()
    specs = skill._build_tool_specs(mcp_tools=[{"id": "fetch", "name": "Fetch", "description": "web fetch"}])
    names = {spec["function"]["name"] for spec in specs}
    assert "mcp_fetch" in names
    assert "knowledge_base" in names


def test_mcp_tool_call_dispatches_to_executor(monkeypatch):
    """When the LLM requests mcp_<id>, the bot's mcp_executor is invoked and
    the follow-up LLM call produces the reply."""
    import ollama

    calls = []
    executor_calls = []

    def _chat(model=None, messages=None, tools=None, **kwargs):
        calls.append({"messages": messages, "tools": tools})
        if len(calls) == 1:
            tc = SimpleNamespace(function=SimpleNamespace(name="mcp_fetch", arguments={"query": "x"}))
            return SimpleNamespace(message=_FakeMessage("", [tc]))
        return SimpleNamespace(message=_FakeMessage("final answer", []))

    monkeypatch.setattr(ollama, "chat", _chat)

    def _executor(mcp_id, args):
        executor_calls.append((mcp_id, args))
        return {"result": "page contents"}

    skill = DemoSkill()
    result = skill.execute("fetch something", mcp_executor=_executor,
                           mcp_tools=[{"id": "fetch", "name": "Fetch"}])
    assert executor_calls == [("fetch", {"query": "x"})]
    assert result.tool_calls == [{"name": "mcp_fetch", "arguments": {"query": "x"}}]
    assert result.content == "final answer"
    # The tool result is fed back to the model before the final answer.
    follow_up = calls[1]["messages"]
    assert any(m.get("role") == "tool" and "page contents" in str(m.get("content")) for m in follow_up)
