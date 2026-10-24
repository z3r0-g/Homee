"""MCP Service configuration — paths, ports, and defaults."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

# ══════════════════════════════════════════════════════════════════
# Paths
# ══════════════════════════════════════════════════════════════════

SERVICE_DIR = Path(__file__).resolve().parent
SERVER_DIR = SERVICE_DIR.parent.parent

INSTANCES_DIR = Path(os.getenv("MCP_INSTANCES_DIR", str(SERVICE_DIR / "instances")))
MCPS_DIR = INSTANCES_DIR / "mcps"
KNOWLEDGE_DIR = Path(os.getenv("MCP_KNOWLEDGE_DIR", str(Path(os.getenv("UI_INSTANCES_DIR", str(SERVER_DIR / "UI" / "instances"))) / "knowledge")))

for _d in (INSTANCES_DIR, MCPS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════
# Server settings
# ══════════════════════════════════════════════════════════════════

HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "5002"))
DEBUG = os.getenv("MCP_DEBUG", "false").lower() == "true"

UI_SERVICE_URL = os.getenv("UI_SERVICE_URL", "http://localhost:5001")

# Pre-configured marketplace entries
MARKETPLACE: Dict[str, Dict[str, Any]] = {
    "github": {
        "id": "github",
        "name": "GitHub",
        "description": "Integrate with GitHub API",
        "categories": ["code_repository", "version_control"],
    },
    "slack": {
        "id": "slack",
        "name": "Slack",
        "description": "Integrate with Slack API",
        "categories": ["communication", "notifications"],
    },
    "google_sheets": {
        "id": "google_sheets",
        "name": "Google Sheets",
        "description": "Integrate with Google Sheets API",
        "categories": ["data", "spreadsheets"],
    },
}