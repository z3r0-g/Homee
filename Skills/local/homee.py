#!/usr/bin/env python3
"""
Homee — Uptime, Backups & Container Reliability Skill.

One steward for the offline Homee box: server health (disk/memory/CPU),
live process snapshots, Docker container health and log inspection, backup
verification, and family briefings. Deterministic — replies without an LLM.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from Skills.app import SkillBase, SkillResult, get_disk_space, run_shell
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

    def get_disk_space() -> str:  # type: ignore[no-redef]
        total, used, free = shutil.disk_usage("/")
        return f"{free / 2**30:.0f} GB free out of {total / 2**30:.0f} GB"

    def run_shell(command: str) -> str:  # type: ignore[no-redef]
        import subprocess

        try:
            out = subprocess.run(command, shell=True, capture_output=True,
                                 text=True, timeout=15)
            return (out.stdout or out.stderr or "").strip()
        except Exception as e:  # noqa: BLE001
            return f"Shell error: {e}"

# Docker import is lazy — avoid hard failure when docker SDK is not installed
# (the _get_docker_client() function already handles the fallback)
try:
    import docker
except ImportError:  # pragma: no cover - docker is optional
    docker = None

_GB = 2 ** 30
_ANSI_RE = re.compile(r"\x1b(?:[()=][A-Za-z0-9]|\[[0-9;?]*[a-zA-Z])")
_PROC_HEADERS = ["PID", "USER", "CPU%", "MEM%", "RSS", "ELAPSED", "COMMAND"]

CONFIG_PATH = "homee.json"
if not os.path.exists(CONFIG_PATH):
    # Legacy guardrails files
    for _legacy in ("homekeeper.json", "shipwright.json"):
        if os.path.exists(_legacy):
            CONFIG_PATH = _legacy
            break
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
else:
    CONFIG = {
        "guardrails": {
            "destructive_tools": ["prune_volumes", "force_remove_container"]
        }
    }


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


# ══════════════════════════════════════════════════════════════════
# Formatting helpers (produce terminal- and UI-friendly markdown)
# ══════════════════════════════════════════════════════════════════


def _bar(percent: float, width: int = 18) -> str:
    """Inline block-char progress bar that looks good in code blocks and chat."""
    percent = max(0.0, min(100.0, float(percent)))
    filled = int(round(width * percent / 100))
    return "█" * filled + "░" * (width - filled)


def _fmt_gb(num_bytes: int) -> str:
    return f"{num_bytes / _GB:.1f} GB"


def _human_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    parts: List[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    if not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _ascii_table(headers: List[str], rows: List[List[str]]) -> str:
    """Render an aligned text table (for fenced code blocks)."""
    columns = list(zip(*([headers] + rows))) if rows else list(zip(*[headers]))
    widths = [max(len(str(c)) for c in col) for col in columns]
    fmt = lambda row: "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row))
    lines = [fmt(headers), "  ".join("-" * w for w in widths)]
    for row in rows:
        lines.append(fmt(row))
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# Server health metrics
# ══════════════════════════════════════════════════════════════════


def _cpu_with_trend() -> Tuple[float, str]:
    """Sample CPU twice to derive a real, instantaneous trend."""
    import psutil

    psutil.cpu_percent(interval=None)  # prime / seed the baseline
    time.sleep(0.2)
    first = psutil.cpu_percent(interval=None)
    time.sleep(0.4)
    second = psutil.cpu_percent(interval=None)
    if second > first + 2:
        trend = "rising"
    elif second < first - 2:
        trend = "falling"
    else:
        trend = "stable"
    return round(second, 1), trend


def get_server_health() -> Dict[str, Any]:
    """Current server health metrics: disk / memory / CPU / load / trends.

    The returned dict powers the UI bot-detail "Server Health" panel and the
    ``/api/server-health`` endpoint, so its shape is kept stable — existing
    keys are preserved and any new keys are strictly additive.
    """
    import psutil

    total, used, free = shutil.disk_usage("/")
    mem = psutil.virtual_memory()
    cpu_percent, cpu_trend = _cpu_with_trend()
    load = psutil.getloadavg()  # (1, 5, 15 min)
    uptime_seconds = int(time.time() - psutil.boot_time())

    return {
        "hostname": socket.gethostname(),
        "cores": psutil.cpu_count(logical=True) or 1,
        "load": [round(x, 2) for x in load],
        "uptime_seconds": uptime_seconds,
        "uptime_human": _human_duration(uptime_seconds),
        "disk": {
            "total_gb": round(total / _GB, 1),
            "used_gb": round(used / _GB, 1),
            "free_gb": round(free / _GB, 1),
            "usage_percent": round((used / total) * 100, 1) if total else 0.0,
            "trend": "stable",
        },
        "memory": {
            "total_gb": round(mem.total / _GB, 1),
            "available_gb": round(mem.available / _GB, 1),
            "free_gb": round(mem.free / _GB, 1),
            "usage_percent": round(mem.percent, 1),
            "trend": "stable",
        },
        "cpu": {
            "percent": cpu_percent,
            "trend": cpu_trend,
            "cores_logical": psutil.cpu_count(logical=True) or 1,
        },
    }


def render_health_report(health: Optional[Dict[str, Any]] = None) -> str:
    """Pretty markdown report of disk / memory / CPU / load."""
    h = health if health is not None else get_server_health()
    d, m, c = h["disk"], h["memory"], h["cpu"]
    load = h.get("load", [0.0, 0.0, 0.0])

    lines: List[str] = []
    lines.append("## 🖥️  Server Health Report")
    lines.append("")
    lines.append(
        f"**Host** `{h.get('hostname', '?')}`  ·  "
        f"**Uptime** `{h.get('uptime_human', '?')}`  ·  "
        f"**Cores** `{h.get('cores', '?')}`"
    )
    lines.append(
        f"**Load average (1 / 5 / 15 min)** `{load[0]}` · `{load[1]}` · `{load[2]}`"
    )
    lines.append("")
    lines.append("### 💾 Disk")
    lines.append(
        f"- **Total:** `{d['total_gb']:.1f} GB`  ·  "
        f"**Used:** `{d['used_gb']:.1f} GB`  ·  **Free:** `{d['free_gb']:.1f} GB`"
    )
    lines.append(
        f"- **Usage:** `{_bar(d['usage_percent'])}` **{d['usage_percent']}%**  ·  trend: {d['trend']}"
    )
    lines.append("")
    lines.append("### 🧠 Memory")
    lines.append(
        f"- **Total:** `{m['total_gb']:.1f} GB`  ·  "
        f"**Available:** `{m.get('available_gb', 0):.1f} GB`  ·  "
        f"**Free:** `{m['free_gb']:.1f} GB`"
    )
    lines.append(
        f"- **Usage:** `{_bar(m['usage_percent'])}` **{m['usage_percent']}%**  ·  trend: {m['trend']}"
    )
    lines.append("")
    lines.append("### ⚡ CPU")
    lines.append(
        f"- **Usage:** `{_bar(c['percent'])}` **{c['percent']}%**  ·  trend: {c['trend']}"
    )
    lines.append("")
    lines.append(
        f"_Trends — CPU: {c['trend']}, memory: {m['trend']}, disk: {d['trend']}_"
    )
    lines.append("")
    return "\n".join(lines)


def render_trend_report(health: Optional[Dict[str, Any]] = None) -> str:
    """Pretty markdown summary of resource trends and load average."""
    h = health if health is not None else get_server_health()
    d, m, c = h["disk"], h["memory"], h["cpu"]
    load = h.get("load", [0.0, 0.0, 0.0])

    lines: List[str] = []
    lines.append("## 📈 Server Trending")
    lines.append("")
    lines.append(
        f"**Load average:** `{load[0]}` · `{load[1]}` · `{load[2]}`  ·  "
        f"**Uptime** `{h.get('uptime_human', '?')}`"
    )
    lines.append("")
    lines.append("### Resource trends")
    lines.append(
        f"- **CPU** — `{c['percent']}%` `{_bar(c['percent'])}` — **{c['trend']}**"
    )
    lines.append(
        f"- **Memory** — `{m['usage_percent']}%` `{_bar(m['usage_percent'])}` — **{m['trend']}**"
    )
    lines.append(
        f"- **Disk** — `{d['usage_percent']}%` `{_bar(d['usage_percent'])}` — **{d['trend']}**"
    )
    lines.append("")
    lines.append(
        "_CPU trend is a real two-sample reading; memory and disk report "
        "`stable` (no history is retained between calls)._"
    )
    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# Live process snapshot (htop-powered, never top)
# ══════════════════════════════════════════════════════════════════


def _extract_htop_summary(raw: str) -> str:
    """Pull htop's system header (Tasks / Load average / Uptime / Mem / Swap)."""
    text = _ANSI_RE.sub("", raw).replace("\r", "\n")
    lines_out: List[str] = []
    seen = set()
    for line in text.split("\n"):
        s = line.strip()
        if not s or s in seen:
            continue
        if (
            "Tasks:" in s
            or "Load average" in s
            or "Uptime:" in s
            or "Mem[" in s
            or "Swp[" in s
        ):
            lines_out.append(s)
            seen.add(s)
    return "\n".join(lines_out)


