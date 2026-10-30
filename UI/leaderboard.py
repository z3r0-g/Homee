"""Leaderboard & Marketplace registry sync.

Delegates to UI.registry_sync for official MCP and Smithery data.
Retains backward-compatible load_leaderboard(kind) interface.
"""

from __future__ import annotations

from typing import Dict, Any
from .registry_sync import sync_mcp_registry, sync_skills_registry


def load_leaderboard(kind: str) -> Dict[str, Any]:
    """Load registry snapshot for kind ('mcp' or 'skills')."""
    if kind == "mcp":
        return sync_mcp_registry(force_remote=False)
    if kind == "skills":
        return sync_skills_registry(force_remote=False)
    return {"source": "", "source_url": "", "snapshot_date": "", "entries": []}
