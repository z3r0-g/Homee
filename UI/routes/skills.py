"""Skill routes."""

from __future__ import annotations

import uuid
from flask import Blueprint, jsonify, request

from ..models import skills_repo

skills_bp = Blueprint("skills", __name__)


@skills_bp.route("/api/skills", methods=["GET"])
def list_skills():
    skills_repo.load()
    return jsonify({
        "skills": [p.to_dict() for p in skills_repo.all()],
    })


@skills_bp.route("/api/skills", methods=["POST"])
def create_skill():
    data = request.get_json(silent=True) or {}
    skill_id = str(uuid.uuid4())
    from ..models import Skill

    skill = Skill(
        id=skill_id,
        name=data.get("name", "New Skill"),
        description=data.get("description", ""),
        skills=data.get("skills", []),
        abilities=data.get("abilities", []),
        system_prompt=data.get("system_prompt", ""),
    )
    skills_repo.add(skill)
    return jsonify({"success": True, "skill": skill.to_dict()}), 201


@skills_bp.route("/api/skills/<skill_id>", methods=["GET"])
def get_skill(skill_id):
    skills_repo.load()
    p = skills_repo.get(skill_id)
    if not p:
        return jsonify({"error": "Skill not found"}), 404
    return jsonify(p.to_dict())


@skills_bp.route("/api/skills/<skill_id>", methods=["PUT"])
def update_skill(skill_id):
    skills_repo.load()
    data = request.get_json(silent=True) or {}
    p = skills_repo.get(skill_id)
    if not p:
        return jsonify({"error": "Skill not found"}), 404
    for k in ("name", "description", "skills", "abilities", "system_prompt"):
        if k in data:
            setattr(p, k, data[k])
    skills_repo.save()
    return jsonify({"success": True, "skill": p.to_dict()})


@skills_bp.route("/api/skills/<skill_id>", methods=["DELETE"])
def delete_skill(skill_id):
    skills_repo.load()
    if not skills_repo.delete(skill_id):
        return jsonify({"error": "Skill not found"}), 404
    return jsonify({"success": True})


# ── Skill plugins: discovery, sync, leaderboard ──


from Skills.registry import skill_registry



@skills_bp.route("/api/skills/import-git/<skill_id>", methods=["POST"])
def import_skill_git(skill_id):
    """Import skill configuration from remote git source."""
    import json
    from ..config import load_settings, save_settings

    settings = load_settings()
    skills = settings.get("skills", {})

    if skill_id not in skills:
        skills[skill_id] = {"active": True, "name": skill_id, "from_git": True}
    else:
        skills[skill_id]["from_git"] = True

    settings["skills"] = skills
    save_settings(settings)

    return jsonify({"success": True, "skill": skill_id, "from_git": True})


@skills_bp.route("/api/skills/toggle/<skill_id>", methods=["POST"])
def toggle_skill(skill_id):
    """Toggle skill active/inactive status."""
    import json
    from ..config import load_settings, save_settings

    settings = load_settings()
    skills = settings.get("skills", {})

    if skill_id in skills:
        skills[skill_id]["active"] = not skills[skill_id].get("active", True)
    else:
        # Absent from settings means default-enabled, so the first toggle
        # disables it (the old code created it as active: True — a no-op).
        skills[skill_id] = {"active": False, "name": skill_id}

    settings["skills"] = skills
    save_settings(settings)

    return jsonify({"success": True, "skill": skill_id, "active": skills[skill_id]["active"]})


@skills_bp.route("/api/skills/active", methods=["GET"])
def active_skills():
    """Skills for the skills tab: every discovered skill, local and
    remote, with its id and enabled state.

    Local skills are enabled by default; disabling one records
    ``active: false`` in settings (see toggle_agent). Previously this
    returned the bare registry rows — no id, no enabled flag — so the tab
    rendered "undefined" and its buttons could not address an skill.
    """
    from ..config import load_settings

    settings = load_settings()
    agents_cfg = settings.get("skills", {}) if isinstance(settings, dict) else {}
    skills = []
    for skill in skill_registry.list_skills():
        name = skill.get("name", "")
        skills.append({
            **skill,
            "id": name,
            "active": agents_cfg.get(name, {}).get("active", True),
        })
    return jsonify({"skills": skills})


