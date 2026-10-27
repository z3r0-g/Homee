"""Agent registry routes — list available Agent personalities."""

from __future__ import annotations

from flask import Blueprint, jsonify

from Agents.registry import agent_registry

agents_bp = Blueprint("agents", __name__)


@agents_bp.route("/api/agents/import-git/<agent_id>", methods=["POST"])
def import_agent_git(agent_id):
    """Import agent configuration from remote git source."""
    import json
    from ..config import load_settings, save_settings

    settings = load_settings()
    agents = settings.get("agents", {})

    if agent_id not in agents:
        agents[agent_id] = {"active": True, "name": agent_id, "from_git": True}
    else:
        agents[agent_id]["from_git"] = True

    settings["agents"] = agents
    save_settings(settings)

    return jsonify({"success": True, "agent": agent_id, "from_git": True})


@agents_bp.route("/api/agents/toggle/<agent_id>", methods=["POST"])
def toggle_agent(agent_id):
    """Toggle agent active/inactive status."""
    import json
    from ..config import load_settings, save_settings

    settings = load_settings()
    agents = settings.get("agents", {})

    if agent_id in agents:
        agents[agent_id]["active"] = not agents[agent_id].get("active", True)
    else:
        agents[agent_id] = {"active": True, "name": agent_id}

    settings["agents"] = agents
    save_settings(settings)

    return jsonify({"success": True, "agent": agent_id, "active": agents[agent_id]["active"]})


@agents_bp.route("/api/agents/active", methods=["GET"])
def active_agents():
    """Get active/available agents for the personalities modal."""
    from ..models import personalities_repo

    personalities_repo.load()
    # Return active agents from the registry
    agents = agent_registry.list_agents()
    return jsonify({"agents": agents})


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