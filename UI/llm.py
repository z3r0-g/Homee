"""LLM router — local Ollama (priority #1) with remote cloud LLM fallback.

Ollama is the default backend: a fresh install works with no API keys once
Ollama is running and the configured model is pulled (see ``ollama_status``
and the Settings → Models UI, or ``ollama pull <model>``).

Failure results carry a top-level ``"error"`` key in addition to the
human-readable message text, so callers can tell a real failure from a
reply that merely mentions the word "error". Settings are reloaded on
every chat/status call so a change saved in the Settings UI takes effect
without restarting the service.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

import requests

try:
    import ollama  # type: ignore
except ImportError:  # pragma: no cover - ollama is a hard dependency
    ollama = None  # type: ignore

from .config import DEFAULT_SETTINGS, OLLAMA_HOST, load_settings


def _failure(content: str) -> Dict[str, Any]:
    """A normalized failure result (same shape as a success, plus "error")."""
    return {
        "message": {
            "role": "assistant",
            "content": content,
            "tool_calls": [],
        },
        "error": content,
    }


def _local_error_message(exc: Exception, model: str) -> str:
    """Turn a raw Ollama failure into an actionable message."""
    text = str(exc).lower()
    if "not found" in text and "model" in text:
        return (
            f"Model '{model}' is not installed in Ollama. "
            f"Pull it from Settings → Models, or run: ollama pull {model}"
        )
    if any(marker in text for marker in (
        "connection", "connect", "refused", "unreachable",
        "failed to establish", "max retries",
    )):
        return (
            f"Ollama is not reachable at {OLLAMA_HOST}. "
            "Start it with `ollama serve` (or `systemctl start ollama`), "
            "then try again."
        )
    return f"Local LLM error: {exc}"


def _model_name_matches(configured: str, installed: str) -> bool:
    """Compare Ollama model names, treating a missing tag as ":latest".

    This matters because Ollama tags are exact: a configured "qwen2.5"
    (i.e. qwen2.5:latest) is NOT satisfied by an installed "qwen2.5:7b",
    and silently treating them as equal is how fresh installs broke.
    """
    def _norm(name: str) -> str:
        name = name.strip()
        return name if ":" in name.split("/")[-1] else f"{name}:latest"

    return _norm(configured) == _norm(installed)


class LLMRouter:
    """Routes LLM calls: local ollama first, remote cloud LLM as fallback.

    The ``provider`` setting selects the default backend:
      - "local"  -> Ollama (must be running, model must be installed)
      - "remote" -> OpenAI-compatible endpoint (OpenRouter, Groq, etc.)
    Each chat call can override the provider per-request.
    """

    def __init__(self, client: Any = None) -> None:
        self._settings = load_settings()
        # Injectable for tests; otherwise built lazily so importing this
        # module never requires the ollama package or a running server.
        self._client = client
        self._pull_lock = threading.Lock()
        self._pull_job: Dict[str, Any] = {
            "state": "idle", "model": "", "detail": "",
        }

    def refresh_settings(self) -> None:
        self._settings = load_settings()

    @property
    def settings(self) -> Dict[str, Any]:
        return self._settings

    # ════════════════════════════════════════════════════════════════
    # Ollama client
    # ════════════════════════════════════════════════════════════════

    @property
    def client(self) -> Any:
        """An ollama client honouring the configured OLLAMA_HOST, or None."""
        if self._client is None:
            if ollama is None:
                return None
            # NOTE: the module-level ollama.chat() helpers ignore OLLAMA_HOST;
            # a Client is required for a custom host to take effect.
            self._client = ollama.Client(host=OLLAMA_HOST)
        return self._client

    # ════════════════════════════════════════════════════════════════
    # Ollama status + model pulls (Settings → Models UI)
    # ════════════════════════════════════════════════════════════════

    def ollama_status(self) -> Dict[str, Any]:
        """Report Ollama reachability, installed models, and model readiness.

        Returns a JSON-serializable dict:
          running, host, models, configured_model,
          configured_model_installed, error
        """
        self.refresh_settings()
        configured = self._settings["llm"]["local_model"]
        status: Dict[str, Any] = {
            "running": False,
            "host": OLLAMA_HOST,
            "models": [],
            "configured_model": configured,
            "configured_model_installed": False,
            "error": "",
        }
        client = self.client
        if client is None:
            status["error"] = (
                "The server is missing the ollama Python package. "
                "Install it with: pip install ollama"
            )
            return status
        try:
            listed = client.list()
        except Exception as e:  # noqa: BLE001
            status["error"] = _local_error_message(e, configured)
            return status
        raw = listed.get("models", []) if isinstance(listed, dict) \
            else getattr(listed, "models", [])
        models = []
        for entry in raw or []:
            name = entry.get("name") if isinstance(entry, dict) \
                else getattr(entry, "model", "")
            if name:
                models.append(name)
        status["running"] = True
        status["models"] = sorted(models)
        status["configured_model_installed"] = any(
            _model_name_matches(configured, name) for name in models
        )
        return status

    def pull_job(self) -> Dict[str, Any]:
        """Current model-pull job state (idle/running/done/error)."""
        with self._pull_lock:
            return dict(self._pull_job)

    def start_pull(self, model: str) -> Dict[str, Any]:
        """Start pulling a model in the background. Returns the job dict.

        If a pull is already running, the running job is returned unchanged
        (callers map that to HTTP 409). The pull runs on a daemon thread
        because a multi-GB model download outlasts any HTTP request budget.
        """
        model = (model or "").strip()
        if not model:
            return {"state": "error", "model": "",
                    "detail": "No model name given."}
        with self._pull_lock:
            if self._pull_job["state"] == "running":
                return dict(self._pull_job)
            self._pull_job = {"state": "running", "model": model,
                              "detail": "Pulling…"}
        thread = threading.Thread(target=self._run_pull, args=(model,),
                                  daemon=True)
        thread.start()
        return self.pull_job()

    def _run_pull(self, model: str) -> None:
        try:
            client = self.client
            if client is None:
                raise RuntimeError("ollama Python package is not installed")
            try:
                for _chunk in client.pull(model, stream=True):
                    pass
            except TypeError:
                # Clients that do not accept stream= (e.g. test doubles).
                client.pull(model)
            with self._pull_lock:
                self._pull_job = {"state": "done", "model": model,
                                  "detail": f"Model '{model}' is installed."}
        except Exception as e:  # noqa: BLE001
            with self._pull_lock:
                self._pull_job = {"state": "error", "model": model,
                                  "detail": f"Pull failed: {e}"}

    # ════════════════════════════════════════════════════════════════
    # Local (Ollama)
    # ════════════════════════════════════════════════════════════════

    def query_local(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query the local Ollama server. Returns a normalized dict."""
        client = self.client
        if client is None:
            return _failure(
                "Ollama Python package is not installed. "
                "Install it with: pip install ollama"
            )
        model = model or self._settings["llm"]["local_model"]
        try:
            response = client.chat(model=model, messages=messages, tools=tools)
            return self._normalize_ollama(response)
        except Exception as e:  # noqa: BLE001
            return _failure(_local_error_message(e, model))

    @staticmethod
    def _normalize_ollama(response: Any) -> Dict[str, Any]:
        msg = getattr(response, "message", None)
        if msg is None:
            return {"message": {"role": "assistant", "content": "", "tool_calls": []}}
        tool_calls = []
        for tc in getattr(msg, "tool_calls", []) or []:
            tool_calls.append(
                {
                    "function": {
                        "name": getattr(tc.function, "name", ""),
                        "arguments": getattr(tc.function, "arguments", {}) or {},
                    }
                }
            )
        return {
            "message": {
                "role": getattr(msg, "role", "assistant"),
                "content": getattr(msg, "content", "") or "",
                "tool_calls": tool_calls,
            }
        }

    # ════════════════════════════════════════════════════════════════
    # Remote (OpenAI-compatible cloud LLM)
    # ════════════════════════════════════════════════════════════════

    def query_remote(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query a remote OpenAI-compatible LLM endpoint."""
        llm_cfg = self._settings["llm"]
        base_url = base_url or llm_cfg.get("remote_base_url", "")
        api_key = api_key if api_key is not None else llm_cfg.get("remote_api_key", "")
        model = model or llm_cfg.get("remote_model", "gpt-4o-mini")

        if not base_url:
            return _failure(
                "Remote LLM not configured (no base_url). "
                "Set one in Settings → Remote Cloud LLM, or switch the "
                "provider back to Local Ollama."
            )

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
        }

        try:
            resp = requests.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            return {
                "message": {
                    "role": msg.get("role", "assistant"),
                    "content": msg.get("content", "") or "",
                    "tool_calls": [],
                }
            }
        except Exception as e:  # noqa: BLE001
            return _failure(f"Remote LLM error: {e}")

    # ════════════════════════════════════════════════════════════════
    # Unified chat with routing
    # ════════════════════════════════════════════════════════════════

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Chat with automatic provider fallback.

        Order: requested provider -> settings provider -> local -> remote.
        A fallback only happens when the other backend is actually
        configured; an unconfigured remote no longer replaces a clear
        local error with a second confusing one.
        """
        self.refresh_settings()
        provider = provider or self._settings["llm"]["provider"]
        remote_configured = bool(self._settings["llm"].get("remote_base_url"))

        if provider == "local":
            result = self.query_local(messages, tools=tools, model=model)
            if result.get("error") and remote_configured:
                remote_result = self.query_remote(messages, model=model)
                if not remote_result.get("error"):
                    return remote_result
            return result

        if provider == "remote":
            result = self.query_remote(messages, model=model)
            if result.get("error"):
                local_result = self.query_local(messages, tools=tools, model=model)
                if not local_result.get("error"):
                    return local_result
            return result

        result = self.query_local(messages, tools=tools, model=model)
        if result.get("error") and remote_configured:
            return self.query_remote(messages, model=model)
        return result
