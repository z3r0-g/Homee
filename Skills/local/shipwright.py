#!/usr/bin/env python3
"""
Shipwright SRE Skill — Autonomous Infrastructure & Container Reliability Skill.

Provides container health diagnostics, log inspection, and system monitoring
for multi-host Docker environments.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

# Docker import is lazy — avoid hard failure when docker SDK is not installed
# (the _get_docker_client() function already handles the fallback)
try:
    import docker
except ImportError:  # pragma: no cover - docker is optional
    docker = None

from Skills.app import SkillBase

CONFIG_PATH = "shipwright.json"
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
else:
    CONFIG = {
        "guardrails": {
            "destructive_tools": ["prune_volumes", "force_remove_container"]
        }
    }


def _get_docker_client():
    try:
        return docker.from_env()
    except Exception as e:
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


class ShipwrightSkill(SkillBase):
    name = "Shipwright (SRE Skill)"
    description = "An autonomous Site Reliability Engineer skill that monitors, diagnoses, and maintains local container infrastructure."
    system_prompt = (
        "You are Shipwright, an autonomous Site Reliability Engineer skill designed "
        "to monitor, diagnose, and maintain multi-host Docker environments. You "
        "prioritize safety, local-first execution, and clear technical communication. "
        "Always use your available infrastructure tools to check container state or "
        "fetch log traces before drawing conclusions. Never perform destructive "
        "actions without explicit admin confirmation."
    )
    tools = [
        fetch_container_logs,
        get_system_health,
        get_logs,
        get_container_logs,
        system_health,
        container_health,
    ]


# Convenient aliases for app registration and importing
ShipwrightSREAgent = ShipwrightSkill
DeckhandSREAgent = ShipwrightSkill
SREAgent = ShipwrightSkill
Shipwright = ShipwrightSkill


if __name__ == "__main__":
    skill = ShipwrightSkill()
    print("Shipwright SRE Skill Online. Type 'exit' to quit.")
    messages = [{"role": "system", "content": skill.system_prompt}]
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ("exit", "quit"):
                break
            result = skill.execute(user_input, conversation_history=messages)
            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "assistant", "content": result.content})
            print(f"\nAgent: {result.content}")
        except KeyboardInterrupt:
            break