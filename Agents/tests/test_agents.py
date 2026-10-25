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


# ════════════════════════════════════════════════════════════════
# Burundy Weather Agent
# ════════════════════════════════════════════════════════════════

import Agents.local.burgundy as burgundy  # noqa: E402
from Agents.local.burgundy import (  # noqa: E402
    BurundyAgent,
    BurundyWeatherAgent,
    get_weather_by_zip,
    get_weather_forecast,
)


class _FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


_WTTR_SAMPLE = {
    "current_condition": [
        {
            "FeelsLikeF": "65",
            "FeelsLikeC": "18",
            "temp_F": "70",
            "temp_C": "21",
            "humidity": "60",
            "windspeedMiles": "5",
            "windspeedKmph": "8",
            "visibility": "10",
            "visibilityMiles": "6",
            "weatherDesc": [{"value": "Sunny"}],
        }
    ],
    "nearest_area": [
        {
            "areaName": [{"value": "San Diego"}],
            "region": [{"value": "California"}],
            "country": [{"value": "United States of America"}],
        }
    ],
    "weather": [
        {
            "date": "2026-10-24",
            "mintempF": "63",
            "maxtempF": "72",
            "hourly": [{"weatherDesc": [{"value": "Sunny"}], "chanceofrain": "2"}],
        }
    ],
}


def test_burundy_agent_subclass():
    assert issubclass(BurundyAgent, AgentBase)
    assert BurundyAgent is BurundyWeatherAgent
    agent = BurundyAgent()
    assert agent.name == "Burundy Weather Agent"
    assert agent.model == "qwen2.5"


def test_registry_lists_burundy_agent():
    agents = agent_registry.list_agents()
    names = {a["name"] for a in agents}
    assert "Burundy Weather Agent" in names


def test_burundy_has_weather_tools():
    agent = BurundyAgent()
    names = {spec["function"]["name"] for spec in agent._build_tool_specs()}
    assert {"get_weather_forecast", "knowledge_base"} <= names


def test_burundy_system_prompt_style():
    agent = BurundyAgent()
    assert "Stay classy, San Diego" in agent.system_prompt


def test_get_weather_forecast_by_zip(monkeypatch):
    monkeypatch.setattr(
        burgundy.requests, "get", lambda *a, **k: _FakeResponse(_WTTR_SAMPLE)
    )
    result = get_weather_by_zip("92101")
    assert "San Diego" in result
    assert "°F" in result
    assert "Stay classy, San Diego!" in result
    assert "72" in result


def test_get_weather_forecast_metric(monkeypatch):
    monkeypatch.setattr(
        burgundy.requests, "get", lambda *a, **k: _FakeResponse(_WTTR_SAMPLE)
    )
    result = get_weather_forecast(latitude=32.7, longitude=-117.1, units="metric")
    assert "°C" in result
    assert "21" in result


def test_get_weather_forecast_no_location(monkeypatch):
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("requests.get should not be called with no location")

    monkeypatch.setattr(burgundy.requests, "get", _boom)
    result = get_weather_forecast()
    assert "zip code" in result.lower()
    assert called["n"] == 0


def test_get_weather_forecast_http_error(monkeypatch):
    monkeypatch.setattr(
        burgundy.requests,
        "get",
        lambda *a, **k: _FakeResponse({"error": "bad"}, status_code=404),
    )
    result = get_weather_by_zip("00000")
    assert "status 404" in result


def test_get_weather_forecast_connection_error(monkeypatch):
    import requests

    def _raise(*a, **k):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(burgundy.requests, "get", _raise)
    result = get_weather_by_zip("92101")
    assert "unavailable" in result.lower()