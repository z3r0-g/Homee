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

# Pre-configured marketplace entries with resolved endpoints and auth metadata
MARKETPLACE: Dict[str, Dict[str, Any]] = {
    "github": {
        "id": "github",
        "name": "GitHub",
        "description": "Integrate with GitHub API",
        "endpoint": "https://api.github.com/mcp",
        "method": "POST",
        "categories": ["code_repository", "version_control"],
        "requires_auth": True,
        "auth_type": "bearer",
        "auth_note": "Requires GitHub Personal Access Token",
    },
    "slack": {
        "id": "slack",
        "name": "Slack",
        "description": "Integrate with Slack API",
        "endpoint": "https://mcp.run/slack",
        "method": "POST",
        "categories": ["communication", "notifications"],
        "requires_auth": True,
        "auth_type": "bearer",
        "auth_note": "Requires Slack Bot Token",
    },
    "google_sheets": {
        "id": "google_sheets",
        "name": "Google Sheets",
        "description": "Integrate with Google Sheets API",
        "endpoint": "https://mcp.run/google-sheets",
        "method": "POST",
        "categories": ["data", "spreadsheets"],
        "requires_auth": True,
        "auth_type": "bearer",
        "auth_note": "Requires Google OAuth / API Key",
    },
    "fetch": {
        "id": "fetch",
        "name": "Fetch",
        "description": "Web fetcher for pages and APIs",
        "endpoint": "https://mcp.run/fetch",
        "method": "GET",
        "categories": ["api", "web"],
        "requires_auth": False,
        "auth_type": "none",
        "auth_note": "No credentials required",
    },
}
