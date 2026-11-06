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
from Skills.local.mastodon import DemoSkill
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


def test_tool_calls_chain_across_rounds(monkeypatch):
    """Regression: tools stay advertised after a tool result, so the model can
    chain another tool call instead of concluding it has no tool access."""
    import ollama

    calls = []
    executor_calls = []

    def _chat(model=None, messages=None, tools=None, **kwargs):
        calls.append({"messages": messages, "tools": tools})
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if len(tool_msgs) >= 2:
            return SimpleNamespace(message=_FakeMessage("chained answer", []))
        if tool_msgs:
            tc = SimpleNamespace(function=SimpleNamespace(name="get_disk_space", arguments={}))
        else:
            tc = SimpleNamespace(function=SimpleNamespace(name="mcp_fetch", arguments={"query": "x"}))
        return SimpleNamespace(message=_FakeMessage("", [tc]))

    monkeypatch.setattr(ollama, "chat", _chat)

    def _executor(mcp_id, args):
        executor_calls.append((mcp_id, args))
        return {"result": "page contents"}

    skill = DemoSkill()
    result = skill.execute("fetch then check disk", mcp_executor=_executor,
                           mcp_tools=[{"id": "fetch", "name": "Fetch"}])
    assert result.content == "chained answer"
    assert [c["name"] for c in result.tool_calls] == ["mcp_fetch", "get_disk_space"]
    assert executor_calls == [("fetch", {"query": "x"})]
    # Tools were advertised on every LLM call, not just the first.
    assert calls and all(c["tools"] for c in calls)
    # Each tool result immediately follows an assistant message that carries
    # the corresponding tool call (the sequence chat templates expect).
    for call in calls[1:]:
        msgs = call["messages"]
        for i, m in enumerate(msgs):
            if m.get("role") == "tool":
                assert msgs[i - 1].get("role") == "assistant"
                assert msgs[i - 1].get("tool_calls")


# ════════════════════════════════════════════════════════════════
# Contract: models without tool support still answer
# ════════════════════════════════════════════════════════════════

def test_tool_less_model_still_answers(monkeypatch):
    """Regression: a model that rejects tool specs (e.g. gemma3:4b "does not
    support tools") must not fail the turn — the skill retries without tools
    instead of returning "Skill LLM error"."""
    import ollama

    calls = []

    def _chat(model=None, messages=None, tools=None, **kwargs):
        calls.append({"messages": messages, "tools": tools})
        if tools:
            raise Exception(
                "registry.ollama.ai/library/gemma3:4b does not support tools "
                "(status code: 400)"
            )
        return SimpleNamespace(message=_FakeMessage("answer without tools", []))

    monkeypatch.setattr(ollama, "chat", _chat)
    skill = DemoSkill()
    result = skill.execute("hello", mcp_tools=[{"id": "fetch", "name": "Fetch"}])
    assert result.error is None
    assert result.content == "answer without tools"
    assert result.tool_calls == []
    assert calls[0]["tools"], "tools should be advertised on the first attempt"
    assert calls[-1]["tools"] is None, "the retry must drop tool specs"
    # The model is told tools are unavailable so it won't claim tool use.
    note = calls[-1]["messages"][-1]
    assert note["role"] == "system" and "Tool calling is unavailable" in note["content"]


def test_non_tool_error_still_fails_turn(monkeypatch):
    """A non-tool LLM error keeps the existing failure behavior."""
    import ollama

    def _chat(model=None, messages=None, tools=None, **kwargs):
        raise Exception("connection refused")

    monkeypatch.setattr(ollama, "chat", _chat)
    result = DemoSkill().execute("hello")
    assert result.error is not None
    assert "Skill LLM error" in result.content


# ════════════════════════════════════════════════════════════════
# Contract: real-world sourcing and citations
# ════════════════════════════════════════════════════════════════

def test_execute_reports_sources_for_citation(monkeypatch):
    """Tool/MCP calls made during a turn are reported as citable sources."""
    import ollama

    def _chat(model=None, messages=None, tools=None, **kwargs):
        if not any(m.get("role") == "tool" for m in messages):
            tc = SimpleNamespace(
                function=SimpleNamespace(name="mcp_fetch", arguments={"query": "x"}))
            return SimpleNamespace(message=_FakeMessage("", [tc]))
        return SimpleNamespace(message=_FakeMessage("done", []))

    monkeypatch.setattr(ollama, "chat", _chat)
    skill = DemoSkill()
    result = skill.execute("fetch something",
                           mcp_executor=lambda mid, args: {"result": "page"},
                           mcp_tools=[{"id": "fetch", "name": "Fetch"}])
    assert result.error is None
    assert {"name": "mcp_fetch", "kind": "mcp"} in result.sources


def test_base_context_requires_real_world_sources_and_citations():
    """The shared base policy pins real-world sourcing + citation rules."""
    from Skills.app import bot_base_context

    ctx = bot_base_context()
    assert '"Sources:"' in ctx
    assert "Never invent sources" in ctx
    assert "local model knowledge" in ctx


def test_base_system_prompt_requires_sources():
    """SkillBase's own prompt carries the sourcing/citation core instructions."""
    assert "Sources:" in SkillBase.system_prompt
    assert "Never invent" in SkillBase.system_prompt
