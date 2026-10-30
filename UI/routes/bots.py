"""Bot management routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Type
from flask import Blueprint, jsonify, request

from ..config import MCP_SERVICE_URL
from ..llm import LLMRouter
from ..models import bots_repo, skills_repo, Bot, BotConfig
from Skills.app import SkillBase
from Skills.local.demo import get_server_health
from Skills.registry import skill_registry

bots_bp = Blueprint("bots", __name__)
llm_router = LLMRouter()


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_bot_skill(skill_id: Optional[str]) -> Tuple[Optional[Type[SkillBase]], str]:
    """Resolve skill class and system prompt for a given skill_id.
    Supports discovered skills (e.g. Burgundy, Demo), saved skills, and general skills.
    """
    if not skill_id:
        return SkillBase, SkillBase.system_prompt

    if skill_id == "demo":
        cls = skill_registry.get_skill("Demo System Skill")
        if cls:
            return cls, cls().system_prompt
    elif skill_id == "general":
        return SkillBase, SkillBase.system_prompt

    # Check skill registry first (discovered skills like 'Burgundy Weather Skill')
    cls = skill_registry.get_skill(skill_id)
    if cls:
        return cls, cls().system_prompt

    # Check saved skills repository
    skills_repo.load()
    saved = skills_repo.get(skill_id)
    if saved:
        # Dynamically subclass SkillBase to preserve saved system prompt & capabilities
        prompt = saved.system_prompt or "You are a helpful assistant."
        class DynamicSavedSkill(SkillBase):
            name = saved.name
            description = saved.description
            system_prompt = prompt

        return DynamicSavedSkill, prompt

    return SkillBase, SkillBase.system_prompt


def _get_mcp_executor_and_tools(bot: Bot):
    """Build MCP executor callback and list of available MCP tool specs for this bot."""
    import requests as _req

    mcp_tools: List[Dict[str, Any]] = []
    try:
        resp = _req.get(f"{MCP_SERVICE_URL}/api/mcps", timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            raw_mcps = data.get("mcps", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for m in raw_mcps:
                if m.get("enabled", True):
                    if not bot.mcps or m["id"] in bot.mcps:
                        mcp_tools.append(m)
    except Exception:
        pass

    # Built-in system tools
    system_mcps = [
        {"id": "system_disk", "name": "system_disk", "description": "Check free disk space on root filesystem"},
        {"id": "system_shell", "name": "system_shell", "description": "Execute a shell command"},
    ]
    for sm in system_mcps:
        if not any(t["id"] == sm["id"] for t in mcp_tools):
            mcp_tools.append(sm)

    def mcp_executor(mcp_id: str, args: dict) -> dict:
        try:
            resp = _req.post(
                f"{MCP_SERVICE_URL}/api/mcp/execute/{mcp_id}",
                json=args,
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"MCP service returned {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    return mcp_executor, mcp_tools


@bots_bp.route("/api/server-health", methods=["GET"])
def server_health():
    """Host health (disk/memory/CPU) for the bot detail panel."""
    try:
        return jsonify(get_server_health())
    except Exception as e:  # noqa: BLE001 - psutil is optional
        return jsonify({"error": f"Server health unavailable: {e}"}), 503


@bots_bp.route("/api/bots", methods=["GET"])
def list_bots():
    bots_repo.load()
    return jsonify({
        "bots": [b.to_dict() for b in bots_repo.all()],
        "count": len(bots_repo.all()),
    })


@bots_bp.route("/api/bots", methods=["POST"])
def create_bot():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "New Bot")
    skill_id = data.get("skill_id", "")
    schedule_type = data.get("schedule_type", "none")
    interval_seconds = int(data.get("interval_seconds", 3600))
    task_prompt = data.get("task_prompt", "")
    enabled = bool(data.get("enabled", False))

    bot_id = str(uuid.uuid4())
    from ..config import KNOWLEDGE_DIR
    bot = Bot(
        id=bot_id,
        name=name,
        skill_id=skill_id,
        knowledge_base_path=str(KNOWLEDGE_DIR / f"kb_{bot_id}.md"),
        config=BotConfig(
            schedule_type=schedule_type,
            interval_seconds=interval_seconds,
            task_prompt=task_prompt,
            enabled=enabled,
        ),
    )
    bots_repo.add(bot)
    return jsonify({"success": True, "bot": bot.to_dict()}), 201


@bots_bp.route("/api/bots/search", methods=["GET"])
def search_bots():
    """Substring search across all bots' conversation history."""
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"query": "", "results": []})
    needle = query.lower()
    results = []
    bots_repo.load()
    for bot in bots_repo.all():
        for msg in bot.conversation_history or []:
            content = str(msg.get("content", ""))
            idx = content.lower().find(needle)
            if idx < 0:
                continue
            start = max(0, idx - 60)
            end = min(len(content), idx + len(query) + 60)
            snippet = ("…" if start > 0 else "") + content[start:end] + ("…" if end < len(content) else "")
            results.append({
                "bot_id": bot.id,
                "bot_name": bot.name,
                "role": msg.get("role", ""),
                "snippet": snippet,
                "timestamp": msg.get("timestamp"),
            })
            if len(results) >= 30:
                return jsonify({"query": query, "results": results})
    return jsonify({"query": query, "results": results})


