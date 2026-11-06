"""Skill base class — every skill subclasses this."""

from __future__ import annotations

import importlib
import inspect
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import ollama

__all__ = [
    "SkillBase", "SkillResult", "bot_base_context",
    "is_tool_support_error", "source_kind",
]

SKILL_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
MAX_KNOWLEDGE_CACHE_CHARS = 8_000
# Cap on tool-calling rounds per turn: the model may chain several tools
# (e.g. a news MCP after a weather tool), but a stuck model must not loop
# forever. The final round drops the tool specs to force a text answer.
MAX_TOOL_ROUNDS = 8


def is_tool_support_error(exc: BaseException) -> bool:
    """True when the LLM backend rejected the request because the model
    cannot do tool calling (e.g. Ollama's "does not support tools")."""
    text = str(exc).lower()
    return "does not support tools" in text or (
        "tool" in text and "not support" in text
    )


def source_kind(tool_name: str) -> str:
    """Classify an executed tool call for source citation."""
    if tool_name.startswith("mcp_"):
        return "mcp"
    if tool_name == "knowledge_base":
        return "knowledge_base"
    return "tool"


def bot_base_context(knowledge_path: Optional[str] = None) -> str:
    """Return shared, date-aware policy and the bot's bounded local cache."""
    today = datetime.now(timezone.utc).date().isoformat()
    cache = ""
    if knowledge_path:
        path = Path(knowledge_path)
        try:
            if path.exists():
                cache = path.read_text(encoding="utf-8")[-MAX_KNOWLEDGE_CACHE_CHARS:]
        except OSError as exc:
            cache = f"[Knowledge cache unavailable: {exc}]"

    cache_context = (
        f"\n\nLocal knowledge cache (check this first):\n{cache}"
        if cache else
        "\n\nLocal knowledge cache: no cached information is available for this bot."
    )
    return (
        f"Homee base policy — today's date is {today} (UTC). Keep dates and "
        "time-sensitive reasoning relevant to today. For every request: first "
        "check the local knowledge cache below; second, use an available Skill "
        "or MCP tool when current, external, or verifiable information is "
        "needed; only then answer from local model knowledge. When answering "
        "without cache or tool evidence, clearly say that it is local model "
        f"knowledge and may be outdated as of {today}. Do not claim a tool was "
        "used when it was not.\n\n"
        "Sourcing and citations: every factual, current, or external claim "
        "must come from the knowledge cache or a real tool/MCP result — never "
        "from memory alone when a tool could verify it. Always answer the "
        "question fully first; then, when a tool or MCP result informed the "
        "answer, cite it by ending the reply with a \"Sources:\" section "
        "listing each tool or MCP used by name (e.g. \"- mcp_weather "
        "(Weather Service)\") and any source URLs present in the tool output. "
        "Never invent sources, URLs, quotes, or citations. If no tool "
        "or cache evidence is available, say so explicitly instead of citing."
        f"{cache_context}"
    )

@dataclass
class SkillResult:
    """Result of an Skill execution turn."""

    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_updated: bool = False
    error: Optional[str] = None
    # Real-world sources used this turn, for citations: one entry per
    # executed tool/MCP call, e.g. {"name": "mcp_weather", "kind": "mcp"}.
    sources: List[Dict[str, str]] = field(default_factory=list)


