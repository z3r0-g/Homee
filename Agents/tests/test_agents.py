"""Tests for the Agents package (independent of the UI and MCP apps)."""

from __future__ import annotations

from Agents.app import AgentBase, AgentResult, get_disk_space, run_shell
from Agents.local.demo import DemoAgent
from Agents.registry import agent_registry


def test_agent_result_defaults():
    result = AgentResult(content="hello")
    assert result.content == "hello"
    assert result.tool_calls == []
    assert result.knowledge_updated is False
    assert result.error is None


def test_demo_agent_subclass():
    assert issubclass(DemoAgent, AgentBase)
    agent = DemoAgent()
    assert agent.name == "Demo System Agent"
    assert agent.model == "qwen2.5"
    assert callable(get_disk_space)
    assert callable(run_shell)


def test_registry_lists_local_agent():
    agents = agent_registry.list_agents()
    names = {a["name"] for a in agents}
    assert "Demo System Agent" in names


def test_build_tool_specs_include_knowledge_base():
    agent = DemoAgent()
    specs = agent._build_tool_specs()
    names = {spec["function"]["name"] for spec in specs}
    assert {"get_disk_space", "run_shell", "knowledge_base"} <= names


def test_dispatch_knowledge_base(tmp_path):
    agent = DemoAgent()
    kb = tmp_path / "kb.md"
    result = agent._dispatch_tool("knowledge_base", {"content": "hello pytest"}, knowledge_path=str(kb))
    assert "Knowledge base updated" in result
    assert "hello pytest" in kb.read_text(encoding="utf-8")


def test_dispatch_unknown_tool():
    agent = DemoAgent()
    assert agent._dispatch_tool("no_such_tool", {}) == "Unknown tool: no_such_tool"


def test_run_shell_echo():
    out = run_shell("echo hello-pytest")
    assert "hello-pytest" in out