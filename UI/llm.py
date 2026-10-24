"""LLM router — local Ollama (priority #1) with remote cloud LLM fallback."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

try:
    import ollama  # type: ignore
except ImportError:  # pragma: no cover - ollama is a hard dependency
    ollama = None  # type: ignore

from .config import DEFAULT_SETTINGS, load_settings


class LLMRouter:
    """Routes LLM calls: local ollama first, remote cloud LLM as fallback.

    The ``provider`` setting selects the default backend:
      - "local"  -> Ollama (must be running)
      - "remote" -> OpenAI-compatible endpoint (OpenRouter, Groq, etc.)
    Each chat call can override the provider per-request.
    """

    def __init__(self) -> None:
        self._settings = load_settings()

    def refresh_settings(self) -> None:
        self._settings = load_settings()

    @property
    def settings(self) -> Dict[str, Any]:
        return self._settings

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
        if ollama is None:
            return {
                "message": {
                    "role": "assistant",
                    "content": "Ollama Python package is not installed.",
                    "tool_calls": [],
                }
            }
        model = model or self._settings["llm"]["local_model"]
        try:
            response = ollama.chat(model=model, messages=messages, tools=tools)
            return self._normalize_ollama(response)
        except Exception as e:  # noqa: BLE001
            return {
                "message": {
                    "role": "assistant",
                    "content": f"Local LLM error: {e}",
                    "tool_calls": [],
                }
            }

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
        api_key = api_key or llm_cfg.get("remote_api_key", "")
        model = model or llm_cfg.get("remote_model", "gpt-4o-mini")

        if not base_url:
            return {
                "message": {
                    "role": "assistant",
                    "content": "Remote LLM not configured (no base_url).",
                    "tool_calls": [],
                }
            }

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
            return {
                "message": {
                    "role": "assistant",
                    "content": f"Remote LLM error: {e}",
                    "tool_calls": [],
                }
            }

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
        """
        provider = provider or self._settings["llm"]["provider"]

        if provider == "local":
            result = self.query_local(messages, tools=tools, model=model)
            if "error" in (result.get("message", {}).get("content", "") or ""):
                remote_result = self.query_remote(messages, model=model)
                if "error" not in (remote_result.get("message", {}).get("content", "") or ""):
                    return remote_result
            return result

        if provider == "remote":
            result = self.query_remote(messages, model=model)
            if "error" in (result.get("message", {}).get("content", "") or ""):
                local_result = self.query_local(messages, tools=tools, model=model)
                if "error" not in (local_result.get("message", {}).get("content", "") or ""):
                    return local_result
            return result

        result = self.query_local(messages, tools=tools, model=model)
        if "error" in (result.get("message", {}).get("content", "") or ""):
            return self.query_remote(messages, model=model)
        return result