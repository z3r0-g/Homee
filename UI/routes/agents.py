"""Agent registry routes — list available Agent personalities."""

from __future__ import annotations

from flask import Blueprint, jsonify

from Agents.registry import agent_registry

agents_bp = Blueprint("agents", __name__)


@agents_bp.route("/api/agents", methods=["GET"])
def list_agents():
    return jsonify({"agents": agent_registry.list_agents()})


@agents_bp.route("/api/agents/available-personalities", methods=["GET"])
def available_personalities():
    """Combined list of saved personalities plus discovered agents.

    Lets the New-Bot form offer *every* selectable personality in one place,
    including locally-discovered agents like the Burundy Weather Agent that are
    not stored in the personalities repository.
    """
    from ..models import personalities_repo

    personalities_repo.load()
    items = [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "type": "personality",
        }
        for p in personalities_repo.all()
    ]
    for agent in agent_registry.list_agents():
        items.append(
            {
                "id": agent["name"],
                "name": agent["name"],
                "description": agent.get("description", ""),
                "type": "agent",
            }
        )
    return jsonify({"personalities": items})


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