@bots_bp.route("/api/bots/<bot_id>", methods=["GET"])
def get_bot(bot_id):
    bots_repo.load()
    bot = bots_repo.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found"}), 404
    return jsonify(bot.to_dict())


@bots_bp.route("/api/bots/<bot_id>", methods=["PUT"])
def update_bot(bot_id):
    bots_repo.load()
    data = request.get_json(silent=True) or {}
    bot = bots_repo.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found"}), 404
    if "name" in data:
        bot.name = data["name"]
    if "skill_id" in data:
        bot.skill_id = data["skill_id"]
    if "status" in data:
        bot.status = data["status"]
    if "mcps" in data:
        bot.mcps = data["mcps"]
    cfg = bot.config
    for k in ("schedule_type", "interval_seconds", "cron_expression", "task_prompt", "enabled"):
        if k in data:
            setattr(cfg, k, data[k])
    if "config" in data and isinstance(data["config"], dict):
        for k, v in data["config"].items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
    bot.updated_at = _iso()
    bots_repo.save()
    return jsonify({"success": True, "bot": bot.to_dict()})


@bots_bp.route("/api/bots/<bot_id>", methods=["DELETE"])
def delete_bot(bot_id):
    bots_repo.load()
    bot = bots_repo.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found"}), 404
    # Only allow deletion if the bot is already disabled
    if bot.config.enabled:
        return jsonify({"error": "Bot must be disabled before deletion"}), 403
    if bots_repo.delete(bot_id):
        return jsonify({"success": True})
    return jsonify({"error": "Bot not found"}), 404


@bots_bp.route("/api/bots/<bot_id>/chat", methods=["POST"])
def chat_bot(bot_id):
    """Process a chat turn with a bot using its assigned skill, MCPs, and optional multimodal attachments."""
    bots_repo.load()
    skills_repo.load()
    bot = bots_repo.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found"}), 404

    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "")
    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    model = data.get("model") or None

    # Process attachments: text context and image attachments (vision)
    attachment_text = ""
    images: List[str] = []
    for att in data.get("attachments") or []:
        if isinstance(att, dict):
            att_content = str(att.get("content", ""))
            if att.get("type") == "image" or att_content.startswith("data:image/"):
                if "," in att_content:
                    att_content = att_content.split(",", 1)[1]
                images.append(att_content)
            elif att_content:
                attachment_text += f"\n\nFile: {str(att.get('name', 'file'))[:200]}\n{att_content[:50_000]}"
    attachment_text = attachment_text[:100_000]

    sent_at = _iso()

    # Resolve skill assigned to the bot
    agent_cls, system_prompt = _resolve_bot_skill(bot.skill_id)
    mcp_executor, mcp_tools = _get_mcp_executor_and_tools(bot)

    assistant_response = ""

    # Execute with assigned skill if available
    executed_skill = False
    if agent_cls:
        try:
            skill_inst = agent_cls()
            if model:
                skill_inst.model = model
            full_prompt = user_message
            if attachment_text.strip():
                full_prompt = f"User attached context:\n{attachment_text}\n\n{user_message}"
            res = skill_inst.execute(
                full_prompt,
                conversation_history=bot.conversation_history[-20:],
                knowledge_path=bot.knowledge_base_path,
                mcp_executor=mcp_executor,
                mcp_tools=mcp_tools,
                images=images or None,
            )
            if not res.error:
                assistant_response = res.content
                executed_skill = True
        except Exception:
            executed_skill = False

    # Fallback to LLM router if skill execution failed or returned error
    if not executed_skill:
        messages = [{"role": "system", "content": system_prompt}]
        if attachment_text.strip():
            messages.append({"role": "system", "content": "The user attached file(s) for this chat. Use their contents to answer questions about them." + attachment_text})
        messages.extend(bot.conversation_history[-20:])
        user_turn: Dict[str, Any] = {"role": "user", "content": user_message}
        if images:
            user_turn["images"] = images
        messages.append(user_turn)

        result = llm_router.chat(messages, model=model)
        assistant_response = result.get("message", {}).get("content", "")

    received_at = _iso()
    user_entry = {"role": "user", "content": user_message, "timestamp": sent_at}
    if images:
        user_entry["has_image"] = True
    bot.conversation_history.extend([
        user_entry,
        {"role": "assistant", "content": assistant_response, "timestamp": received_at},
    ])
    bot.conversation_history = bot.conversation_history[-20:]
    bot.updated_at = _iso()
    bots_repo.add(bot)

    return jsonify({
        "response": assistant_response,
        "bot_id": bot_id,
        "skill": bot.skill_id,
    })


