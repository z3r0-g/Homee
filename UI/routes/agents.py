"""Agent registry routes — list available Agent personalities."""

from __future__ import annotations

from flask import Blueprint, jsonify

from Agents.registry import agent_registry

agents_bp = Blueprint("agents", __name__)


@agents_bp.route("/api/agents", methods=["GET"])
def list_agents():
    return jsonify({"agents": agent_registry.list_agents()})


@agents_bp.route("/api/agents/sources", methods=["GET"])
def list_sources():
    from Agents.registry import load_sources
    return jsonify(load_sources())


@agents_bp.route("/api/agents/refresh", methods=["POST"])
def refresh_agents():
    """Re-discover Agents, honouring the agents.git_url UI setting."""
    from ..config import load_settings
    from Agents.registry import agent_registry

    settings = load_settings()
    git_url = (settings.get("agents") or {}).get("git_url") or None
    agent_registry.configure_git_url(git_url)
    agent_registry.discover(force=True)
    return jsonify({"success": True, "agents": agent_registry.list_agents()})