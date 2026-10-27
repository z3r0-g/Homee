"""Tests for the ollama-first LLM router (UI/llm.py).

All Ollama behavior is injected via a fake client; no test touches the
network or a real Ollama server.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from UI.llm import LLMRouter, _model_name_matches


class FakeClient:
    """Minimal stand-in for ollama.Client."""

    def __init__(self, models=(), chat_text="hello", chat_error=None,
                 list_error=None, pull_block=None):
        self.models = list(models)
        self.chat_text = chat_text
        self.chat_error = chat_error
        self.list_error = list_error
        self.pull_block = pull_block
        self.pulled = []
        self.last_chat_model = None

    def list(self):
        if self.list_error is not None:
            raise self.list_error
        return {"models": [{"name": name} for name in self.models]}

    def chat(self, model, messages, tools=None):
        self.last_chat_model = model
        if self.chat_error is not None:
            raise self.chat_error
        return SimpleNamespace(
            message=SimpleNamespace(role="assistant",
                                    content=self.chat_text,
                                    tool_calls=[]))

    def pull(self, model, stream=False):
        self.pulled.append(model)
        if self.pull_block is not None:
            self.pull_block.wait(timeout=10)
        if stream:
            return iter(())
        return None


@pytest.fixture
def _tmp_settings(tmp_path, monkeypatch):
    """Point settings at a scratch file so defaults apply."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr("UI.config.SETTINGS_FILE", path)
    return path


def test_default_local_model_matches_installer(_tmp_settings):
    # Both install.sh and the router pick the default by host RAM
    # (qwen2.5:3b under 12 GB, qwen2.5:7b above); the router default must
    # equal that rule, otherwise a fresh install fails first chat with
    # "model not found".
    from UI import model_catalog
    router = LLMRouter(client=FakeClient())
    assert router.settings["llm"]["local_model"] == model_catalog.default_model(
        model_catalog.host_total_ram_gb())
    assert router.settings["llm"]["provider"] == "local"


def test_status_offline(_tmp_settings):
    router = LLMRouter(client=FakeClient(
        list_error=ConnectionError("Connection refused")))
    status = router.ollama_status()
    assert status["running"] is False
    assert status["models"] == []
    assert status["configured_model_installed"] is False
    assert "not reachable" in status["error"]


def test_status_reports_installed_configured_model(_tmp_settings):
    # Pin the configured model: this test is about status reporting,
    # not about which default the host's RAM selects.
    _tmp_settings.write_text('{"llm": {"local_model": "qwen2.5:7b"}}')
    router = LLMRouter(client=FakeClient(models=["qwen2.5:7b", "llama3.1:8b"]))
    status = router.ollama_status()
    assert status["running"] is True
    assert status["models"] == ["llama3.1:8b", "qwen2.5:7b"]
    assert status["configured_model"] == "qwen2.5:7b"
    assert status["configured_model_installed"] is True


def test_model_name_matching_treats_missing_tag_as_latest():
    assert _model_name_matches("qwen2.5", "qwen2.5:latest")
    assert _model_name_matches("qwen2.5:latest", "qwen2.5")
    assert not _model_name_matches("qwen2.5", "qwen2.5:7b")
    assert not _model_name_matches("qwen2.5:7b", "qwen2.5:latest")


def test_query_local_model_not_found_is_actionable(_tmp_settings):
    # Pin the configured model so the hint names the model in the error.
    _tmp_settings.write_text('{"llm": {"local_model": "qwen2.5:7b"}}')
    router = LLMRouter(client=FakeClient(
        chat_error=Exception("model 'qwen2.5:7b' not found, try pulling it")))
    result = router.query_local([{"role": "user", "content": "hi"}])
    assert "error" in result
    assert "ollama pull qwen2.5:7b" in result["message"]["content"]


def test_reply_mentioning_error_is_not_a_failure(_tmp_settings):
    # Regression: the old router treated any reply containing the substring
    # "error" as a failure and fell back to the other backend.
    router = LLMRouter(client=FakeClient(
        chat_text="There is no error here, all good."))
    result = router.chat([{"role": "user", "content": "hi"}])
    assert "error" not in result
    assert result["message"]["content"] == "There is no error here, all good."


def test_chat_does_not_fall_back_to_unconfigured_remote(_tmp_settings):
    router = LLMRouter(client=FakeClient(
        chat_error=Exception("Connection refused")))
    calls = []
    router.query_remote = lambda *a, **k: calls.append(1) or {
        "message": {"role": "assistant", "content": "remote", "tool_calls": []}}
    result = router.chat([{"role": "user", "content": "hi"}])
    assert calls == []
    assert "not reachable" in result["message"]["content"]


def test_chat_falls_back_to_configured_remote(_tmp_settings):
    # Remote fallback requires local_cloud mode (the mode switcher governs
    # fallback; local_local must NOT fall back to remote even if configured).
    import json
    _tmp_settings.write_text(json.dumps(
        {"llm": {"mode": "local_cloud",
                 "remote_base_url": "https://example.invalid/v1"}}))
    router = LLMRouter(client=FakeClient(
        chat_error=Exception("Connection refused")))
    router.query_remote = lambda *a, **k: {
        "message": {"role": "assistant", "content": "remote ok",
                    "tool_calls": []}}
    result = router.chat([{"role": "user", "content": "hi"}])
    assert result["message"]["content"] == "remote ok"