@bots_bp.route("/api/bots/<bot_id>/run", methods=["POST"])
def run_bot(bot_id):
    """Execute a Bot's scheduled task using its assigned skill."""
    data = request.get_json(silent=True) or {}
    task_prompt = data.get("task_prompt")
    result = _execute_bot_task(bot_id, task_prompt=task_prompt)
    if "error" in result:
        return jsonify(result), 404 if result["error"] == "Bot not found" else 400
    return jsonify(result)


def _execute_bot_task(bot_id: str, task_prompt: str | None = None) -> dict:
    """Shared bot-execution logic used by both the /run route and the scheduler."""
    bots_repo.load()
    skills_repo.load()
    bot = bots_repo.get(bot_id)
    if not bot:
        return {"error": "Bot not found"}

    task_prompt = task_prompt or bot.config.task_prompt
    if not task_prompt:
        return {"error": "No task prompt configured"}

    started_at = _iso()

    agent_cls, system_prompt = _resolve_bot_skill(bot.skill_id)
    mcp_executor, mcp_tools = _get_mcp_executor_and_tools(bot)

    result_text = ""
    executed_skill = False
    if agent_cls:
        try:
            skill = agent_cls()
            agent_result = skill.execute(
                task_prompt,
                conversation_history=bot.conversation_history[-20:],
                knowledge_path=bot.knowledge_base_path,
                mcp_executor=mcp_executor,
                mcp_tools=mcp_tools,
            )
            if not agent_result.error:
                result_text = agent_result.content
                executed_skill = True
        except Exception:
            executed_skill = False

    if not executed_skill:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(bot.conversation_history[-20:])
        messages.append({"role": "user", "content": task_prompt})
        llm_result = llm_router.chat(messages)
        result_text = llm_result.get("message", {}).get("content", "")

    finished_at = _iso()

    bot.conversation_history.extend([
        {"role": "user", "content": task_prompt, "timestamp": started_at},
        {"role": "assistant", "content": result_text, "timestamp": finished_at},
    ])
    bot.conversation_history = bot.conversation_history[-20:]
    bot.status = "idle"
    bot.updated_at = _iso()
    bot.config.last_run = _iso()
    bot.config.run_count += 1
    bots_repo.add(bot)

    return {
        "success": True,
        "bot_id": bot_id,
        "response": result_text,
        "server_health": get_server_health()
    }


@bots_bp.route("/api/bots/<bot_id>/schedule", methods=["POST"])
def set_schedule(bot_id):
    bots_repo.load()
    data = request.get_json(silent=True) or {}
    bot = bots_repo.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found"}), 404

    cfg = bot.config
    for k in ("schedule_type", "interval_seconds", "cron_expression", "task_prompt", "enabled"):
        if k in data:
            setattr(cfg, k, data[k])
    if "config" in data and isinstance(data["config"], dict):
        for k, v in data["config"].items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
    bot.updated_at = _iso()
    bots_repo.save()
    return jsonify({"success": True, "bot": bot.to_dict()})