class SkillBase:
    name: str = "Generic Homee"
    description: str = "A generic AI skill."
    system_prompt: str = (
        "You are a helpful assistant. Always use available skills, tools, and "
        "MCPs to fetch current, up-to-date information instead of relying on "
        "your training data. Use the tool-calling interface (do not print JSON). "
        "Only state factual, current, or external claims that are backed by a "
        "tool/MCP result or the knowledge cache, and cite those sources in a "
        "\"Sources:\" section. Never invent facts, sources, or URLs; when "
        "nothing verified is available, say the answer is local model "
        "knowledge and may be outdated."
    )
    model: str = SKILL_MODEL
    tools: List[Callable[..., Any]] = []
    # Default for the base class itself; __init_subclass__ rebuilds it per subclass.
    _tool_registry: Dict[str, Callable[..., Any]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._tool_registry: Dict[str, Callable[..., Any]] = {}
        raw_tools = getattr(cls, "tools", None)
        if not isinstance(raw_tools, (list, tuple)):
            raw_tools = []
        for tool in raw_tools:
            if callable(tool):
                cls._tool_registry[tool.__name__] = tool

    # ════════════════════════════════════════════════════════════════
    # Execution
    # ════════════════════════════════════════════════════════════════

    def execute(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        knowledge_path: Optional[str] = None,
        mcp_executor: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
        mcp_tools: Optional[List[Dict[str, Any]]] = None,
        images: Optional[List[str]] = None,
    ) -> SkillResult:
        """Run one turn of the skill: LLM call + optional tool execution."""
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": bot_base_context(knowledge_path)},
        ]
        if conversation_history:
            messages.extend(conversation_history[-20:])

        # MCP dispatch gate: when the caller passes a tool list (the bot routes
        # always do), only those MCPs may be invoked — even if the model asks
        # for one that was never advertised. ``None`` means unrestricted
        # (direct/REPL skill usage).
        self._active_mcp_ids: Optional[set] = None
        if mcp_tools is not None:
            self._active_mcp_ids = {m.get("id") or m.get("name") for m in mcp_tools}
        user_turn: Dict[str, Any] = {"role": "user", "content": user_message}
        if images:
            user_turn["images"] = images
        messages.append(user_turn)

        ollama_tools = self._build_tool_specs(mcp_tools=mcp_tools)

        tool_calls: List[Dict[str, Any]] = []
        sources: List[Dict[str, str]] = []
        knowledge_updated = False
        assistant_content = ""
        tools_supported = True

        # Multi-round tool loop: tools stay advertised on every round so the
        # model can chain calls (e.g. a news MCP after a weather tool) and
        # react to earlier results. Dropping tools after the first round used
        # to make the model conclude it "has no access to the MCP tools".
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            force_answer = round_no == MAX_TOOL_ROUNDS or not tools_supported
            try:
                response = ollama.chat(
                    model=self.model,
                    messages=messages,
                    tools=None if force_answer else (ollama_tools or None),
                )
            except Exception as e:  # noqa: BLE001
                if not force_answer and ollama_tools and is_tool_support_error(e):
                    # The model can't do tool calling (e.g. gemma3:4b): drop
                    # the tool specs and answer without them rather than
                    # failing the whole turn. The base policy already tells
                    # the model to disclose answers without tool evidence.
                    print(
                        f"[Skills] Model '{self.model}' does not support tool "
                        "calling; answering without Skills/MCP tools this turn. "
                        "Pick a model with tool support (e.g. llama3.2:3b) to "
                        "restore tool access."
                    )
                    tools_supported = False
                    messages.append({
                        "role": "system",
                        "content": (
                            "Tool calling is unavailable for this model on this "
                            "turn, so no Skill or MCP tool could be run. Answer "
                            "from the local knowledge cache and your own "
                            "knowledge, state clearly that no live sources were "
                            "used, and do not cite or claim any tool result."
                        ),
                    })
                    continue
                if not tool_calls and not assistant_content:
                    return SkillResult(content=f"Skill LLM error: {e}", error=str(e))
                assistant_content = f"{assistant_content}\nTool follow-up error: {e}".strip()
                break
            msg = response.message
            content = getattr(msg, "content", "") or ""
            if content:
                assistant_content = content

            round_calls = [
                {
                    "name": getattr(tc.function, "name", ""),
                    "arguments": getattr(tc.function, "arguments", {}) or {},
                }
                for tc in getattr(msg, "tool_calls", []) or []
            ]
            if not round_calls:
                break
            tool_calls.extend(round_calls)

            # One assistant message carrying the tool calls, then one tool
            # message per result — the sequence chat templates expect.
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {"function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in round_calls
                ],
            })
            for call in round_calls:
                result_text = self._dispatch_tool(
                    call["name"], call["arguments"],
                    knowledge_path=knowledge_path, mcp_executor=mcp_executor,
                )
                if call["name"] == "knowledge_base":
                    knowledge_updated = True
                sources.append({
                    "name": call["name"],
                    "kind": source_kind(call["name"]),
                })
                messages.append({
                    "role": "tool",
                    "content": result_text,
                    "tool_name": call["name"],
                })

        return SkillResult(
            content=assistant_content,
            tool_calls=tool_calls,
            knowledge_updated=knowledge_updated,
            sources=sources,
        )

    # ════════════════════════════════════════════════════════════════
    # Tool dispatch
    # ════════════════════════════════════════════════════════════════

    def _dispatch_tool(
        self,
        func_name: str,
        func_args: Dict[str, Any],
        knowledge_path: Optional[str] = None,
        mcp_executor: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> str:
        if func_name in self._tool_registry:
            try:
                return str(self._tool_registry[func_name](**func_args))
            except Exception as e:  # noqa: BLE001
                return f"Tool error: {e}"

        if func_name.startswith("mcp_"):
            mcp_id = func_name[len("mcp_"):]
            allowed = getattr(self, "_active_mcp_ids", None)
            if allowed is not None and mcp_id not in allowed:
                return f"MCP {mcp_id} is not available to this bot"
            if mcp_executor:
                try:
                    result = mcp_executor(mcp_id, func_args)
                    return json.dumps(result, indent=2)
                except Exception as e:  # noqa: BLE001
                    return f"MCP error: {e}"
            return f"MCP {mcp_id} executor not available"

        if func_name == "knowledge_base":
            kb_path = knowledge_path
            if kb_path:
                try:
                    path = Path(kb_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    existing = path.read_text(encoding="utf-8") if path.exists() else ""
                    path.write_text(
                        existing + f"\n## Tool Query\n{json.dumps(func_args, indent=2)}\n",
                        encoding="utf-8",
                    )
                    return f"Knowledge base updated at {kb_path}"
                except OSError as e:
                    return f"Knowledge base error: {e}"
            return "No knowledge base path configured"

        return f"Unknown tool: {func_name}"

    # ════════════════════════════════════════════════════════════════
    # Tool specs for Ollama
    # ════════════════════════════════════════════════════════════════

    def _build_tool_specs(self, mcp_tools: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []

        for name, func in self._tool_registry.items():
            sig = inspect.signature(func)
            properties: Dict[str, Any] = {}
            required: List[str] = []
            for pname, param in sig.parameters.items():
                if pname == "self":
                    continue
                annotation = param.annotation
                json_type = "string"
                if annotation is int:
                    json_type = "integer"
                elif annotation is float:
                    json_type = "number"
                elif annotation is bool:
                    json_type = "boolean"
                properties[pname] = {"type": json_type}
                if param.default is inspect.Parameter.empty:
                    required.append(pname)
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": func.__doc__ or "",
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    },
                }
            )

        # Knowledge base tool
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": "knowledge_base",
                    "description": "Persist information to the bot's knowledge base.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                        },
                        "required": ["content"],
                    },
                },
            }
        )

        # MCP tools
        for mcp in (mcp_tools or []):
            mcp_id = mcp.get("id") or mcp.get("name")
            if not mcp_id:
                continue
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": f"mcp_{mcp_id}",
                        "description": mcp.get("description") or f"MCP tool: {mcp.get('name', mcp_id)}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Command or input parameter for the tool"},
                                "query": {"type": "string", "description": "Query or parameter for the tool"},
                            },
                        },
                    },
                }
            )

        return specs


# ══════════════════════════════════════════════════════════════════
# Built-in system tools (available to all skills)
# ══════════════════════════════════════════════════════════════════


def get_disk_space() -> str:
    """Return free disk space on the root filesystem."""
    total, used, free = shutil.disk_usage("/")
    return f"{free // (2**30)} GB free out of {total // (2**30)} GB"


def run_shell(command: str) -> str:
    """Run a shell command and return its stdout/stderr."""
    try:
        result = subprocess.run(
            command, shell=True, text=True, capture_output=True, timeout=10
        )
        return result.stdout or result.stderr
    except Exception as e:  # noqa: BLE001
        return str(e)