def test_pull_job_lifecycle(_tmp_settings):
    import threading
    # Hold the pull thread so the "running" state is observable: a fake
    # pull otherwise finishes before start_pull() even returns.
    block = threading.Event()
    router = LLMRouter(client=FakeClient(pull_block=block))
    job = router.start_pull("qwen2.5:7b")
    assert job["state"] == "running"
    block.set()
    deadline = time.time() + 5
    while time.time() < deadline:
        job = router.pull_job()
        if job["state"] in ("done", "error"):
            break
        time.sleep(0.02)
    assert job["state"] == "done"
    assert router._client.pulled == ["qwen2.5:7b"]


def test_pull_empty_model_is_an_error(_tmp_settings):
    router = LLMRouter(client=FakeClient())
    job = router.start_pull("   ")
    assert job["state"] == "error"


def test_chat_local_local_does_not_fall_back_to_remote(_tmp_settings):
    import json
    _tmp_settings.write_text(json.dumps(
        {"llm": {"mode": "local_local",
                 "remote_base_url": "https://example.invalid/v1"}}))
    router = LLMRouter(client=FakeClient(
        chat_error=Exception("Connection refused")))
    calls = []
    router.query_remote = lambda *a, **k: calls.append(1) or {
        "message": {"role": "assistant", "content": "remote", "tool_calls": []}}
    result = router.chat([{"role": "user", "content": "hi"}])
    assert calls == []
    assert "not reachable" in result["message"]["content"]


def test_chat_local_local_falls_back_to_secondary_model(_tmp_settings):
    import json
    _tmp_settings.write_text(json.dumps(
        {"llm": {"mode": "local_local", "secondary_model": "llama3.1:8b"}}))
    client = FakeClient(chat_error=Exception("model 'qwen2.5:7b' not found"))

    def chat_then_ok(model, messages, tools=None):
        if model == "llama3.1:8b":
            from types import SimpleNamespace
            return SimpleNamespace(
                message=SimpleNamespace(role="assistant",
                                        content="secondary ok",
                                        tool_calls=[]))
        raise Exception("model 'qwen2.5:7b' not found")

    client.chat = chat_then_ok
    router = LLMRouter(client=client)
    result = router.chat([{"role": "user", "content": "hi"}])
    assert result["message"]["content"] == "secondary ok"


def test_chat_local_remote_local_falls_back_to_secondary_host(_tmp_settings):
    import json
    _tmp_settings.write_text(json.dumps(
        {"llm": {"mode": "local_remote_local",
                 "secondary_base_url": "http://otherhost:11434"}}))
    seen_hosts = []

    def factory(host):
        seen_hosts.append(host)
        if host == "http://otherhost:11434":
            return FakeClient(chat_text="secondary host ok")
        return FakeClient(chat_error=Exception("Connection refused"))

    router = LLMRouter(client=FakeClient(chat_error=Exception("Connection refused")),
                       client_factory=factory)
    result = router.chat([{"role": "user", "content": "hi"}])
    assert result["message"]["content"] == "secondary host ok"
    assert "http://otherhost:11434" in seen_hosts


# ── Model delete + catalog ────────────────────────────────────────────

class DeleteRecorder:
    """Fake ollama client recording delete() calls."""

    def __init__(self, fail=False):
        self.deleted = []
        self.fail = fail

    def delete(self, model):
        if self.fail:
            raise Exception("model not found")
        self.deleted.append(model)


def test_delete_model_calls_client():
    router = LLMRouter(client=DeleteRecorder())
    result = router.delete_model("qwen2.5:7b")
    assert result["success"] is True
    assert router._client.deleted == ["qwen2.5:7b"]


def test_delete_model_failure_is_a_failure_dict():
    router = LLMRouter(client=DeleteRecorder(fail=True))
    result = router.delete_model("nope:1b")
    assert "error" in result


def test_catalog_filters_by_host_ram(monkeypatch):
    from UI import model_catalog
    monkeypatch.setattr(model_catalog, "host_ram_gb", lambda: 6.0)
    cat = model_catalog.catalog()
    assert cat["size_cap_gb"] == 6
    assert cat["ollama_search_url"] == "https://ollama.com/search?c=local&s=6"
    names = [m["name"] for m in cat["models"]]
    assert "qwen2.5:7b" in names
    assert "gemma3:27b" not in names
    assert "llama3.1:70b" not in names
    assert cat["hidden_count"] == len(model_catalog.MODELS) - len(names)


def test_catalog_filter_by_capability():
    from UI import model_catalog
    vision = [m for m in model_catalog.MODELS if "vision" in m["capabilities"]]
    assert vision and all(m["size_gb"] for m in vision)
    assert "llava:7b" in [m["name"] for m in vision]


def test_default_model_by_ram():
    from UI import model_catalog
    assert model_catalog.default_model(8.0) == "qwen2.5:3b"
    assert model_catalog.default_model(11.9) == "qwen2.5:3b"
    assert model_catalog.default_model(12.0) == "qwen2.5:7b"
    assert model_catalog.default_model(16.0) == "qwen2.5:7b"
    assert model_catalog.default_model(None) == "qwen2.5:7b"
