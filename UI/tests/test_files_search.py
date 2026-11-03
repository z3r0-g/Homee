"""Tests for PLAN.md Chapter 1: Ask About a File + Search Across Chats."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from UI.config import BOTS_DIR, INSTANCES_DIR


class _FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


@pytest.fixture
def fake_ollama(monkeypatch):
    """Capture messages sent through SkillBase.execute's ollama.chat call."""
    import ollama

    captured = []

    def _chat(model=None, messages=None, tools=None, **kwargs):
        captured.append({"model": model, "messages": messages, "tools": tools})
        return SimpleNamespace(message=_FakeMessage("skill reply", []))

    monkeypatch.setattr(ollama, "chat", _chat)
    return captured


def _create_bot(client, **overrides):
    payload = {"name": "File Bot", "enabled": False}
    payload.update(overrides)
    resp = client.post("/api/bots", json=payload)
    assert resp.status_code == 201
    return resp.get_json()["bot"]["id"]


def _last_user_prompt(captured):
    return captured[-1]["messages"][-1]["content"]


# ════════════════════════════════════════════════════════════════
# 1.1 Ask About a File
# ════════════════════════════════════════════════════════════════

def test_chat_multipart_file_injection(client, fake_ollama):
    bot_id = _create_bot(client)
    resp = client.post(
        f"/api/bots/{bot_id}/chat",
        data={"message": "summarize this",
              "file": (io.BytesIO("line one\nline two".encode("utf-8")), "notes.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert resp.get_json()["response"] == "skill reply"
    prompt = _last_user_prompt(fake_ollama)
    assert "[User attached file: notes.txt (17 chars)]" in prompt
    assert "line one\nline two" in prompt
    assert "summarize this" in prompt


def test_chat_multipart_file_truncation(client, fake_ollama):
    bot_id = _create_bot(client)
    big = "x" * 20_000
    resp = client.post(
        f"/api/bots/{bot_id}/chat",
        data={"message": "read it", "file": (io.BytesIO(big.encode()), "big.log")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    prompt = _last_user_prompt(fake_ollama)
    assert "[User attached file: big.log (20000 chars, truncated to 12000)]" in prompt
    assert "x" * 12_000 in prompt
    assert "x" * 12_001 not in prompt


def test_chat_multipart_binary_rejected(client, fake_ollama):
    bot_id = _create_bot(client)
    resp = client.post(
        f"/api/bots/{bot_id}/chat",
        data={"message": "open this", "file": (io.BytesIO(b"\x00\x01\x02\x03PNG"), "img.bin")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "binary" in resp.get_json()["error"].lower()
    assert not fake_ollama, "LLM must not be called for a rejected attachment"


def test_chat_json_attachment_injection(client, fake_ollama):
    """The JSON attachment path (current frontend) uses the same format."""
    bot_id = _create_bot(client)
    resp = client.post(f"/api/bots/{bot_id}/chat", json={
        "message": "what does this say?",
        "attachments": [{"name": "data.json", "content": '{"a": 1}'}],
    })
    assert resp.status_code == 200
    prompt = _last_user_prompt(fake_ollama)
    assert "[User attached file: data.json (8 chars)]" in prompt
    assert '{"a": 1}' in prompt


def test_chat_file_without_message_gets_default_prompt(client, fake_ollama):
    bot_id = _create_bot(client)
    resp = client.post(
        f"/api/bots/{bot_id}/chat",
        data={"file": (io.BytesIO(b"hello file"), "f.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert "attached file" in _last_user_prompt(fake_ollama)


def test_chat_attachment_never_written_to_instances(client, fake_ollama):
    """PLAN.md 1.1 constraint: attachments never land in UI/instances/."""
    bot_id = _create_bot(client)
    secret = "quixotic-attachment-content-7f3a9c"
    resp = client.post(f"/api/bots/{bot_id}/chat", json={
        "message": "remember this?",
        "attachments": [{"name": "secret.txt", "content": secret}],
    })
    assert resp.status_code == 200
    for path in INSTANCES_DIR.rglob("*"):
        if path.is_file():
            assert secret not in path.read_text(encoding="utf-8", errors="ignore"), \
                f"attachment content persisted to {path}"


def test_chat_attachment_in_fallback_llm_path(client, monkeypatch):
    """If skill execution fails, the LLM-router fallback still gets the file."""
    import ollama

    def _boom(**kwargs):
        raise ConnectionError("ollama down")

    monkeypatch.setattr(ollama, "chat", _boom)

    captured = {}

    class _FakeRouter:
        def chat(self, messages, tools=None, model=None):
            captured["messages"] = messages
            captured["tools"] = tools
            return {"message": {"content": "fallback reply"}}

    monkeypatch.setattr("UI.routes.bots.llm_router", _FakeRouter())

    bot_id = _create_bot(client)
    resp = client.post(f"/api/bots/{bot_id}/chat", json={
        "message": "read this",
        "attachments": [{"name": "notes.md", "content": "# Notes\nhello"}],
    })
    assert resp.status_code == 200
    assert "fallback reply" in resp.get_json()["response"]
    user_turn = captured["messages"][-1]
    assert user_turn["role"] == "user"
    assert "[User attached file: notes.md (13 chars)]" in user_turn["content"]
    assert "# Notes\nhello" in user_turn["content"]


# ════════════════════════════════════════════════════════════════
# 1.2 Search Across Chats
# ════════════════════════════════════════════════════════════════

def test_search_finds_message_with_metadata(client, fake_ollama):
    bot_id = _create_bot(client, name="Searchable Bot")
    client.post(f"/api/bots/{bot_id}/chat", json={"message": "the quixotic aardvark"})
    resp = client.get("/api/search?q=aardvark")
    assert resp.status_code == 200
    results = resp.get_json()["results"]
    assert len(results) == 1
    hit = results[0]
    assert hit["bot_id"] == bot_id
    assert hit["bot_name"] == "Searchable Bot"
    assert hit["role"] == "user"
    assert "aardvark" in hit["snippet"]
    assert hit["timestamp"]


def test_search_writes_history_jsonl(client, fake_ollama):
    bot_id = _create_bot(client)
    client.post(f"/api/bots/{bot_id}/chat", json={"message": "logged message"})
    path = BOTS_DIR / bot_id / "history.jsonl"
    assert path.exists()
    lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert [m["role"] for m in lines] == ["user", "assistant"]
    assert lines[0]["content"] == "logged message"


def test_search_empty_query(client):
    resp = client.get("/api/search?q=")
    assert resp.status_code == 200
    assert resp.get_json()["results"] == []


def test_search_case_insensitive(client, fake_ollama):
    bot_id = _create_bot(client)
    client.post(f"/api/bots/{bot_id}/chat", json={"message": "MixedCase Needle"})
    resp = client.get("/api/search?q=mixedcase")
    assert len(resp.get_json()["results"]) == 1


def test_search_top_20_cap(client, fake_ollama):
    bot_id = _create_bot(client)
    for i in range(25):  # 25 matching user messages (assistant replies don't match)
        client.post(f"/api/bots/{bot_id}/chat", json={"message": f"needle turn {i}"})
    resp = client.get("/api/search?q=needle")
    assert len(resp.get_json()["results"]) == 20


def test_search_beyond_conversation_window(client, fake_ollama):
    """The JSONL log keeps full history even though only 20 messages are
    retained in the bot's conversation window."""
    bot_id = _create_bot(client)
    client.post(f"/api/bots/{bot_id}/chat", json={"message": "ancient paleozoic message"})
    for i in range(12):  # push the first message out of the 20-message window
        client.post(f"/api/bots/{bot_id}/chat", json={"message": f"filler {i}"})
    resp = client.get(f"/api/bots/{bot_id}")
    assert len(resp.get_json()["conversation_history"]) == 20
    resp = client.get("/api/search?q=paleozoic")
    assert len(resp.get_json()["results"]) == 1


def test_search_legacy_alias(client, fake_ollama):
    bot_id = _create_bot(client)
    client.post(f"/api/bots/{bot_id}/chat", json={"message": "alias needle"})
    resp = client.get("/api/bots/search?q=alias")
    assert resp.status_code == 200
    assert len(resp.get_json()["results"]) == 1


def test_search_falls_back_to_conversation_window(client, fake_ollama):
    """Bots without a JSONL log (pre-1.2) are still searchable."""
    bot_id = _create_bot(client)
    client.post(f"/api/bots/{bot_id}/chat", json={"message": "window-only needle"})
    (BOTS_DIR / bot_id / "history.jsonl").unlink()
    resp = client.get("/api/search?q=window-only")
    assert len(resp.get_json()["results"]) == 1


def test_bot_history_endpoint(client, fake_ollama):
    bot_id = _create_bot(client)
    client.post(f"/api/bots/{bot_id}/chat", json={"message": "full history please"})
    resp = client.get(f"/api/bots/{bot_id}/history")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["count"] == 2
    assert body["history"][0]["content"] == "full history please"


def test_bot_history_endpoint_404(client):
    assert client.get("/api/bots/nope/history").status_code == 404


def test_delete_bot_removes_history_log(client, fake_ollama):
    bot_id = _create_bot(client)
    client.post(f"/api/bots/{bot_id}/chat", json={"message": "doomed message"})
    assert (BOTS_DIR / bot_id / "history.jsonl").exists()
    resp = client.delete(f"/api/bots/{bot_id}")
    assert resp.status_code == 200
    assert not (BOTS_DIR / bot_id).exists()
