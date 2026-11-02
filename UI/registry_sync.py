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
import re
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests

_DATA = Path(__file__).resolve().parent / "data"


def _write_cache(cache_file: Path, source: str, source_url: str,
                 snapshot_date: str, entries: List[Dict[str, Any]]) -> None:
    """Persist a freshly synced snapshot so later non-forced loads reuse it."""
    try:
        cache_file.write_text(json.dumps({
            "source": source,
            "source_url": source_url,
            "snapshot_date": snapshot_date,
            "entries": entries,
        }, indent=2), encoding="utf-8")
    except OSError:
        pass


def _load_cache(legacy_file: Path, cache_file: Path) -> Dict[str, Any]:
    """Load the synced cache when present, else the shipped legacy snapshot.

    Entries without an id are skipped; a file that yields no usable entries
    falls through to the next candidate.
    """
    for target in (cache_file, legacy_file):
        if not target.exists():
            continue
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        entries = [e for e in data.get("entries", [])
                   if isinstance(e, dict) and e.get("id")]
        if entries:
            return {**data, "entries": entries}
    return {}

OFFICIAL_MCP_REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"
SMITHERY_REGISTRY_URL = "https://smithery.ai/api/v1/servers"

# The registry paginates at ~30 entries/page; cap pages so a sync stays quick.
MAX_REGISTRY_PAGES = 10

# Keyword classifier for registry servers (the official registry provides no
# category field). Ordered most-specific first; "AI & ML" is checked last
# because nearly every MCP description mentions "agent"/"AI".
CATEGORY_RULES: List[Tuple[str, str]] = [
    ("Developer Tools", r"\b(code|coding|github|git|gitlab|ide|debug|debugger|sdk|cli|repo|commit|pull request|lint|compile|devops|ci/cd|docker|npm|package|regex|terminal|shell|console)\b"),
    ("Data & Databases", r"\b(database|db|sql|postgres|mysql|sqlite|mongo|redis|query|tables|spreadsheet|sheets|csv|analytics|warehouse|etl|dataset|records|duckdb|clickhouse)\b"),
    ("Search & Web", r"\b(search|scrape|scraper|crawl|browser|fetch|url|http|seo|google|bing|brave|website|webpage|sitemap)\b"),
    ("Communication", r"\b(slack|email|mail|gmail|outlook|teams|discord|telegram|whatsapp|chat|message|messaging|sms|notification|zoom|meet)\b"),
    ("Productivity", r"\b(notion|todo|task|tasks|calendar|schedule|notes|docs|document|wiki|jira|trello|asana|linear|kanban|reminder|planner)\b"),
    ("Cloud & Infra", r"\b(aws|azure|gcp|cloud|hosting|infra|cluster|container|terraform|kubernetes|k8s|monitor|observability|logging|metrics|serverless)\b"),
    ("Finance & Crypto", r"\b(crypto|usdc|x402|payment|pay|bank|finance|trading|stock|invoice|billing|price|prices|wallet|token|defi|exchange|tax|sec filings)\b"),
    ("Media & Content", r"\b(image|video|audio|music|photo|media|youtube|tiktok|podcast|transcri|text-to-speech|tts|speech|3d|design|figma|canvas|screenshot)\b"),
    ("Ads & Marketing", r"\b(\w+ads|ads|advert|campaign|campaigns|marketing|leads|brand)\b"),
    ("Files & Storage", r"\b(file|files|filesystem|storage|s3|bucket|drive|dropbox|backup|upload|download)\b"),
    ("Security & Identity", r"\b(auth|oauth|security|vulnerab|password|secret|vault|identity|sso|permission|encrypt)\b"),
    ("Location & Maps", r"\b(map|maps|geo|location|weather|places|route|directions|gps|address)\b"),
    ("Science & Knowledge", r"\b(wikipedia|arxiv|paper|research|academic|science|periodic|element|math|knowledge|lesson|academy|learn|law|legal|directory)\b"),
    ("Business & CRM", r"\b(crm|sales|customer|hubspot|salesforce|shopify|commerce|store|order|business|company|hr|recruit|property|real estate)\b"),
    ("AI & ML", r"\b(ai|llm|models|model|gpt|claude|anthropic|openai|inference|embedding|vector|rag|prompt|neural|ml|copilot|agent)\b"),
]


