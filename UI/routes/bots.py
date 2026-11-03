"""Bot management routes."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type
from flask import Blueprint, jsonify, request

from ..config import BOTS_DIR, MCP_SERVICE_URL
from ..llm import LLMRouter
from ..models import bots_repo, skills_repo, Bot, BotConfig
from Skills.app import MAX_TOOL_ROUNDS, SkillBase, bot_base_context
from Skills.local.mastodon import get_server_health
from Skills.registry import skill_registry

bots_bp = Blueprint("bots", __name__)
llm_router = LLMRouter()

# PLAN.md 1.1: attached files are truncated to 12k chars before injection.
MAX_ATTACHMENT_CHARS = 12_000


def _local_knowledge_notice(content: str) -> str:
    """Disclose that a last-resort reply was generated without tool evidence."""
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        f"{content}\n\n"
        f"_Source: local model knowledge only; it may be outdated as of {today}. "
        "No cache or tool result was available for this reply._"
    )


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════
# File attachments (PLAN.md 1.1 — "Ask About a File")
# ══════════════════════════════════════════════════════════════════

def _format_attachment(name: str, text: str) -> str:
    """Wrap decoded file text in the plan-specified injection block."""
    total = len(text)
    if total > MAX_ATTACHMENT_CHARS:
        header = f"[User attached file: {name} ({total} chars, truncated to {MAX_ATTACHMENT_CHARS})]"
        text = text[:MAX_ATTACHMENT_CHARS]
    else:
        header = f"[User attached file: {name} ({total} chars)]"
    return f"{header}\n{text}"


def _collect_attachments(data: Dict[str, Any]) -> Tuple[str, List[str], Optional[str]]:
    """Normalize text/image attachments from a JSON body and/or multipart form.

    Returns ``(attachment_text, images, error)``. Text files are decoded as
    utf-8 (ignoring errors), truncated to MAX_ATTACHMENT_CHARS, and wrapped in
    a ``[User attached file: …]`` block. Attachments live only for the request
    — they are never written to ``UI/instances/``.
    """
    blocks: List[str] = []
    images: List[str] = []

    # multipart/form-data: optional `file` field (PLAN.md 1.1)
    upload = request.files.get("file") if request.files else None
    if upload is not None:
        name = (upload.filename or "file.txt")[:200]
        raw = upload.read()
        if b"\x00" in raw:
            return "", [], f"'{name}' looks like a binary file — attach a text file instead (.txt, .md, .json, .py, .log)."
        blocks.append(_format_attachment(name, raw.decode("utf-8", errors="ignore")))

    # JSON body: attachments: [{name, content, type?}]
    for att in data.get("attachments") or []:
        if not isinstance(att, dict):
            continue
        att_content = str(att.get("content", ""))
        att_name = str(att.get("name", "file"))[:200]
        if att.get("type") == "image" or att_content.startswith("data:image/"):
            if "," in att_content:
                att_content = att_content.split(",", 1)[1]
            images.append(att_content)
        elif att_content:
            if "\x00" in att_content:
                return "", [], f"'{att_name}' looks like a binary file — attach a text file instead (.txt, .md, .json, .py, .log)."
            blocks.append(_format_attachment(att_name, att_content))

    return "\n\n".join(blocks), images, None


# ══════════════════════════════════════════════════════════════════
# Append-only chat history log (PLAN.md 1.2 — "Search Across Chats")
# ══════════════════════════════════════════════════════════════════

def _history_path(bot_id: str) -> Path:
    return BOTS_DIR / bot_id / "history.jsonl"


def _append_history(bot: Bot, entries: List[Dict[str, Any]]) -> None:
    """Append chat turns to the bot's append-only JSONL history log.

    Attached file contents are never written here — only the messages as
    typed/sent, so an attachment never lands in ``UI/instances/``.
    """
    try:
        path = _history_path(bot.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[UI] Could not append history for bot {bot.id}: {e}")


def _iter_searchable_messages(bot: Bot) -> Iterator[Dict[str, Any]]:
    """Yield a bot's messages for search: the full JSONL log when present,
    falling back to the in-memory conversation window (older bots)."""
    path = _history_path(bot.id)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(msg, dict):
                        yield msg
            return
        except OSError:
            pass
    yield from (bot.conversation_history or [])


def _search_bots(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Linear substring scan across all bots' histories (top ``limit``)."""
    needle = query.lower()
    results: List[Dict[str, Any]] = []
    bots_repo.load()
    for bot in bots_repo.all():
        for msg in _iter_searchable_messages(bot):
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
            if len(results) >= limit:
                return results
    return results


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


