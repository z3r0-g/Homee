"""Skill utility tests (PLAN.md Ch 12) — what each local skill must be good at.

Contract mechanics live in test_skill_contract.py; these tests pin each
skill's usefulness. All external dependencies (Ollama, Docker, network, MCP
service) are mocked or absent.
"""

from __future__ import annotations

import pytest

from Skills.local import burgundy, homee
from Skills.local.burgundy import BurgundySkill
from Skills.local.homee import HomeeSkill


# ════════════════════════════════════════════════════════════════
# Homee — server health & process snapshot
# ════════════════════════════════════════════════════════════════

def test_homee_health_report_sections():
    report = homee.render_health_report()
    assert "Server Health Report" in report
    assert "### 💾 Disk" in report
    assert "### 🧠 Memory" in report
    assert "### ⚡ CPU" in report
    assert "GB" in report


def test_homee_process_snapshot_never_uses_top(monkeypatch):
    calls = []

    def _spy(command):
        calls.append(command)
        if "htop" in command:
            return ""  # htop missing → psutil fallback summary
        if command.startswith("ps "):
            return "100 vscode 3.2 1.1 102400 01:02:03 code-server"
        return ""

    monkeypatch.setattr(homee, "run_shell", _spy)
    out = homee.get_process_snapshot()
    assert "Process Snapshot" in out
    assert "code-server" in out
    assert all("top" not in c or "htop" in c for c in calls), "top must never be invoked"


def test_homee_parse_ps_rows_bad_lines_skipped():
    rows = homee._parse_ps_rows("garbage\n\n1 root 0.0 0.1 2048 00:01 init", 5)
    assert rows == [["1", "root", "0.0%", "0.1%", "2M", "00:01", "init"]]


# ════════════════════════════════════════════════════════════════
# Burgundy (Weather Skill)
# ════════════════════════════════════════════════════════════════

def test_burgundy_location_precedence():
    resolve = burgundy._resolve_location
    assert resolve(location="San Diego", zip_code="92101") == "92101"  # zip wins
    assert resolve(location="San Diego", latitude=32.7, longitude=-117.1) == "32.7,-117.1"
    assert resolve(location="San Diego") == "San Diego"
    assert resolve() == ""


def test_burgundy_tool_dispatch_weather(monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            return {"current_condition": [{"temp_F": "70", "weatherDesc": [{"value": "Sunny"}]}],
                    "nearest_area": [{"areaName": [{"value": "San Diego"}]}],
                    "weather": []}

    monkeypatch.setattr(burgundy.requests, "get", lambda *a, **k: _Resp())
    skill = BurgundySkill()
    out = skill._dispatch_tool("get_weather_forecast", {"zip_code": "92101"})
    assert "San Diego" in out
    assert "Stay classy" in out


# ════════════════════════════════════════════════════════════════
# Homee (Uptime & Backups)
# ════════════════════════════════════════════════════════════════

def _executor(disk="42 GB free out of 233 GB", shell="active"):
    def _exec(mcp_id, args):
        if mcp_id == "system_disk":
            return {"result": disk}
        if mcp_id == "system_shell":
            return {"result": shell}
        return {"error": f"unknown {mcp_id}"}
    return _exec


def test_homee_disk_alert_over_80():
    skill = HomeeSkill()
    result = skill.execute("check disk", mcp_executor=_executor())
    assert "ALERT" in result.content  # 42/233 free → 82% used
    assert "82.0%" in result.content


def test_homee_no_alert_when_disk_ok():
    skill = HomeeSkill()
    result = skill.execute("check disk", mcp_executor=_executor(disk="200 GB free out of 233 GB"))
    assert "ALERT" not in result.content.split("Ollama")[0]


def test_homee_ollama_down_alert():
    skill = HomeeSkill()
    result = skill.execute("status", mcp_executor=_executor(shell="inactive"))
    assert "Ollama is down" in result.content


def test_homee_health_persists_to_knowledge(tmp_path):
    skill = HomeeSkill()
    kb = tmp_path / "kb.md"
    result = skill.execute("health", mcp_executor=_executor(), knowledge_path=str(kb))
    assert result.knowledge_updated is True
    assert "Health Check" in kb.read_text(encoding="utf-8")


def test_homee_vault_reflects_assigned_mcps():
    skill = HomeeSkill()
    result = skill.execute("verify backups", mcp_tools=[{"id": "github"}])
    assert "github:** connected" in result.content
    assert "gdrive:** no MCP" in result.content


def test_homee_default_route_and_dry_mode():
    skill = HomeeSkill()
    result = skill.execute("hello there")  # no executor, no kb
    assert result.error is None
    assert "Health Check" in result.content
    assert "Family Briefing" in result.content
    assert "dry mode" in result.content


# ════════════════════════════════════════════════════════════════
# Homee — container reliability (SRE)
# ════════════════════════════════════════════════════════════════

def test_homee_docker_unavailable_plain_error(monkeypatch):
    monkeypatch.setattr(homee, "_get_docker_client", lambda: None)
    out = homee.get_system_health()
    assert "Docker daemon communication error" in out
    out = homee.fetch_container_logs("web")
    assert "Docker daemon communication error" in out


def test_homee_destructive_tool_guardrail():
    assert homee.validate_safety("prune_volumes", {}) is False
    assert homee.validate_safety("prune_volumes", {"confirmed_by_admin": True}) is True
    assert homee.validate_safety("fetch_container_logs", {}) is True


def test_homee_log_tail_and_truncation(monkeypatch):
    class _Container:
        def logs(self, tail=100, timestamps=True):
            assert tail == 5
            return b"\n".join(b"line %d" % i for i in range(5000))

    class _Client:
        class containers:
            @staticmethod
            def get(name):
                return _Container()

    monkeypatch.setattr(homee, "_get_docker_client", lambda: _Client())
    out = homee.fetch_container_logs("web", tail=5)
    assert "Logs for `web`" in out
    assert len(out) < 3200  # capped payload


def test_homee_health_counts(monkeypatch):
    class _C:
        def __init__(self, name, status):
            self.name = name
            self.status = status

    class _Client:
        class containers:
            @staticmethod
            def list(all=True):
                return [_C("a", "running"), _C("b", "running"), _C("c", "exited")]

    monkeypatch.setattr(homee, "_get_docker_client", lambda: _Client())
    out = homee.get_system_health()
    assert "Total Containers:** 3" in out
    assert "Running:** 2" in out
    assert "c" in out
