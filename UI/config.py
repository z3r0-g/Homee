"""UI Service configuration — paths, ports, and defaults."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

# ══════════════════════════════════════════════════════════════════
# Paths
# ══════════════════════════════════════════════════════════════════

SERVICE_DIR = Path(__file__).resolve().parent
SERVER_DIR = SERVICE_DIR.parent.parent

INSTANCES_DIR = Path(os.getenv("UI_INSTANCES_DIR", str(SERVICE_DIR / "instances")))
BOTS_DIR = INSTANCES_DIR / "bots"
KNOWLEDGE_DIR = INSTANCES_DIR / "knowledge"
PERSONALITIES_DIR = INSTANCES_DIR / "personalities"
MCPS_DIR = INSTANCES_DIR / "mcps"
SETTINGS_FILE = INSTANCES_DIR / "settings.json"
AGENTS_DIR = SERVER_DIR / "Agents"

for _d in (INSTANCES_DIR, BOTS_DIR, KNOWLEDGE_DIR, PERSONALITIES_DIR, MCPS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════
# Server settings
# ══════════════════════════════════════════════════════════════════

HOST = os.getenv("UI_HOST", "0.0.0.0")
PORT = int(os.getenv("UI_PORT", "5001"))
DEBUG = os.getenv("UI_DEBUG", "false").lower() == "true"

MCP_SERVICE_URL = os.getenv("MCP_SERVICE_URL", "http://localhost:5002")

# Must match install.sh's MODEL_NAME (qwen2.5:7b): in Ollama, "qwen2.5"
# resolves to the :latest tag, which is NOT satisfied by an installed
# qwen2.5:7b — the mismatch used to break fresh installs at first chat.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Default settings merged with any on-disk settings
DEFAULT_SETTINGS: Dict[str, Any] = {
    "llm": {
        "provider": "local",           # "local" | "remote"
        "local_model": OLLAMA_MODEL,
        "remote_base_url": "",
        "remote_api_key": "",
        "remote_model": "gpt-4o-mini",
    },
    "scheduler": {
        "enabled": True,
        "tick_seconds": 30,
    },
    "mcp_service_url": MCP_SERVICE_URL,
    "agents": {
        "enabled": True,
        "git_url": "",  # optional git repo URL cloned into Agents/remote/<name>; empty => local /Agents only
    },
}


def load_settings() -> Dict[str, Any]:
    """Load settings from disk, falling back to defaults."""
    import json

    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f:
                disk = json.load(f)
            # Deep-merge with defaults so missing keys are filled
            settings = json.loads(json.dumps(DEFAULT_SETTINGS))
            _deep_merge(settings, disk)
            return settings
        except (json.JSONDecodeError, OSError):
            pass
    return json.loads(json.dumps(DEFAULT_SETTINGS))


def save_settings(settings: Dict[str, Any]) -> None:
    """Persist settings to disk."""
    import json

    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    for key, value in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value