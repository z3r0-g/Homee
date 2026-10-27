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
        # Absent from settings means default-enabled, so the first toggle
        # disables it (the old code created it as active: True — a no-op).
        agents[agent_id] = {"active": False, "name": agent_id}

    settings["agents"] = agents
    save_settings(settings)

    return jsonify({"success": True, "agent": agent_id, "active": agents[agent_id]["active"]})


@agents_bp.route("/api/agents/active", methods=["GET"])
def active_agents():
    """Agents for the personalities tab: every discovered agent, local and
    remote, with its id and enabled state.

    Local agents are enabled by default; disabling one records
    ``active: false`` in settings (see toggle_agent). Previously this
    returned the bare registry rows — no id, no enabled flag — so the tab
    rendered "undefined" and its buttons could not address an agent.
    """
    from ..config import load_settings

    settings = load_settings()
    agents_cfg = settings.get("agents", {}) if isinstance(settings, dict) else {}
    agents = []
    for agent in agent_registry.list_agents():
        name = agent.get("name", "")
        agents.append({
            **agent,
            "id": name,
            "active": agents_cfg.get(name, {}).get("active", True),
        })
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
    """Re-discover Agents, honouring the agents.git_url UI setting.

    Also imports ``*.json`` personality files from the cloned repos (see
    CONTRIBUTE.md): a repo may ship personality JSON next to its agent
    ``.py`` files, and syncing pulls those into the personalities store.
    """
    from ..config import load_settings
    from Agents.registry import agent_registry

    settings = load_settings()
    git_url = (settings.get("agents") or {}).get("git_url") or None
    agent_registry.configure_git_url(git_url)
    agent_registry.discover(force=True)
    imported = _import_remote_personalities()
    return jsonify({"success": True, "agents": agent_registry.list_agents(),
                    "personalities_imported": imported})


def _import_remote_personalities() -> int:
    """Import ``*.json`` personality files from cloned agent repos.

    Each file is one personality (or a list of them). Files need at least
    a ``name``; the id defaults to the file stem. Re-syncing upserts by
    id, so updating a repo and syncing again picks up edits.
    """
    import json

    from ..models import Personality, personalities_repo
    from Agents.registry import REMOTE_DIR

    personalities_repo.load()
    count = 0
    if not REMOTE_DIR.exists():
        return 0
    for path in sorted(REMOTE_DIR.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            item = dict(item)
            item.setdefault("id", path.stem)
            new = Personality.from_dict(item)
            current = personalities_repo.all()
            for i, existing in enumerate(current):
                if existing.id == new.id:
                    personalities_repo._personalities[i] = new
                    break
            else:
                personalities_repo._personalities.append(new)
            count += 1
    if count:
        personalities_repo.save()
    return count