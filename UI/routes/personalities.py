"""Personality routes."""

from __future__ import annotations

import uuid
from flask import Blueprint, jsonify, request

from ..models import personalities_repo

personalities_bp = Blueprint("personalities", __name__)


@personalities_bp.route("/api/personalities", methods=["GET"])
def list_personalities():
    personalities_repo.load()
    return jsonify({
        "personalities": [p.to_dict() for p in personalities_repo.all()],
    })


@personalities_bp.route("/api/personalities", methods=["POST"])
def create_personality():
    data = request.get_json(silent=True) or {}
    personality_id = str(uuid.uuid4())
    from ..models import Personality

    personality = Personality(
        id=personality_id,
        name=data.get("name", "New Personality"),
        description=data.get("description", ""),
        skills=data.get("skills", []),
        abilities=data.get("abilities", []),
        system_prompt=data.get("system_prompt", ""),
    )
    personalities_repo.add(personality)
    return jsonify({"success": True, "personality": personality.to_dict()}), 201


@personalities_bp.route("/api/personalities/<personality_id>", methods=["GET"])
def get_personality(personality_id):
    personalities_repo.load()
    p = personalities_repo.get(personality_id)
    if not p:
        return jsonify({"error": "Personality not found"}), 404
    return jsonify(p.to_dict())


@personalities_bp.route("/api/personalities/<personality_id>", methods=["PUT"])
def update_personality(personality_id):
    personalities_repo.load()
    data = request.get_json(silent=True) or {}
    p = personalities_repo.get(personality_id)
    if not p:
        return jsonify({"error": "Personality not found"}), 404
    for k in ("name", "description", "skills", "abilities", "system_prompt"):
        if k in data:
            setattr(p, k, data[k])
    personalities_repo.save()
    return jsonify({"success": True, "personality": p.to_dict()})


@personalities_bp.route("/api/personalities/<personality_id>", methods=["DELETE"])
def delete_personality(personality_id):
    personalities_repo.load()
    # Rebuild list without the target
    remaining = [pp for pp in personalities_repo.all() if pp.id != personality_id]
    if len(remaining) == len(personalities_repo.all()):
        return jsonify({"error": "Personality not found"}), 404
    personalities_repo._personalities = remaining
    personalities_repo.save()
    return jsonify({"success": True})