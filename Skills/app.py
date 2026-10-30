"""Skill base class — every skill subclasses this."""

from __future__ import annotations

import importlib
import inspect
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import ollama

__all__ = ["SkillBase", "SkillResult"]

# NOTE on tags: in Ollama, a bare "llama3.2" resolves to the :latest tag,
# which is NOT satisfied by an installed "llama3.2:3b" — always use a full
# tag. OLLAMA_MODEL wins when set (same convention as the UI service),
# so a host with a different tag installed (e.g. llama3.2:3b) just sets it.
SKILL_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

@dataclass
class SkillResult:
    """Result of an Skill execution turn."""

    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_updated: bool = False
    error: Optional[str] = None


class SkillBase:
    name: str = "Generic Homee"
    description: str = "A generic AI skill."
    system_prompt: str = "You are a helpful assistant."
    model: str = SKILL_MODEL
    tools: List[Callable[..., Any]] = []

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
    ) -> SkillResult:
        """Run one turn of the skill: LLM call + optional tool execution."""
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt}
        ]
        if conversation_history:
            messages.extend(conversation_history[-20:])
        messages.append({"role": "user", "content": user_message})

        ollama_tools = self._build_tool_specs()

        try:
            response = ollama.chat(model=self.model, messages=messages, tools=ollama_tools or None)
        except Exception as e:  # noqa: BLE001
            return SkillResult(content=f"Skill LLM error: {e}", error=str(e))
        msg = response.message
        assistant_content = getattr(msg, "content", "") or ""

        tool_calls: List[Dict[str, Any]] = []
        knowledge_updated = False

        for tc in getattr(msg, "tool_calls", []) or []:
            func_name = getattr(tc.function, "name", "")
            func_args = getattr(tc.function, "arguments", {}) or {}
            tool_calls.append({"name": func_name, "arguments": func_args})

            result_text = self._dispatch_tool(
                func_name, func_args, knowledge_path=knowledge_path, mcp_executor=mcp_executor
            )
            if func_name == "knowledge_base":
                knowledge_updated = True

            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "tool", "content": result_text, "tool_name": func_name})

        if tool_calls:
            try:
                final = ollama.chat(model=self.model, messages=messages)
                assistant_content = getattr(final.message, "content", "") or assistant_content
            except Exception as e:  # noqa: BLE001
                assistant_content = f"{assistant_content}\nTool follow-up error: {e}"

        return SkillResult(
            content=assistant_content,
            tool_calls=tool_calls,
            knowledge_updated=knowledge_updated,
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

    def _build_tool_specs(self) -> List[Dict[str, Any]]:
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