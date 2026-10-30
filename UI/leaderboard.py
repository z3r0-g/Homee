"""Leaderboard snapshots (mcpmarket.com, seeded 2026-10-27).

The snapshots are data, not code: re-seed the JSON files under data/
when the rankings change. The UI serves them as-is; nothing here
fetches the leaderboard pages at runtime, so a tab still renders its
remote cards when the network or the leaderboard site is unreachable.
"""

import json
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data"


def load_leaderboard(kind: str) -> dict:
    """Load one snapshot: kind is 'skills' or 'mcp'.

    Returns the snapshot dict. A missing or corrupt file yields an
    empty snapshot rather than a 500, so the tab degrades to local
    content only.
    """
    path = _DATA / f"leaderboard_{kind}.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"source": "", "source_url": "", "snapshot_date": "", "entries": []}
