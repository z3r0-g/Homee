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

# Pre-configured marketplace entries with resolved endpoints and auth metadata.
# The built-in entries (github/slack/google_sheets/fetch) were retired: their
# endpoints are dead (mcp.run shut down and now redirects to a landing page).
# The marketplace is served from the synced Official MCP Registry & Smithery
# snapshot instead (see UI registry_sync).
MARKETPLACE: Dict[str, Dict[str, Any]] = {}