@skills_bp.route("/api/skills/discovered", methods=["GET"])
def list_discovered_skills():
    return jsonify({"skills": skill_registry.list_skills()})


@skills_bp.route("/api/skills/available", methods=["GET"])
def available_skills():
    """Combined list of saved skills plus discovered skills.

    Lets the New-Bot form offer *every* selectable skill in one place,
    including locally-discovered skills like the Burgundy Weather Skill that are
    not stored in the skills repository.
    """
    from ..models import skills_repo

    skills_repo.load()
    items = [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "type": "skill",
            "source": "saved",
        }
        for p in skills_repo.all()
    ]
    for skill in skill_registry.list_skills():
        items.append(
            {
                "id": skill["name"],
                "name": skill["name"],
                "description": skill.get("description", ""),
                "type": "skill",
                "source": "discovered",
            }
        )
    return jsonify({"skills": items})


@skills_bp.route("/api/skills/sources", methods=["GET"])
def list_sources():
    from Skills.registry import load_sources
    return jsonify(load_sources())


@skills_bp.route("/api/skills/refresh", methods=["POST"])
def refresh_skills():
    """Re-discover Skills, honouring the skills.git_url UI setting.

    Also imports ``*.md`` skill files from the cloned repos (see
    CONTRIBUTE.md): a repo may ship skill MD next to its skill
    ``.py`` files, and syncing pulls those into the skills store.
    """
    from ..config import load_settings
    from Skills.registry import skill_registry

    settings = load_settings()
    git_url = (settings.get("skills") or {}).get("git_url") or None
    skill_registry.configure_git_url(git_url)
    skill_registry.discover(force=True)
    imported = _import_remote_skills()
    return jsonify({"success": True, "skills": skill_registry.list_skills(),
                    "skills_imported": imported})


def _import_remote_skills() -> int:
    """Import ``*.md`` skill files from cloned skill repos.

    Each file is one skill; the id defaults to the file stem.
    Re-syncing upserts by id, so updating a repo and syncing again
    picks up edits. Repos ship ``.md`` only (no legacy JSON).
    """
    from ..models import Skill, skills_repo
    from ..skill_md import parse_skill_md
    from Skills.registry import REMOTE_DIR

    skills_repo.load()
    count = 0
    if not REMOTE_DIR.exists():
        return 0
    for path in sorted(REMOTE_DIR.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            data = parse_skill_md(text)
        except ValueError:
            continue
        if not data.get("name"):
            continue
        skill_id = path.stem
        existing = skills_repo.get(skill_id)
        if existing:
            for k in ("name", "description", "skills", "abilities", "system_prompt"):
                if k in data:
                    setattr(existing, k, data[k])
        else:
            skills_repo.add(Skill(
                id=skill_id,
                name=data.get("name", ""),
                description=data.get("description", ""),
                skills=data.get("skills", []),
                abilities=data.get("abilities", []),
                system_prompt=data.get("system_prompt", ""),
            ))
        count += 1
    skills_repo.save()
    return count


@skills_bp.route("/api/skills/leaderboard", methods=["GET"])
def skills_leaderboard():
    """Top Skills from the MCP Market leaderboard snapshot.
    Discovery only: entries carry no repo URL, so cards link out
    to the leaderboard instead of importing."""
    from ..leaderboard import load_leaderboard
    snap = load_leaderboard("skills")
    return jsonify({
        "skills": snap.get("entries", []),
        "snapshot_date": snap.get("snapshot_date", ""),
        "source_url": snap.get("source_url", ""),
    })
