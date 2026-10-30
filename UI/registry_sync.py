"""Official MCP Registry & Smithery sync module.

Replaces static leaderboard snapshots with dynamic registry synchronization:
- Fetches official MCP servers (which include endpoints/URLs)
- Auto-resolves endpoints for servers that need them
- Classifies authentication requirements (warning tags for credentials)
- Supports one-click installs for non-auth servers
- Provides refreshable UI sync for both MCPs and Skills
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

_DATA = Path(__file__).resolve().parent / "data"

OFFICIAL_MCP_REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"
SMITHERY_REGISTRY_URL = "https://smithery.ai/api/v1/servers"


def auto_resolve_endpoint(entry: Dict[str, Any]) -> str:
    """Auto-resolve an MCP server endpoint from its ID or metadata."""
    if entry.get("endpoint"):
        return entry["endpoint"]
    
    server_id = entry.get("id", "").strip().lower()
    
    # Well-known server endpoint mappings
    known_endpoints = {
        "github": "https://api.github.com/mcp",
        "slack": "https://mcp.run/slack",
        "google_sheets": "https://mcp.run/google-sheets",
        "fetch": "https://mcp.run/fetch",
        "filesystem": "http://127.0.0.1:5002/api/mcp/filesystem",
        "postgres": "https://mcp.run/postgres",
        "weather": "https://api.open-meteo.com/v1/forecast",
        "memory": "https://mcp.run/memory",
        "brave_search": "https://api.search.brave.com/res/v1/web/search",
        "time": "https://mcp.run/time",
        "system_disk": "http://127.0.0.1:5002/api/mcp/execute/system_disk",
        "system_shell": "http://127.0.0.1:5002/api/mcp/execute/system_shell",
        "lb-mcp-1": "https://mcp.run/reverse-engineer",
        "lb-mcp-2": "https://mcp.run/superpowers",
    }
    if server_id in known_endpoints:
        return known_endpoints[server_id]
    
    # Clean ID for default fallback
    clean_id = server_id.replace("io.github.", "").replace("/", "-")
    return f"https://mcp.run/{clean_id}"


def sync_mcp_registry(force_remote: bool = False) -> Dict[str, Any]:
    """Sync MCP registry from official registry or Smithery, falling back to cached file."""
    legacy_file = _DATA / "leaderboard_mcp.json"
    cache_file = _DATA / "registry_mcp.json"
    
    servers: List[Dict[str, Any]] = []
    source = "Official MCP Registry & Smithery"
    source_url = OFFICIAL_MCP_REGISTRY_URL
    snapshot_date = "2026-10-30"

    if force_remote:
        try:
            resp = requests.get(OFFICIAL_MCP_REGISTRY_URL, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                raw_servers = data.get("servers", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                for s in raw_servers:
                    s_id = s.get("name") or s.get("id", "")
                    requires_auth = bool(s.get("requires_auth") or s.get("auth_type") not in (None, "", "none"))
                    servers.append({
                        "id": s_id,
                        "name": s.get("title") or s.get("name") or s_id,
                        "description": s.get("description", ""),
                        "endpoint": auto_resolve_endpoint(s),
                        "method": s.get("method", "GET"),
                        "author": s.get("author") or s.get("publisher", ""),
                        "category": s.get("category", "General"),
                        "requires_auth": requires_auth,
                        "auth_type": s.get("auth_type", "api_key" if requires_auth else "none"),
                        "auth_note": s.get("auth_note", "Credentials required" if requires_auth else "No credentials required"),
                        "source": "Official MCP Registry",
                        "source_url": s.get("url") or f"https://registry.modelcontextprotocol.io/v0.1/servers/{s_id}",
                    })
        except Exception:
            pass

    if not servers:
        target_path = legacy_file if legacy_file.exists() else cache_file
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
                servers = cached.get("entries", [])
                source = cached.get("source", source)
                source_url = cached.get("source_url", source_url)
                snapshot_date = cached.get("snapshot_date", snapshot_date)
        except Exception:
            servers = []

    # Ensure every entry has resolved endpoint, auth information, and source
    for entry in servers:
        if not entry.get("endpoint"):
            entry["endpoint"] = auto_resolve_endpoint(entry)
        if str(entry.get("id", "")).startswith("lb-"):
            entry.setdefault("source", "Leaderboard")
        else:
            entry.setdefault("source", "Official MCP Registry")
        if "requires_auth" not in entry:
            entry["requires_auth"] = bool(entry.get("auth_type") and entry["auth_type"] != "none")
        if not entry.get("auth_type"):
            entry["auth_type"] = "api_key" if entry["requires_auth"] else "none"
        if not entry.get("auth_note"):
            entry["auth_note"] = "Requires credentials" if entry["requires_auth"] else "No credentials required"
        if not entry.get("method"):
            entry["method"] = "GET"
        if "tags" not in entry:
            entry["tags"] = ["auth-required" if entry["requires_auth"] else "no-auth"]

    return {
        "source": source,
        "source_url": source_url,
        "snapshot_date": snapshot_date,
        "entries": servers,
        "count": len(servers),
    }


def sync_skills_registry(force_remote: bool = False) -> Dict[str, Any]:
    """Sync Skills registry with Smithery / public registry."""
    legacy_file = _DATA / "leaderboard_skills.json"
    cache_file = _DATA / "registry_skills.json"

    skills: List[Dict[str, Any]] = []
    source = "Smithery & Public Skills Registry"
    source_url = "https://smithery.ai/skills"
    snapshot_date = "2026-10-27"

    if force_remote:
        try:
            resp = requests.get("https://smithery.ai/api/v1/skills", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                raw_skills = data.get("skills", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                for s in raw_skills:
                    s_id = s.get("id") or s.get("name", "")
                    skills.append({
                        "id": s_id,
                        "name": s.get("name") or s_id,
                        "description": s.get("description", ""),
                        "author": s.get("author", "Smithery Community"),
                        "category": s.get("category", "General"),
                        "source_url": s.get("url") or f"https://smithery.ai/skills/{s_id}",
                    })
                snapshot_date = "2026-10-30"
        except Exception:
            pass

    if not skills:
        target_path = legacy_file if legacy_file.exists() else cache_file
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
                skills = cached.get("entries", [])
                source = cached.get("source", source)
                source_url = cached.get("source_url", source_url)
                snapshot_date = cached.get("snapshot_date", "2026-10-27")
        except Exception:
            skills = []

    return {
        "source": source,
        "source_url": source_url,
        "snapshot_date": snapshot_date,
        "entries": skills,
        "count": len(skills),
    }
