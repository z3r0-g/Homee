"""Settings routes — LLM provider, scheduler, MCP service URL."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..config import save_settings, load_settings, DEFAULT_SETTINGS

settings_bp = Blueprint("settings", __name__)


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