def categorize(name: str, description: str = "") -> str:
    """Best-effort category for a registry entry from its name/description."""
    text = f"{name} {description}".lower()
    for label, pattern in CATEGORY_RULES:
        if re.search(pattern, text):
            return label
    return "General"


def _parse_registry_server(wrapper: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str, bool]:
    """Normalize one official-registry entry.

    The registry wraps each server as ``{"server": {...}, "_meta": {...}}`` and
    publishes every version of a server; returns (entry, registry_name,
    is_latest) so the caller can dedupe by name preferring the latest version.
    Flat (unwrapped) shapes are accepted too.
    """
    s = wrapper.get("server") if isinstance(wrapper.get("server"), dict) else wrapper
    name = str(s.get("name") or s.get("id") or "").strip()
    if not name:
        return None, "", False
    meta = wrapper.get("_meta") if isinstance(wrapper.get("_meta"), dict) else {}
    official = meta.get("io.modelcontextprotocol.registry/official")
    is_latest = bool(official.get("isLatest", True)) if isinstance(official, dict) else True

    endpoint = ""
    for remote in s.get("remotes") or []:
        if isinstance(remote, dict) and remote.get("url"):
            endpoint = remote["url"]
            break

    repo = s.get("repository") if isinstance(s.get("repository"), dict) else {}
    source_url = repo.get("url") or (
        f"{OFFICIAL_MCP_REGISTRY_URL}/{urllib.parse.quote(name, safe='')}")

    requires_auth = bool(s.get("requires_auth") or s.get("auth_type") not in (None, "", "none"))
    entry = {
        # URL-safe id: registry names look like "io.github.user/server".
        "id": name.lower().replace("/", "-"),
        "name": s.get("title") or name,
        "description": s.get("description", ""),
        "endpoint": endpoint,
        "method": s.get("method", "GET"),
        "author": s.get("author") or s.get("publisher") or name.split("/")[0],
        "category": s.get("category") or categorize(name, s.get("description", "")),
        "requires_auth": requires_auth,
        "auth_type": s.get("auth_type", "api_key" if requires_auth else "none"),
        "auth_note": s.get("auth_note", "Credentials required" if requires_auth else "No credentials required"),
        "source": "Official MCP Registry",
        "source_url": s.get("url") or source_url,
    }
    return entry, name, is_latest


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
        by_name: Dict[str, Dict[str, Any]] = {}
        latest_by_name: Dict[str, bool] = {}
        cursor: Optional[str] = None
        try:
            for _ in range(MAX_REGISTRY_PAGES):
                url = OFFICIAL_MCP_REGISTRY_URL
                if cursor:
                    url += "?cursor=" + urllib.parse.quote(cursor)
                resp = requests.get(url, timeout=5)
                if resp.status_code != 200:
                    break
                data = resp.json()
                raw_servers = data.get("servers", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                for wrapper in raw_servers:
                    if not isinstance(wrapper, dict):
                        continue
                    entry, reg_name, is_latest = _parse_registry_server(wrapper)
                    if entry is None:
                        continue
                    if reg_name not in by_name or (is_latest and not latest_by_name.get(reg_name)):
                        by_name[reg_name] = entry
                        latest_by_name[reg_name] = is_latest
                cursor = data.get("metadata", {}).get("nextCursor") if isinstance(data, dict) else None
                if not cursor:
                    break
        except Exception:
            pass
        servers = list(by_name.values())
        if servers:
            snapshot_date = date.today().isoformat()
            _write_cache(cache_file, source, source_url, snapshot_date, servers)

    if not servers:
        cached = _load_cache(legacy_file, cache_file)
        servers = cached.get("entries", [])
        source = cached.get("source", source)
        source_url = cached.get("source_url", source_url)
        snapshot_date = cached.get("snapshot_date", snapshot_date)

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
        except Exception:
            pass
        if skills:
            snapshot_date = date.today().isoformat()
            _write_cache(cache_file, source, source_url, snapshot_date, skills)

    if not skills:
        cached = _load_cache(legacy_file, cache_file)
        skills = cached.get("entries", [])
        source = cached.get("source", source)
        source_url = cached.get("source_url", source_url)
        snapshot_date = cached.get("snapshot_date", "2026-10-27")

    return {
        "source": source,
        "source_url": source_url,
        "snapshot_date": snapshot_date,
        "entries": skills,
        "count": len(skills),
    }