def _psutil_summary_line() -> str:
    """Fallback system summary when htop is unavailable (still never uses top)."""
    import psutil

    load = psutil.getloadavg()
    up = int(time.time() - psutil.boot_time())
    mem = psutil.virtual_memory()
    return (
        f"Load average: {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}  "
        f"Uptime: {_human_duration(up)}  "
        f"Mem: {_fmt_gb(mem.used)}/{_fmt_gb(mem.total)} ({mem.percent}%)"
    )


def _parse_ps_rows(ps_out: str, limit: int) -> List[List[str]]:
    """Parse `ps` columns into rows for the aligned table."""
    rows: List[List[str]] = []
    for line in ps_out.splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 6)
        if len(parts) < 6:
            continue
        pid, user, pcpu, pmem, rss_kb, etime = parts[:6]
        comm = parts[6] if len(parts) > 6 else ""
        try:
            rss_mb = f"{int(rss_kb) / 1024:.0f}M"
        except ValueError:
            rss_mb = "-"
        rows.append([pid, user, f"{pcpu}%", f"{pmem}%", rss_mb, etime, comm[:45]])
        if len(rows) >= limit:
            break
    return rows


def get_process_snapshot(limit: int = 12) -> str:
    """Pretty markdown snapshot of live processes, powered by ``htop``.

    Uses ``htop -C -n 1`` (the modern, colour-friendly alternative to ``top``)
    for the authoritative system summary, and a clean ``ps`` table of the
    busiest processes. ``htop``'s TUI rows don't split into columns cleanly, so
    ``ps`` provides a machine-parseable process table — ``top`` is never used.
    Falls back to ``psutil`` metrics if ``htop`` isn't installed.
    """
    raw = run_shell("COLUMNS=400 htop -C -n 1")
    summary = _extract_htop_summary(raw)
    if not summary:
        summary = _psutil_summary_line()

    ps_out = run_shell(
        "ps -eo pid,user,pcpu,pmem,rss,etime,comm --sort=-pcpu --no-headers"
    )
    rows = _parse_ps_rows(ps_out, limit)

    lines: List[str] = []
    lines.append("## 🖥️  Process Snapshot")
    lines.append("")
    lines.append("_Live host overview — single frame via `htop -C -n 1` (never `top`)._")
    lines.append("")
    lines.append("### System summary")
    lines.append("```")
    lines.append(summary)
    lines.append("```")
    lines.append("")
    lines.append(f"### Top {limit} processes by CPU")
    if rows:
        lines.append("```")
        lines.append(_ascii_table(_PROC_HEADERS, rows))
        lines.append("```")
    else:
        lines.append("_No process data available._")
    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# Docker container health & logs (guardrailed)
