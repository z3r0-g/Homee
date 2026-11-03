"""Skill utility tests (PLAN.md Ch 12) — what each local skill must be good at.

Contract mechanics live in test_skill_contract.py; these tests pin each
skill's usefulness. All external dependencies (Ollama, Docker, network, MCP
service) are mocked or absent.
"""

from __future__ import annotations

import pytest

from Skills.local import burgundy, homekeeper, mastodon, shipwright
from Skills.local.burgundy import BurgundySkill
from Skills.local.mastodon import DemoSkill
from Skills.local.homekeeper import HomeKeeperSkill
from Skills.local.shipwright import ShipwrightSkill


# ════════════════════════════════════════════════════════════════
# Demo (System Skill)
# ════════════════════════════════════════════════════════════════

def test_demo_health_report_sections():
    report = mastodon.render_health_report()
    assert "Server Health Report" in report
    assert "### 💾 Disk" in report
    assert "### 🧠 Memory" in report
    assert "### ⚡ CPU" in report
    assert "GB" in report


def test_demo_process_snapshot_never_uses_top(monkeypatch):
    calls = []

    def _spy(command):
        calls.append(command)
        if "htop" in command:
            return ""  # htop missing → psutil fallback summary
        if command.startswith("ps "):
            return "100 vscode 3.2 1.1 102400 01:02:03 code-server"
        return ""

    monkeypatch.setattr(mastodon, "run_shell", _spy)
    out = mastodon.get_process_snapshot()
    assert "Process Snapshot" in out
    assert "code-server" in out
    assert all("top" not in c or "htop" in c for c in calls), "top must never be invoked"


def test_demo_parse_ps_rows_bad_lines_skipped():
    rows = mastodon._parse_ps_rows("garbage\n\n1 root 0.0 0.1 2048 00:01 init", 5)
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
# HomeKeeper (Uptime & Backups)
# ════════════════════════════════════════════════════════════════

def _executor(disk="42 GB free out of 233 GB", shell="active"):
    def _exec(mcp_id, args):
        if mcp_id == "system_disk":
            return {"result": disk}
        if mcp_id == "system_shell":
            return {"result": shell}
        return {"error": f"unknown {mcp_id}"}
    return _exec


def test_homekeeper_disk_alert_over_80():
    skill = HomeKeeperSkill()
    result = skill.execute("check disk", mcp_executor=_executor())
    assert "ALERT" in result.content  # 42/233 free → 82% used
    assert "82.0%" in result.content


def test_homekeeper_no_alert_when_disk_ok():
    skill = HomeKeeperSkill()
    result = skill.execute("check disk", mcp_executor=_executor(disk="200 GB free out of 233 GB"))
    assert "ALERT" not in result.content.split("Ollama")[0]


def test_homekeeper_ollama_down_alert():
    skill = HomeKeeperSkill()
    result = skill.execute("status", mcp_executor=_executor(shell="inactive"))
    assert "Ollama is down" in result.content


def test_homekeeper_health_persists_to_knowledge(tmp_path):
    skill = HomeKeeperSkill()
    kb = tmp_path / "kb.md"
    result = skill.execute("health", mcp_executor=_executor(), knowledge_path=str(kb))
    assert result.knowledge_updated is True
    assert "Health Check" in kb.read_text(encoding="utf-8")


def test_homekeeper_vault_reflects_assigned_mcps():
    skill = HomeKeeperSkill()
    result = skill.execute("verify backups", mcp_tools=[{"id": "github"}])
    assert "github:** connected" in result.content
    assert "gdrive:** no MCP" in result.content


def test_homekeeper_default_route_and_dry_mode():
    skill = HomeKeeperSkill()
    result = skill.execute("hello there")  # no executor, no kb
    assert result.error is None
    assert "Health Check" in result.content
    assert "Family Briefing" in result.content
    assert "dry mode" in result.content


# ════════════════════════════════════════════════════════════════
# Shipwright (SRE Skill)
# ════════════════════════════════════════════════════════════════

def test_shipwright_docker_unavailable_plain_error(monkeypatch):
    monkeypatch.setattr(shipwright, "_get_docker_client", lambda: None)
    out = shipwright.get_system_health()
    assert "Docker daemon communication error" in out
    out = shipwright.fetch_container_logs("web")
    assert "Docker daemon communication error" in out


def test_shipwright_destructive_tool_guardrail():
    assert shipwright.validate_safety("prune_volumes", {}) is False
    assert shipwright.validate_safety("prune_volumes", {"confirmed_by_admin": True}) is True
    assert shipwright.validate_safety("fetch_container_logs", {}) is True


def test_shipwright_log_tail_and_truncation(monkeypatch):
    class _Container:
        def logs(self, tail=100, timestamps=True):
            assert tail == 5
            return b"\n".join(b"line %d" % i for i in range(5000))

    class _Client:
        class containers:
            @staticmethod
            def get(name):
                return _Container()

    monkeypatch.setattr(shipwright, "_get_docker_client", lambda: _Client())
    out = shipwright.fetch_container_logs("web", tail=5)
    assert "Logs for `web`" in out
    assert len(out) < 3200  # capped payload


def test_shipwright_health_counts(monkeypatch):
    class _C:
        def __init__(self, name, status):
            self.name = name
            self.status = status

    class _Client:
        class containers:
            @staticmethod
            def list(all=True):
                return [_C("a", "running"), _C("b", "running"), _C("c", "exited")]

    monkeypatch.setattr(shipwright, "_get_docker_client", lambda: _Client())
    out = shipwright.get_system_health()
    assert "Total Containers:** 3" in out
    assert "Running:** 2" in out
    assert "c" in out
