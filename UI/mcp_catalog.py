"""Curated remote MCP servers for the Marketplace tab.

Homee's MCP service executes HTTP endpoints, so every entry here is an
HTTP API that can be registered as-is (or with a key the user pastes into
the Add form). Entries with no auth work out of the box and are good first
MCPs to try.

``source`` names where the server is listed so the tab can attribute it:
the built-in marketplace, mcpmarket.com, or the wider community. This is a
curated snapshot, not a live scrape — the tab links out to mcpmarket.com
for the full listing.
"""

from __future__ import annotations

from typing import Any, Dict, List

# id, name, description, source, source_url, endpoint, method, auth_note
REMOTE_CATALOG: List[Dict[str, Any]] = [
    {"id": "github", "name": "GitHub",
     "description": "Integrate with the GitHub API.",
     "source": "Built-in marketplace", "source_url": "",
     "endpoint": "https://api.github.com", "method": "GET",
     "auth_note": "Needs a GitHub token — add it as a bearer header in the Add form."},
    {"id": "slack", "name": "Slack",
     "description": "Integrate with the Slack API.",
     "source": "Built-in marketplace", "source_url": "",
     "endpoint": "https://slack.com/api", "method": "POST",
     "auth_note": "Needs a Slack bot token."},
    {"id": "google_sheets", "name": "Google Sheets",
     "description": "Integrate with the Google Sheets API.",
     "source": "Built-in marketplace", "source_url": "",
     "endpoint": "https://sheets.googleapis.com", "method": "GET",
     "auth_note": "Needs Google OAuth credentials."},
    {"id": "brave_search", "name": "Brave Search",
     "description": "Web search via the Brave Search API.",
     "source": "mcpmarket.com", "source_url": "https://mcpmarket.com",
     "endpoint": "https://api.search.brave.com/res/v1/web/search", "method": "GET",
     "auth_note": "Needs a Brave Search API key."},
    {"id": "openweather", "name": "OpenWeather",
     "description": "Current weather and forecasts.",
     "source": "mcpmarket.com", "source_url": "https://mcpmarket.com",
     "endpoint": "https://api.openweathermap.org/data/2.5/weather", "method": "GET",
     "auth_note": "Needs an OpenWeather API key."},
    {"id": "jsonplaceholder", "name": "JSONPlaceholder",
     "description": "Fake REST API for trying out MCP calls — no key needed.",
     "source": "Community", "source_url": "",
     "endpoint": "https://jsonplaceholder.typicode.com", "method": "GET",
     "auth_note": "No auth required."},
    {"id": "hackernews", "name": "Hacker News",
     "description": "Top stories and items from the Hacker News API.",
     "source": "Community", "source_url": "",
     "endpoint": "https://hacker-news.firebaseio.com/v0", "method": "GET",
     "auth_note": "No auth required."},
    {"id": "coingecko", "name": "CoinGecko",
     "description": "Crypto prices and market data.",
     "source": "Community", "source_url": "",
     "endpoint": "https://api.coingecko.com/api/v3", "method": "GET",
     "auth_note": "No auth required for basic use."},
    {"id": "restcountries", "name": "REST Countries",
     "description": "Country data: capitals, populations, languages.",
     "source": "Community", "source_url": "",
     "endpoint": "https://restcountries.com/v3.1", "method": "GET",
     "auth_note": "No auth required."},
    {"id": "httpbin", "name": "httpbin",
     "description": "HTTP request/response testing service.",
     "source": "Community", "source_url": "",
     "endpoint": "https://httpbin.org", "method": "GET",
     "auth_note": "No auth required."},
]


def remote_catalog() -> List[Dict[str, Any]]:
    """Curated remote entries (copies, so callers cannot mutate the table)."""
    return [dict(entry) for entry in REMOTE_CATALOG]
