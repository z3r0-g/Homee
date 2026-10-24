"""Knowledge base MCP endpoints — read/append bot knowledge bases."""

from __future__ import annotations

from pathlib import Path
from flask import Blueprint, jsonify, request

from ..config import KNOWLEDGE_DIR

knowledge_bp = Blueprint("knowledge", __name__)


@knowledge_bp.route("/api/mcp/knowledge/<bot_id>", methods=["GET"])
def mcp_knowledge_get(bot_id):
    kb_path = KNOWLEDGE_DIR / f"kb_{bot_id}.md"
    try:
        content = kb_path.read_text(encoding="utf-8") if kb_path.exists() else "# Knowledge Base\n\nNo knowledge base yet."
    except OSError:
        content = "# Knowledge Base\n\nError reading knowledge base."
    return jsonify({"content": content, "path": str(kb_path)})


@knowledge_bp.route("/api/mcp/knowledge/<bot_id>", methods=["POST"])
def mcp_knowledge_append(bot_id):
    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    if not content:
        return jsonify({"error": "No content provided"}), 400
    kb_path = KNOWLEDGE_DIR / f"kb_{bot_id}.md"
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    existing = kb_path.read_text(encoding="utf-8") if kb_path.exists() else ""
    kb_path.write_text(existing + f"\n{content}\n", encoding="utf-8")
    return jsonify({"success": True, "path": str(kb_path)})