# ══════════════════════════════════════════════════════════════════


def _get_docker_client():
    try:
        return docker.from_env()
    except Exception:  # noqa: BLE001
        return None


def validate_safety(tool_name: str, args: Dict[str, Any]) -> bool:
    destructive = CONFIG.get("guardrails", {}).get("destructive_tools", [])
    if tool_name in destructive and not args.get("confirmed_by_admin", False):
        return False
    return True


def fetch_container_logs(container_name: str = "", tail: int = 100) -> str:
    """Retrieve recent stdout/stderr logs from a specific Docker container."""
    client = _get_docker_client()
    if not client:
        return "Docker daemon communication error: Unable to connect to Docker socket."
    if not container_name:
        return "Please specify a container name to fetch logs."
    try:
        container = client.containers.get(container_name)
        logs = container.logs(tail=tail, timestamps=True).decode("utf-8")
        return f"### Logs for `{container_name}` (Last {tail} lines):\n```text\n{logs[-3000:]}\n```"
    except Exception as e:
        return f"Error fetching logs for {container_name}: {str(e)}"


def get_system_health() -> str:
    """Get overall status and container health counts for the host."""
    client = _get_docker_client()
    if not client:
        return "Docker daemon communication error: Unable to connect to Docker socket."
    try:
        containers = client.containers.list(all=True)
        running = sum(1 for c in containers if c.status == "running")
        unhealthy = [c.name for c in containers if c.status != "running"]

        report = f"- **Total Containers:** {len(containers)}\n- **Running:** {running}\n"
        if unhealthy:
            report += f"- ⚠️ **Stopped/Unhealthy:** {', '.join(unhealthy)}"
        else:
            report += "- ✅ All managed containers operating normally."
        return report
    except Exception as e:
        return f"Docker daemon communication error: {str(e)}"