def _resolve_bot_skills(skill_ids: List[str]) -> Tuple[Type[SkillBase], str]:
    """Resolve a bot's skills to a single executable skill class + prompt.

    - No skills -> the generic ``SkillBase``.
    - One skill -> that skill as-is (custom ``execute()`` preserved).
    - Many skills -> a composite ``SkillBase`` subclass whose system prompt
      joins each skill's instructions and whose tool set is the union of all
      skills' tools. Skills with a custom ``execute()`` (e.g. HomeKeeper)
      contribute their prompt and tools to the composite.
    """
    resolved = [_resolve_bot_skill(sid) for sid in skill_ids if sid]
    resolved = [(cls, prompt) for cls, prompt in resolved if cls]
    if not resolved:
        return SkillBase, SkillBase.system_prompt
    if len(resolved) == 1:
        return resolved[0]

    prompts: List[str] = []
    tools: List[Any] = []
    names: List[str] = []
    seen_tools = set()
    for cls, prompt in resolved:
        names.append(getattr(cls, "name", "Skill"))
        if prompt and prompt not in prompts:
            prompts.append(prompt)
        for tool in getattr(cls, "tools", None) or []:
            if callable(tool) and tool.__name__ not in seen_tools:
                seen_tools.add(tool.__name__)
                tools.append(tool)

    combined_prompt = "\n\n".join(prompts)
    combined_name = " + ".join(names)
    merged_tools = tools  # distinct name: class bodies can't read `tools = tools`

    class CompositeSkill(SkillBase):
        name = combined_name
        description = f"Composite skill combining: {combined_name}"
        system_prompt = combined_prompt
        tools = merged_tools

    return CompositeSkill, combined_prompt


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


def _fallback_chat_with_tools(
    agent_cls: Optional[Type[SkillBase]],
    messages: List[Dict[str, Any]],
    mcp_executor: Any,
    mcp_tools: List[Dict[str, Any]],
    knowledge_path: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """Last-resort router chat that still advertises and executes tools.

    Used when the skill's own ``execute()`` failed (e.g. the primary model is
    missing): the router's fallback model gets the same tool specs, and tool
    calls are dispatched through the skill's registry/MCP gate exactly as in
    ``SkillBase.execute`` — so a bot keeps its tools on every backend.
    """
    try:
        skill = agent_cls() if agent_cls else SkillBase()
    except Exception:  # noqa: BLE001 - the skill class itself may be broken
        skill = SkillBase()
    specs = skill._build_tool_specs(mcp_tools=mcp_tools)
    skill._active_mcp_ids = {m.get("id") or m.get("name") for m in mcp_tools or []}

    content = ""
    for round_no in range(MAX_TOOL_ROUNDS + 1):
        result = llm_router.chat(
            messages,
            tools=None if round_no == MAX_TOOL_ROUNDS else (specs or None),
            model=model,
        )
        if result.get("error"):
            return result.get("message", {}).get("content", "")
        msg = result.get("message", {})
        content = msg.get("content", "") or content
        round_calls = msg.get("tool_calls") or []
        if not round_calls:
            break
        messages.append({
            "role": "assistant",
            "content": msg.get("content", "") or "",
            "tool_calls": round_calls,
        })
        for tc in round_calls:
            func = tc.get("function", {}) or {}
            name = func.get("name", "")
            result_text = skill._dispatch_tool(
                name, func.get("arguments") or {},
                knowledge_path=knowledge_path, mcp_executor=mcp_executor,
            )
            messages.append({"role": "tool", "content": result_text, "tool_name": name})
    return content


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
    # Multi-skill: `skill_ids` list wins; legacy single `skill_id` still works.
    skill_ids = data.get("skill_ids")
    if skill_ids is None:
        skill_ids = [data.get("skill_id", "")] if data.get("skill_id") else []
    schedule_type = data.get("schedule_type", "none")
    interval_seconds = int(data.get("interval_seconds", 3600))
    task_prompt = data.get("task_prompt", "")
    enabled = bool(data.get("enabled", False))

    bot_id = str(uuid.uuid4())
    from ..config import KNOWLEDGE_DIR
    bot = Bot(
        id=bot_id,
        name=name,
        knowledge_base_path=str(KNOWLEDGE_DIR / f"kb_{bot_id}.md"),
        mcps=[str(m) for m in data.get("mcps") or []],
        config=BotConfig(
            schedule_type=schedule_type,
            interval_seconds=interval_seconds,
            task_prompt=task_prompt,
            enabled=enabled,
        ),
    )
    bot.set_skills(skill_ids)
    bots_repo.add(bot)
    return jsonify({"success": True, "bot": bot.to_dict()}), 201


@bots_bp.route("/api/search", methods=["GET"])
def search_chats():
    """Search across all bots' chat histories (PLAN.md 1.2).

    Scans ``UI/instances/bots/*/history.jsonl`` in memory — a linear scan,
    no index — and returns the top 20 matches.
    """
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"query": "", "results": []})
    return jsonify({"query": query, "results": _search_bots(query)})


@bots_bp.route("/api/bots/search", methods=["GET"])
def search_bots():
    """Backwards-compatible alias for ``/api/search``."""
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"query": "", "results": []})
    return jsonify({"query": query, "results": _search_bots(query)})


