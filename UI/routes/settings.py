"""Settings routes — LLM provider, scheduler, MCP service URL."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..config import save_settings, load_settings, DEFAULT_SETTINGS
from ..llm import LLMRouter

settings_bp = Blueprint("settings", __name__)

# Module-level router (same pattern as bots.py); tests monkeypatch this.
llm_router = LLMRouter()


@settings_bp.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())


@settings_bp.route("/api/settings", methods=["POST"])
def save_settings_endpoint():
    data = request.get_json(silent=True) or {}
    # Merge with defaults to keep structure intact
    merged = dict(DEFAULT_SETTINGS)
    def _deep_merge(base, override):
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                _deep_merge(base[k], v)
            else:
                base[k] = v
    _deep_merge(merged, data)
    save_settings(merged)
    return jsonify({"success": True, "settings": merged})


@settings_bp.route("/api/llm/status", methods=["GET"])
def llm_status():
    """Ollama reachability + installed models + configured-model readiness."""
    return jsonify(llm_router.ollama_status())


@settings_bp.route("/api/llm/pull", methods=["POST"])
def llm_pull():
    """Start a background pull of a model. 202 + job, or 409 if busy."""
    data = request.get_json(silent=True) or {}
    current = llm_router.pull_job()
    if current["state"] == "running":
        return jsonify({"error": "A model pull is already running.",
                        "job": current}), 409
    model = (data.get("model") or "").strip() \
        or load_settings()["llm"]["local_model"]
    return jsonify({"job": llm_router.start_pull(model)}), 202


@settings_bp.route("/api/llm/pull", methods=["GET"])
def llm_pull_status():
    """Current model-pull job state (idle/running/done/error)."""
    return jsonify({"job": llm_router.pull_job()})