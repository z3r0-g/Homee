"""Knowledge base routes."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..models import bots_repo

knowledge_bp = Blueprint("knowledge", __name__)


@knowledge_bp.route("/api/knowledge/<bot_id>", methods=["GET"])
def get_knowledge(bot_id):
    bots_repo.load()
    bot = bots_repo.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found"}), 404

    kb_path = bot.knowledge_path()
    try:
        content = kb_path.read_text(encoding="utf-8") if kb_path.exists() else "# Knowledge Base\n\nNo knowledge base yet."
    except OSError:
        content = "# Knowledge Base\n\nError reading knowledge base."
    return jsonify({"content": content, "path": str(kb_path)})


@knowledge_bp.route("/api/knowledge/<bot_id>", methods=["POST"])
def append_knowledge(bot_id):
    bots_repo.load()
    bot = bots_repo.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found"}), 404

    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    if not content:
        return jsonify({"error": "No content provided"}), 400

    kb_path = bot.knowledge_path()
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    existing = kb_path.read_text(encoding="utf-8") if kb_path.exists() else ""
    kb_path.write_text(existing + f"\n{content}\n", encoding="utf-8")
    return jsonify({"success": True, "path": str(kb_path)})