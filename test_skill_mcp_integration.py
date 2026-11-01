"""Integration: marketplace MCP → import → assign to one bot → chat.

Confirms (against both real services, in-process):
- a marketplace MCP installs via ``POST /api/mcp/import/{id}``,
- the assigned bot can call it (``mcp_<id>`` tool → MCP service → upstream),
- the bot still replies through its assigned Skill (skill system prompt leads
  every LLM call), and
- a bot NOT assigned the MCP cannot invoke it, even if the model asks.

Ollama is faked at the ``ollama.chat`` boundary; the MCP upstream is a local
in-process HTTP server. No external network is touched.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
import requests

from Skills.local.burgundy import BurgundySkill


class _FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


@pytest.fixture
def fake_upstream():
    """A stand-in for the marketplace MCP's remote endpoint."""
    from flask import Flask, jsonify
    from werkzeug.serving import make_server

    app = Flask("fake-mcp-upstream")
    app.hits = []  # type: ignore[attr-defined]

    @app.get("/weather")
    def weather():
        app.hits.append({"path": "/weather"})  # type: ignore[attr-defined]
        return jsonify({"temperature": "72F", "conditions": "sunny"})

    server = make_server("127.0.0.1", 0, app)
    port = server.socket.getsockname()[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield app, f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def fake_ollama(monkeypatch):
    """First call (tools advertised) requests mcp_fetch; follow-up answers."""
    import ollama

    captured = []

    def _chat(model=None, messages=None, tools=None, **kwargs):
        captured.append({"model": model, "messages": messages, "tools": tools})
        if tools:
            tc = SimpleNamespace(
                function=SimpleNamespace(name="mcp_fetch", arguments={"query": "weather"}))
            return SimpleNamespace(message=_FakeMessage("", [tc]))
        return SimpleNamespace(message=_FakeMessage("Sunny, 72F. Stay classy!", []))

    monkeypatch.setattr(ollama, "chat", _chat)
    return captured


def test_bot_uses_marketplace_mcp_and_retains_skill(e2e_servers, fake_upstream, fake_ollama):
    base_url = e2e_servers
    upstream_app, upstream_url = fake_upstream
    bot_id = bot2_id = None
    try:
        # 1. Import the "fetch" MCP from the marketplace, endpoint overridden
        #    to the local fake upstream (no real network).
        resp = requests.post(f"{base_url}/api/mcp/import/fetch",
                             json={"endpoint": f"{upstream_url}/weather", "method": "GET"},
                             timeout=10)
        assert resp.status_code == 200, resp.text
        assert resp.json()["mcp"]["id"] == "fetch"

        # 2. Create the bot with an assigned skill + the imported MCP.
        resp = requests.post(f"{base_url}/api/bots", json={
            "name": "Integration Weather Bot",
            "skill_id": BurgundySkill.name,
            "mcps": ["fetch"],
            "enabled": False,
        }, timeout=10)
        assert resp.status_code == 201, resp.text
        bot_id = resp.json()["bot"]["id"]
        assert resp.json()["bot"]["mcps"] == ["fetch"]

        # 3. Chat: the skill must offer mcp_fetch, execute it against the
        #    upstream, and reply through the skill path.
        resp = requests.post(f"{base_url}/api/bots/{bot_id}/chat",
                             json={"message": "what is the weather?"}, timeout=30)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["response"] == "Sunny, 72F. Stay classy!"
        assert body["skill"] == BurgundySkill.name

        # Skill-based instructions retained: Burgundy's system prompt leads.
        first_call = fake_ollama[0]
        assert first_call["messages"][0]["role"] == "system"
        assert first_call["messages"][0]["content"] == BurgundySkill.system_prompt
        tool_names = {t["function"]["name"] for t in first_call["tools"]}
        assert "mcp_fetch" in tool_names

        # The MCP round-trip really happened against the upstream.
        assert len(upstream_app.hits) == 1
        tool_msgs = [m for m in fake_ollama[1]["messages"] if m.get("role") == "tool"]
        assert tool_msgs and "sunny" in tool_msgs[0]["content"]

        # 4. A bot NOT assigned the MCP cannot invoke it.
        fake_ollama.clear()
        resp = requests.post(f"{base_url}/api/bots", json={
            "name": "Unassigned Bot", "skill_id": BurgundySkill.name,
            "mcps": ["system_disk"], "enabled": False,
        }, timeout=10)
        bot2_id = resp.json()["bot"]["id"]
        resp = requests.post(f"{base_url}/api/bots/{bot2_id}/chat",
                             json={"message": "fetch the weather"}, timeout=30)
        assert resp.status_code == 200
        tool_names2 = {t["function"]["name"] for t in fake_ollama[0]["tools"]}
        assert "mcp_fetch" not in tool_names2
        tool_msgs2 = [m for m in fake_ollama[1]["messages"] if m.get("role") == "tool"]
        assert tool_msgs2 and "not available" in tool_msgs2[0]["content"]
        assert len(upstream_app.hits) == 1, "unassigned bot reached the upstream"
    finally:
        if bot_id:
            requests.delete(f"{base_url}/api/bots/{bot_id}", timeout=10)
        if bot2_id:
            requests.delete(f"{base_url}/api/bots/{bot2_id}", timeout=10)
        requests.delete(f"{base_url}/api/mcps/fetch", timeout=10)