@bots_bp.route("/api/bots/<bot_id>", methods=["GET"])
def get_bot(bot_id):
    bots_repo.load()
    bot = bots_repo.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found"}), 404
    return jsonify(bot.to_dict())


@bots_bp.route("/api/bots/<bot_id>/history", methods=["GET"])
def bot_history(bot_id):
    """Full chat history from the append-only JSONL log (capped at 500).

    Used by search to open a bot at an older match that has scrolled out of
    the 20-message conversation window.
    """
    bots_repo.load()
    bot = bots_repo.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found"}), 404
    history = list(_iter_searchable_messages(bot))[-500:]
    return jsonify({"bot_id": bot_id, "history": history, "count": len(history)})


@bots_bp.route("/api/bots/<bot_id>", methods=["PUT"])
def update_bot(bot_id):
    bots_repo.load()
    data = request.get_json(silent=True) or {}
    bot = bots_repo.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found"}), 404
    if "name" in data:
        bot.name = data["name"]
    if "skill_ids" in data:
        bot.set_skills(data["skill_ids"] or [])
    elif "skill_id" in data:
        bot.set_skills([data["skill_id"]] if data["skill_id"] else [])
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
        import shutil
        shutil.rmtree(_history_path(bot_id).parent, ignore_errors=True)
        return jsonify({"success": True})
    return jsonify({"error": "Bot not found"}), 404


@bots_bp.route("/api/bots/<bot_id>/chat", methods=["POST"])
def chat_bot(bot_id):
    """Process a chat turn with a bot using its assigned skill, MCPs, and optional multimodal attachments.

    Accepts JSON (``message``, optional ``attachments``) or
    ``multipart/form-data`` with a ``message`` field and an optional ``file``
    field (PLAN.md 1.1).
    """
    bots_repo.load()
    skills_repo.load()
    bot = bots_repo.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found"}), 404

    if request.content_type and request.content_type.startswith("multipart/form-data"):
        data = request.form.to_dict()
    else:
        data = request.get_json(silent=True) or {}

    attachment_text, images, attach_error = _collect_attachments(data)
    if attach_error:
        return jsonify({"error": attach_error}), 400

    user_message = str(data.get("message", "")).strip()
    if not user_message:
        if attachment_text:
            user_message = "What can you tell me about the attached file?"
        else:
            return jsonify({"error": "No message provided"}), 400

    model = data.get("model") or None

    # Inject attached file(s) ahead of the user's message (PLAN.md 1.1 format)
    full_prompt = user_message
    if attachment_text:
        full_prompt = f"{attachment_text}\n\n{user_message}"

    sent_at = _iso()

    # Resolve skills assigned to the bot
    agent_cls, system_prompt = _resolve_bot_skills(bot.skill_id_list())
    mcp_executor, mcp_tools = _get_mcp_executor_and_tools(bot)

    assistant_response = ""

    # Execute with assigned skill(s) if available
    executed_skill = False
    if agent_cls:
        try:
            skill_inst = agent_cls()
            if model:
                skill_inst.model = model
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
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": bot_base_context(bot.knowledge_base_path)},
        ]
        messages.extend(bot.conversation_history[-20:])
        user_turn: Dict[str, Any] = {"role": "user", "content": full_prompt}
        if images:
            user_turn["images"] = images
        messages.append(user_turn)

        assistant_response = _local_knowledge_notice(
            _fallback_chat_with_tools(
                agent_cls, messages, mcp_executor, mcp_tools,
                knowledge_path=bot.knowledge_base_path, model=model,
            )
        )

    received_at = _iso()
    user_entry: Dict[str, Any] = {"role": "user", "content": user_message, "timestamp": sent_at}
    if images:
        user_entry["has_image"] = True
    new_entries = [
        user_entry,
        {"role": "assistant", "content": assistant_response, "timestamp": received_at},
    ]
    bot.conversation_history.extend(new_entries)
    bot.conversation_history = bot.conversation_history[-20:]
    _append_history(bot, new_entries)
    bot.updated_at = _iso()
    bots_repo.add(bot)

    return jsonify({
        "response": assistant_response,
        "bot_id": bot_id,
        "skill": bot.skill_id_list()[0] if bot.skill_id_list() else "",
        "skills": bot.skill_id_list(),
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

    agent_cls, system_prompt = _resolve_bot_skills(bot.skill_id_list())
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
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": bot_base_context(bot.knowledge_base_path)},
        ]
        messages.extend(bot.conversation_history[-20:])
        messages.append({"role": "user", "content": task_prompt})
        result_text = _local_knowledge_notice(
            _fallback_chat_with_tools(
                agent_cls, messages, mcp_executor, mcp_tools,
                knowledge_path=bot.knowledge_base_path,
            )
        )

    finished_at = _iso()

    new_entries = [
        {"role": "user", "content": task_prompt, "timestamp": started_at},
        {"role": "assistant", "content": result_text, "timestamp": finished_at},
    ]
    bot.conversation_history.extend(new_entries)
    bot.conversation_history = bot.conversation_history[-20:]
    _append_history(bot, new_entries)
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
