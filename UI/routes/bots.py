"""Bot management routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

from ..config import MCP_SERVICE_URL
from ..llm import LLMRouter
from ..models import bots_repo, personalities_repo, Bot, BotConfig
from Agents.local.demo import get_server_health

bots_bp = Blueprint("bots", __name__)
llm_router = LLMRouter()


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    personality_id = data.get("personality_id", "")
    schedule_type = data.get("schedule_type", "none")
    interval_seconds = int(data.get("interval_seconds", 3600))
    task_prompt = data.get("task_prompt", "")
    enabled = bool(data.get("enabled", False))

    bot_id = str(uuid.uuid4())
    from ..config import KNOWLEDGE_DIR
    bot = Bot(
        id=bot_id,
        name=name,
        personality_id=personality_id,
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
    """Substring search across all bots' conversation history.

    One search box replaces folders/tags/pins. Returns up to 30 matches
    with a snippet around the hit; an empty query returns nothing.
    """
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
    if "personality_id" in data:
        bot.personality_id = data["personality_id"]
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
    bots_repo.load()
    personalities_repo.load()
    bot = bots_repo.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found"}), 404

    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "")
    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    # Optional per-chat model override (the Fast/Smart composer switch).
    # Only the model is overridable; the provider stays as configured.
    model = data.get("model") or None

    # Optional attached file context (ask-about-a-file): text only,
    # capped server-side, injected into this turn's messages but never
    # persisted to conversation_history.
    attachment_text = ""
    for att in data.get("attachments") or []:
        if isinstance(att, dict) and att.get("content"):
            attachment_text += f"\n\nFile: {str(att.get('name', 'file'))[:200]}\n{str(att['content'])[:50_000]}"
    attachment_text = attachment_text[:100_000]

    sent_at = _iso()
    personality = personalities_repo.get(bot.personality_id) if bot.personality_id else None
    system_prompt = personality.system_prompt if personality else ""

    messages = [{"role": "system", "content": system_prompt}]
    if attachment_text.strip():
        messages.append({"role": "system", "content": "The user attached file(s) for this chat. Use their contents to answer questions about them." + attachment_text})
    messages.extend(bot.conversation_history[-20:])
    messages.append({"role": "user", "content": user_message})

    result = llm_router.chat(messages, model=model)
    assistant_response = result.get("message", {}).get("content", "")

    received_at = _iso()
    bot.conversation_history.extend([
        {"role": "user", "content": user_message, "timestamp": sent_at},
        {"role": "assistant", "content": assistant_response, "timestamp": received_at},
    ])
    bot.conversation_history = bot.conversation_history[-20:]
    bot.updated_at = _iso()
    bots_repo.add(bot)

    return jsonify({
        "response": assistant_response,
        "bot_id": bot_id,
        "personality": bot.personality_id,
    })


@bots_bp.route("/api/bots/<bot_id>/run", methods=["POST"])
def run_bot(bot_id):
    """Execute a Bot's scheduled task using its assigned Agent personality."""
    data = request.get_json(silent=True) or {}
    task_prompt = data.get("task_prompt")
    result = _execute_bot_task(bot_id, task_prompt=task_prompt)
    if "error" in result:
        return jsonify(result), 404 if result["error"] == "Bot not found" else 400
    return jsonify(result)


def _execute_bot_task(bot_id: str, task_prompt: str | None = None) -> dict:
    """Shared bot-execution logic used by both the /run route and the scheduler."""
    bots_repo.load()
    personalities_repo.load()
    bot = bots_repo.get(bot_id)
    if not bot:
        return {"error": "Bot not found"}

    task_prompt = task_prompt or bot.config.task_prompt
    if not task_prompt:
        return {"error": "No task prompt configured"}

    started_at = _iso()

    personality = personalities_repo.get(bot.personality_id) if bot.personality_id else None
    system_prompt = personality.system_prompt if personality else ""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(bot.conversation_history[-20:])
    messages.append({"role": "user", "content": task_prompt})

    import requests as _req

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
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    # Determine agent based on personality_id
    agent_cls = None
    system_prompt = ""
    
    if bot.personality_id == "demo":
        # Use Demo System Agent from demo.py
        from Agents.registry import agent_registry
        agent_cls = agent_registry.get_agent("Demo System Agent")
        if agent_cls:
            system_prompt = agent_cls().system_prompt
    elif bot.personality_id == "general":
        # Use General/Agent base class
        from Agents.app import AgentBase
        system_prompt = AgentBase.system_prompt
    else:
        # A personality id may correspond to a discovered agent name rather than
        # a saved personality. Resolve agents first so bot creators can pick an
        # agent (e.g. "Burundy Weather Agent") directly from the New-Bot form.
        from Agents.registry import agent_registry

        agent_cls = agent_registry.get_agent(bot.personality_id)
        if agent_cls:
            system_prompt = agent_cls().system_prompt
        else:
            personality = (
                personalities_repo.get(bot.personality_id)
                if bot.personality_id
                else None
            )
            if personality:
                system_prompt = personality.system_prompt

    result_text = ""
    if agent_cls:
        agent = agent_cls()
        agent_result = agent.execute(
            task_prompt,
            conversation_history=bot.conversation_history[-20:],
            knowledge_path=bot.knowledge_base_path,
            mcp_executor=mcp_executor,
        )
        result_text = agent_result.content
    else:
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