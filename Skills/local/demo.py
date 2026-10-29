"""Example Skill — a local system assistant with disk and shell tools.

This is the reference implementation of a skill. Bots created in
the UI can be assigned this (or any registered) Skill to embody its skill set.
It provides server health reports, a live process snapshot (via ``htop``,
never ``top``), and trending information — all presented as readable markdown.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import time
from typing import Any, Dict, List, Optional, Tuple

from Skills.app import SkillBase, get_disk_space, run_shell

_GB = 2 ** 30
_ANSI_RE = re.compile(r"\x1b(?:[()=][A-Za-z0-9]|\[[0-9;?]*[a-zA-Z])")
_PROC_HEADERS = ["PID", "USER", "CPU%", "MEM%", "RSS", "ELAPSED", "COMMAND"]


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
# Skill definition
# ══════════════════════════════════════════════════════════════════


class DemoSkill(SkillBase):
    name = "Demo (System Skill)"
    description = (
        "A helpful local system assistant that checks disk space, runs shell "
        "commands, and reports server health and live process snapshots via htop."
    )
    system_prompt = (
        "You are a helpful local system assistant. You have access to tools for "
        "checking disk space, running shell commands, and fetching a live process "
        "snapshot (via htop, never top). When the user asks about the system, use "
        "these tools. Provide server health reports and trending information when "
        "requested. Be concise, safe, and present results as readable markdown."
    )
    tools = [get_disk_space, get_process_snapshot, run_shell]


# Backwards-compatible aliases
DemoSystemSkill = DemoSkill
SystemSkill = DemoSkill
Demo = DemoSkill


# ══════════════════════════════════════════════════════════════════
# CLI entry point (original demo behaviour, upgraded UX)
# ══════════════════════════════════════════════════════════════════

_BANNER = """
╔══════════════════════════════════════════════════════════╗
║ 🖥️  Demo (System Skill) — local system assistant       ║
╚══════════════════════════════════════════════════════════╝
"""

_HELP = """\
Available commands:
  health / status   Server health report (disk, memory, CPU, load)
  trend             Trending summary (CPU/memory/disk trends + load average)
  procs / htop      Live process snapshot (via htop, never top)
  help              Show this help
  exit / quit       Leave the session

Anything else is sent to the local LLM agent as a normal chat message.
"""


if __name__ == "__main__":
    skill = DemoSkill()
    print(_BANNER)
    print("Commands:  health  trend  procs  help  exit")
    messages: list = [{"role": "system", "content": skill.system_prompt}]

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
        if cmd in ("health", "status"):
            print("\n" + render_health_report())
            continue
        if cmd == "trend":
            print("\n" + render_trend_report())
            continue
        if cmd in ("procs", "processes", "htop", "snapshot"):
            print("\n" + get_process_snapshot())
            continue
        # Otherwise: hand the message to the local LLM agent.
        try:
            result = skill.execute(user_input, conversation_history=messages)
            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "assistant", "content": result.content})
            print("\nAgent: " + result.content)
        except Exception as e:  # noqa: BLE001
            print(f"\n[Agent error: {e}]")