# Top-level tool wrappers and aliases
def get_logs(container_name: str = "", tail: int = 100) -> str:
    """Alias for fetch_container_logs."""
    return fetch_container_logs(container_name=container_name, tail=tail)


def get_container_logs(container_name: str = "", tail: int = 100) -> str:
    """Alias for fetch_container_logs."""
    return fetch_container_logs(container_name=container_name, tail=tail)


def system_health() -> str:
    """Alias for get_system_health."""
    return get_system_health()


def container_health() -> str:
    """Alias for get_system_health."""
    return get_system_health()


# ══════════════════════════════════════════════════════════════════
# Skill definition
# ══════════════════════════════════════════════════════════════════


class HomeeSkill(SkillBase):
    name = "Homee (Uptime & Backups)"
    description = (
        "Offline home server steward - monitors health, manages backups, "
        "watches Docker containers, and keeps your family data safe."
    )

    system_prompt = """You are Homee, the steward of this offline home server —
                    uptime steward, site reliability engineer, and system monitor in one.
                    You are frugal, practical, and proactive.
                    Priorities:
                    1) Keep the box alive
                    2) Keep data safe and offline-first
                    3) Be explainable.
                    You can use MCP tools: system/disk, system/shell, mcp/execute, knowledge/{bot_id}.
                    You also have built-in tools for server health (disk/memory/CPU),
                    live process snapshots (via htop, never top), and Docker
                    container health and logs.
                    Always respond with concise, actionable status. If disk >80% or Ollama down, alert immediately.
                    Always use available tools and MCPs to fetch current system state instead of relying on training data.
                    Call tools via the tool-calling interface (do not print JSON).
                    Never perform destructive actions (e.g. pruning volumes or
                    force-removing containers) without explicit admin confirmation.
                    You speak like a reliable home manager, not a chatbot.
                    """

    skills = [
        "system_health_check",
        "disk_cleanup",
        "ollama_manager",
        "vault_index",
        "backup_verifier",
        "family_briefing",
        "server_health",
        "process_snapshot",
        "shell_access",
        "container_health",
        "log_inspection",
    ]

    tools = [
        get_disk_space,
        run_shell,
        get_server_health,
        render_health_report,
        render_trend_report,
        get_process_snapshot,
        fetch_container_logs,
        get_system_health,
        get_logs,
        get_container_logs,
        system_health,
        container_health,
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

        if any(k in task_lower for k in ["container", "docker", "logs"]):
            content, updated = self._container_check(), False
        elif any(k in task_lower for k in ["process", "procs", "htop"]):
            content, updated = get_process_snapshot(), False
        elif "trend" in task_lower:
            content, updated = render_trend_report(), False
        elif any(k in task_lower for k in ["health", "status", "disk", "ollama", "box"]):
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
                "_Try: 'check disk', 'verify backups', 'container health', "
                "'process snapshot', or 'clean old models'_"
            )
        return SkillResult(content=content, knowledge_updated=updated)

    # ════════════════════════════════════════════════════════════════
    # Checks (deterministic — no LLM required)
    # ════════════════════════════════════════════════════════════════

    def _health_check(self, mcp_executor, knowledge_path) -> "tuple[str, bool]":
        lines = ["## 🏠 Homee Health Check", f"_ {_now()} _", ""]
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
# Ollama check via shell MCP, falling back to local subprocess
        # Fixed: use ps-based check since /bin/sh is dash which may not have pgrep
        if mcp_executor:
            ollama = mcp_executor("system_shell", {
                "command": "ps -eo comm | grep -q ollama && echo active || echo inactive"
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

    def _container_check(self) -> str:
        lines = ["## 🐳 Container Health", ""]
        lines.append(get_system_health())
        lines.append("")
        lines.append("_Ask for `logs <container>` to inspect a container; "
                     "destructive actions need explicit admin confirmation._")
        return "\n".join(lines)

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
AGENT = HomeeSkill()

# Convenient aliases for app registration and importing
Homee = HomeeSkill
HomeKeeperSkill = HomeeSkill  # backwards-compatible alias
HomeKeeper = HomeeSkill
ShipwrightSkill = HomeeSkill
DemoSkill = HomeeSkill


# ══════════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════════

_BANNER = """
╔══════════════════════════════════════════════════════════╗
║ 🏠 Homee — uptime, backups & container reliability      ║
╚══════════════════════════════════════════════════════════╝
"""

_HELP = """\
Available commands:
  health / status   Health check (disk + Ollama via MCP when available)
  report            Server health report (disk, memory, CPU, load)
  trend             Trending summary (CPU/memory/disk trends + load average)
  procs / htop      Live process snapshot (via htop, never top)
  containers        Docker container health
  logs <name>       Recent logs for a Docker container
  help              Show this help
  exit / quit       Leave the session

Anything else is answered by the deterministic steward router.
"""


if __name__ == "__main__":
    skill = HomeeSkill()
    print(_BANNER)
    print("Commands:  health  report  trend  procs  containers  logs <name>  help  exit")

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if not user_input:
            continue
        cmd = user_input.lower()
        if cmd in ("exit", "quit"):
            break
        if cmd == "help":
            print(_HELP)
            continue
        if cmd == "clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue
        if cmd == "report":
            print("\n" + render_health_report())
            continue
        if cmd == "trend":
            print("\n" + render_trend_report())
            continue
        if cmd in ("procs", "processes", "htop", "snapshot"):
            print("\n" + get_process_snapshot())
            continue
        if cmd == "containers":
            print("\n" + skill._container_check())
            continue
        if cmd.startswith("logs"):
            parts = user_input.split(None, 1)
            print("\n" + fetch_container_logs(parts[1] if len(parts) > 1 else ""))
            continue
        # Otherwise: hand the message to the deterministic steward router.
        result = skill.execute(user_input)
        print("\nHomee: " + result.content)
