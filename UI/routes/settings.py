"""Settings routes — LLM provider, scheduler, MCP service URL."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from ..config import save_settings, load_settings, DEFAULT_SETTINGS
from ..llm import LLMRouter
from ..models import mcps_repo

settings_bp = Blueprint("settings", __name__)

# Mode display names and descriptions
MODE_CONFIGS = {
    "local_local": {
        "name": "Local + Local",
        "description": "Use local Ollama model(s). Only 1 model required but can support 2 in config for redundancy or specialized tasks.",
        "fields": ["local_model", "secondary_model"],
        "requires_auth": False,
    },
    "local_cloud": {
        "name": "Local + Cloud",
        "description": "Local Ollama model plus a cloud LLM. The cloud fallback uses the secondary endpoint when set, otherwise the remote settings below.",
        "fields": ["local_model", "secondary_base_url", "secondary_api_key", "secondary_model"],
        "requires_auth": True,
    },
    "local_remote_local": {
        "name": "Local + Remote Local",
        "description": "Route complex asks to Ollama on another local host. Secondary base URL points to a remote Ollama instance.",
        "fields": ["local_model", "secondary_base_url"],
        "requires_auth": False,
    },
}

# Module-level router (same pattern as bots.py); tests monkeypatch this.
llm_router = LLMRouter()


@settings_bp.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())


@settings_bp.route("/api/settings", methods=["POST"])
def save_settings_endpoint():
    data = request.get_json(silent=True) or {}
    # Merge over CURRENT settings (not defaults): merging over defaults
    # reset every field the form does not send (mode, agents.git_url, ...)
    # on every save. load_settings() already deep-merges over defaults.
    merged = load_settings()
    def _deep_merge(base, override):
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                _deep_merge(base[k], v)
            else:
                base[k] = v
    _deep_merge(merged, data)
    save_settings(merged)
    return jsonify({"success": True, "settings": merged})


@settings_bp.route("/api/mcp/list", methods=["GET"])
def mcp_list():
    """Get all MCP services for the marketplace."""
    mcps = mcps_repo.all()
    return jsonify({"mcps": mcps})


@settings_bp.route("/api/mcp/import/<mcp_id>", methods=["POST"])
def mcp_import(mcp_id):
    """Import MCP from remote source."""
    import json
    from ..config import MCP_SERVICE_URL
    import requests as _req

    url = f"{MCP_SERVICE_URL}/api/mcp/import/{mcp_id}"
    try:
        resp = _req.post(url, timeout=30)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@settings_bp.route("/api/mcp/disable/<mcp_id>", methods=["POST"])
def mcp_disable(mcp_id):
    """Disable MCP."""
    import json
    from ..config import MCP_SERVICE_URL
    import requests as _req

    url = f"{MCP_SERVICE_URL}/api/mcp/disable/{mcp_id}"
    try:
        resp = _req.post(url, timeout=30)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@settings_bp.route("/api/env/disable/<var_key>", methods=["POST"])
def env_disable(var_key):
    """Disable an environment variable."""
    import json
    from ..config import load_settings, save_settings

    settings = load_settings()
    env_vars = settings.get("env_vars", {})

    if var_key in env_vars:
        del env_vars[var_key]
        settings["env_vars"] = env_vars
        save_settings(settings)
        return jsonify({"success": True, "var_key": var_key})

    return jsonify({"error": "Variable not found"}), 404


@settings_bp.route("/api/env/vars", methods=["GET"])
def env_vars():
    """Get environment variables with optional prefix filter."""
    from ..config import load_settings

    settings = load_settings()
    prefix = request.args.get("prefix", "")

    # Check for AGENT_ env vars in the settings or environment
    vars_dict = settings.get("env_vars", {}) if isinstance(settings.get("env_vars"), dict) else {}

    if prefix:
        filtered = {k: v for k, v in vars_dict.items() if k.startswith(prefix)}
    else:
        filtered = vars_dict

    return jsonify({"vars": filtered})


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


@settings_bp.route("/api/settings/modes", methods=["GET"])
def get_modes():
    """Return mode configurations for the UI."""
    return jsonify({
        "modes": MODE_CONFIGS,
        "current_mode": load_settings().get("llm", {}).get("mode", "local_local"),
    })


@settings_bp.route("/api/settings/modes", methods=["POST"])
def set_mode():
    """Set the active LLM mode."""
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "local_local")
    if mode not in MODE_CONFIGS:
        return jsonify({"error": f"Unknown mode: {mode}"}), 400
    settings = load_settings()
    settings["llm"]["mode"] = mode
    # Validate mode-specific requirements
    if mode == "local_cloud":
        # Ensure secondary cloud config is present
        if not settings["llm"].get("secondary_base_url"):
            settings["llm"]["secondary_base_url"] = ""
        if not settings["llm"].get("secondary_api_key"):
            settings["llm"]["secondary_api_key"] = ""
    save_settings(settings)
    return jsonify({"success": True, "mode": mode, "settings": settings})


@settings_bp.route("/api/mcps", methods=["GET"])
def get_mcps():
    """Get all MCP services."""
    mcps = mcps_repo.all()
    return jsonify({"mcps": mcps})
