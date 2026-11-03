from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from Skills.app import SkillBase, SkillResult
except ImportError:
    # Fallback for local dev scan
    class SkillResult:  # type: ignore[no-redef]
        def __init__(self, content: str, tool_calls: Optional[list] = None,
                     knowledge_updated: bool = False, error: Optional[str] = None):
            self.content = content
            self.tool_calls = tool_calls or []
            self.knowledge_updated = knowledge_updated
            self.error = error

    class SkillBase:  # type: ignore[no-redef]
        name: str = ""
        description: str = ""
        system_prompt: str = ""
        skills: List[str] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _disk_numbers(disk: Any) -> Optional[Dict[str, float]]:
    """Extract free/total GB from an MCP disk result (string or dict)."""
    if isinstance(disk, dict):
        result = disk.get("result", disk)
        if isinstance(result, dict):
            free = result.get("free_gb")
            total = result.get("total_gb")
            if free is not None and total:
                return {"free_gb": float(free), "total_gb": float(total)}
        if isinstance(result, str):
            disk = result
    if isinstance(disk, str):
        m = re.search(r"(\d+)\s*GB free out of\s*(\d+)\s*GB", disk)
        if m:
            return {"free_gb": float(m.group(1)), "total_gb": float(m.group(2))}
    return None


class HomeKeeperSkill(SkillBase):
    name = "HomeKeeper (Uptime & Backups)"
    description = "Offline home server steward - monitors health, manages backups, and keeps your family data safe."

    system_prompt = """You are HomeKeeper, the steward of this offline Homee box.
                    You are frugal, practical, and proactive.
                    Priorities:
                    1) Keep the box alive
                    2) Keep data safe and offline-first
                    3) Be explainable.
                    You can use MCP tools: system/disk, system/shell, mcp/execute, knowledge/{bot_id}.
                    Always respond with concise, actionable status. If disk >80% or Ollama down, alert immediately.
                    Always use available MCP tools to fetch current system state instead of relying on training data.
                    Call tools via the tool-calling interface (do not print JSON).
                    You speak like a reliable home manager, not a chatbot.
                    """

    skills = [
        "system_health_check",
        "disk_cleanup",
        "ollama_manager",
        "vault_index",
        "backup_verifier",
        "family_briefing"
    ]

    # ════════════════════════════════════════════════════════════════
    # SkillBase contract
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
        task_lower = user_message.lower()

        if any(k in task_lower for k in ["health", "status", "disk", "ollama", "box"]):
            content, updated = self._health_check(mcp_executor, knowledge_path)
        elif any(k in task_lower for k in ["backup", "drive", "onedrive", "github", "vault", "sync"]):
            content, updated = self._vault_check(mcp_tools), False
        elif any(k in task_lower for k in ["clean", "prune", "free space"]):
            content, updated = self._cleanup(mcp_executor), False
        elif any(k in task_lower for k in ["brief", "summary", "what happened", "today"]):
            content, updated = self._family_briefing(knowledge_path), False
        else:
            # Default: health + briefing - the most common ask
            health, updated = self._health_check(mcp_executor, knowledge_path)
            briefing = self._family_briefing(knowledge_path)
            content = (
                f"{health}\n\n{briefing}\n\n"
                "_Try: 'check disk', 'verify backups', or 'clean old models'_"
            )
        return SkillResult(content=content, knowledge_updated=updated)

    # ════════════════════════════════════════════════════════════════
    # Checks (deterministic — no LLM required)
    # ════════════════════════════════════════════════════════════════

    def _health_check(self, mcp_executor, knowledge_path) -> "tuple[str, bool]":
        lines = ["## 🏠 HomeKeeper Health Check", f"_ {_now()} _", ""]
        knowledge_updated = False

        # Disk check via MCP
        if mcp_executor:
            disk = mcp_executor("system_disk", {})
            numbers = _disk_numbers(disk)
            if numbers and numbers["total_gb"]:
                used_pct = round((1 - numbers["free_gb"] / numbers["total_gb"]) * 100, 1)
                lines.append(f"- **Disk:** {numbers['free_gb']:g} GB free of {numbers['total_gb']:g} GB ({used_pct}% used)")
                if used_pct > 80:
                    lines.append(f"- ⚠️ **ALERT:** Disk at {used_pct}% — recommend cleanup (`clean old models`).")
            else:
                lines.append(f"- **Disk:** {disk.get('result', disk) if isinstance(disk, dict) else disk}")
        else:
            lines.append("- **Disk:** MCP executor not available — running in dry mode.")

        # Ollama check via shell MCP
        if mcp_executor:
            ollama = mcp_executor("system_shell", {
                "command": "systemctl is-active ollama 2>/dev/null || pgrep -x ollama >/dev/null && echo active || echo inactive"
            })
            out = str(ollama.get("result", "")) if isinstance(ollama, dict) else str(ollama)
            state = "active" if "active" in out.lower() and "inactive" not in out.lower() else "down"
            lines.append(f"- **Ollama:** {state}")
            if state == "down":
                lines.append("- ⚠️ **ALERT:** Ollama is down — bots cannot reason until it is back.")
        else:
            lines.append("- **Ollama:** dry mode (not checked).")

        # Persist to the knowledge base (offline RAG)
        if knowledge_path:
            try:
                path = Path(knowledge_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                existing = path.read_text(encoding="utf-8") if path.exists() else ""
                entry = f"\n## Health Check\n- {_now()}\n" + "\n".join(f"  {l}" for l in lines[3:] if l.startswith("- ")) + "\n"
                path.write_text(existing + entry, encoding="utf-8")
                knowledge_updated = True
            except OSError:
                pass

        return "\n".join(lines), knowledge_updated

    def _vault_check(self, mcp_tools: Optional[List[Dict[str, Any]]]) -> str:
        # Unified view of GitHub + GDrive + OneDrive MCPs from the bot's tools
        lines = ["## 🗄️ Vault Status", ""]
        tools = mcp_tools or []
        for src in ("github", "gdrive", "onedrive"):
            matches = [m.get("id", m.get("name", "")) for m in tools
                       if src in str(m.get("id", m.get("name", ""))).lower()]
            if matches:
                lines.append(f"- **{src}:** connected via `{', '.join(matches)}`")
            else:
                lines.append(f"- **{src}:** no MCP installed — add one from Settings → MCPs → Marketplace.")
        lines.append("")
        lines.append("_Backups stay offline-first; connect a vault MCP to verify remote copies._")
        return "\n".join(lines)

    def _cleanup(self, mcp_executor) -> str:
        lines = ["## 🧹 Cleanup", ""]
        if mcp_executor:
            res = mcp_executor("system_shell", {
                "command": "df -h / | tail -1; du -sh ~/.ollama/models 2>/dev/null || true"
            })
            out = str(res.get("result", "")) if isinstance(res, dict) else str(res)
            if out.strip():
                lines.append(f"```text\n{out.strip()[:2000]}\n```")
        else:
            lines.append("MCP executor not available — running in dry mode.")
        lines.append("")
        lines.append("**Recommendation:** `ollama rm <unused-model>` if disk is above 80%.")
        return "\n".join(lines)

    def _family_briefing(self, knowledge_path) -> str:
        entries = 0
        if knowledge_path:
            try:
                path = Path(knowledge_path)
                if path.exists():
                    entries = sum(1 for l in path.read_text(encoding="utf-8").splitlines()
                                  if l.startswith("## "))
            except OSError:
                pass
        return (
            "## 📋 Family Briefing\n\n"
            "Homee is running locally on the A1347. All data stays offline.\n"
            f"- **Knowledge entries:** {entries}\n"
            f"- **As of:** {_now()}"
        )


# Homee scans for SkillBase subclasses - this registers it
AGENT = HomeKeeperSkill()
