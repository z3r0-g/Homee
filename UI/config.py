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
SKILLS_DIR = SERVICE_DIR.parent / "Skills"
MCPS_DIR = INSTANCES_DIR / "mcps"
SETTINGS_FILE = INSTANCES_DIR / "settings.json"

for _d in (INSTANCES_DIR, BOTS_DIR, KNOWLEDGE_DIR, SKILLS_DIR, MCPS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════
# Server settings
# ══════════════════════════════════════════════════════════════════

HOST = os.getenv("UI_HOST", "0.0.0.0")
PORT = int(os.getenv("UI_PORT", "5001"))
DEBUG = os.getenv("UI_DEBUG", "false").lower() == "true"

MCP_SERVICE_URL = os.getenv("MCP_SERVICE_URL", "http://localhost:5002")

# Default local model, RAM-aware (see UI/model_catalog.py): llama3.2:3b
# is the default for all hosts (the rule exists so big hosts could pick a
# larger model if needed, but 3B fits everywhere Homee runs).
# install.sh picks with the same rule. An explicit OLLAMA_MODEL env value
# always wins, and an existing settings.json keeps its saved local_model
# (disk wins over defaults on load), so this only affects fresh installs.
# NOTE on tags: in Ollama, "llama3.2" resolves to the :latest tag, which is
# NOT satisfied by an installed llama3.2:3b — always use a full tag.
def _default_ollama_model() -> str:
    env = os.getenv("OLLAMA_MODEL")
    if env:
        return env
    try:
        from .model_catalog import default_model, host_total_ram_gb
        return default_model(host_total_ram_gb())
    except Exception:  # noqa: BLE001 - psutil optional
        return "llama3.2:3b"


OLLAMA_MODEL = _default_ollama_model()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Default settings merged with any on-disk settings
DEFAULT_SETTINGS: Dict[str, Any] = {
    "llm": {
        "provider": "local",           # "local" | "remote"
        "local_model": OLLAMA_MODEL,
        "remote_base_url": "",
        "remote_api_key": "",
        "remote_model": "gpt-4o-mini",
        "mode": "local_local",         # "local_local" | "local_cloud" | "local_remote_local"
        "secondary_model": "",         # secondary model for dual-mode configs
        "secondary_base_url": "",      # secondary remote base URL (for cloud or remote local)
        "secondary_api_key": "",       # secondary API key (for cloud mode)
    },
    "scheduler": {
        "enabled": True,
        "tick_seconds": 30,
    },
    "mcp_service_url": MCP_SERVICE_URL,
    "skills": {
        "enabled": True,
        "git_url": "",  # optional git repo URL cloned into Skills/remote/<name>; empty => local /Skills only
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