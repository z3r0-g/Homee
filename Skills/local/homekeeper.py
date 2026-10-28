"""
HomeKeeper Skill — offline home server steward.
Monitors system health, manages backups, and keeps family data safe.
"""

from typing import Dict, Any, List
from datetime import datetime
import json
import os

try:
    from Skills.app import SkillBase
except ImportError:
    # Fallback for local dev scan
    class SkillBase:
        name: str = ""
        description: str = ""
        system_prompt: str = ""
        skills: List[str] = []
        def execute(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
            raise NotImplementedError

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

    def execute(self, task: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        context = context or {}
        mcp_client = context.get("mcp_client")
        bot_id = context.get("bot_id", "homekeeper")
        task_lower = task.lower()

        # Router for Homee's Bot Creation Flow
        if any(k in task_lower for k in ["health", "status", "disk", "ollama", "box"]):
            return self._health_check(mcp_client, bot_id)
        elif any(k in task_lower for k in ["backup", "drive", "onedrive", "github", "vault", "sync"]):
            return self._vault_check(mcp_client, bot_id)
        elif any(k in task_lower for k in ["clean", "prune", "free space"]):
            return self._cleanup(mcp_client, bot_id)
        elif any(k in task_lower for k in ["brief", "summary", "what happened", "today"]):
            return self._family_briefing(mcp_client, bot_id)
        else:
            # Default: health + briefing - the most common ask
            health = self._health_check(mcp_client, bot_id)
            briefing = self._family_briefing(mcp_client, bot_id)
            return {
                "status": "ok",
                "mode": "default",
                "health": health,
                "briefing": briefing,
                "suggestion": "Try: 'check disk', 'verify backups', or 'clean old models'"
            }

    def _health_check(self, mcp_client, bot_id) -> Dict[str, Any]:
        result = {"timestamp": datetime.now().isoformat(), "checks": {}}
        
        # Disk check via MCP
        try:
            if mcp_client:
                disk = mcp_client.get("/api/mcp/system/disk")
                result["checks"]["disk"] = disk
                # Alert logic for old hardware
                if isinstance(disk, dict) and disk.get("percent", 0) > 80:
                    result["alert"] = f"Disk at {disk.get('percent')}% - recommend cleanup"
            else:
                result["checks"]["disk"] = {"status": "mcp_client not injected - running in dry mode"}
        except Exception as e:
            result["checks"]["disk"] = {"error": str(e)}

        # Ollama check via shell MCP
        try:
            if mcp_client:
                ollama = mcp_client.post("/api/mcp/system/shell", {"command": "ollama list && systemctl is-active ollama || pgrep ollama"})
                result["checks"]["ollama"] = ollama
            else:
                result["checks"]["ollama"] = {"status": "dry mode"}
        except Exception as e:
            result["checks"]["ollama"] = {"error": str(e)}

        # Write to knowledge base for persistence (offline RAG)
        if mcp_client:
            try:
                mcp_client.post(f"/api/mcp/knowledge/{bot_id}", {
                    "entry": f"[health {result['timestamp']}] {json.dumps(result['checks'])}"
                })
            except:
                pass

        return result

    def _vault_check(self, mcp_client, bot_id) -> Dict[str, Any]:
        # Unified view of GitHub + GDrive + OneDrive MCPs
        sources = ["github", "gdrive", "onedrive"]
        inventory = {}
        for src in sources:
            try:
                if mcp_client:
                    items = mcp_client.get(f"/api/mcps")
                    inventory[src] = [m for m in items if src in m.get("id","").lower()] if isinstance(items, list) else items
                else:
                    inventory[src] = {"status": "dry mode"}
            except Exception as e:
                inventory[src] = {"error": str(e)}
        return {"vault_status": inventory, "timestamp": datetime.now().isoformat()}

    def _cleanup(self, mcp_client, bot_id) -> Dict[str, Any]:
        actions = []
        if mcp_client:
            # Example: prune old ollama models, clean /tmp, rotate logs
            cmd = "ollama list; du -sh ~/.ollama/models/* | sort -hr | head -10; df -h"
            res = mcp_client.post("/api/mcp/system/shell", {"command": cmd})
            actions.append(res)
        return {"cleanup_report": actions, "recommendation": "Consider: ollama rm <unused-model> if disk >80%"}

    def _family_briefing(self, mcp_client, bot_id) -> Dict[str, Any]:
        kb = {}
        if mcp_client:
            try:
                kb = mcp_client.get(f"/api/mcp/knowledge/{bot_id}")
            except:
                kb = {"entries": 0}
        return {
            "message": "Homee is running locally on A1347. All data stays offline.",
            "knowledge_entries": kb,
            "uptime": datetime.now().isoformat()
        }

# Homee scans for SkillBase subclasses - this registers it
AGENT = HomeKeeperSkill()