# Homee AI Agent Platform
>Designed to run on repurposed Mac Mini A1347 Metal.

## Overview

***WARNING*** This platform was designed with AI coding agents as a key component of the development workflow to provide a comprehensive system for managing AI agent bots on lightweight hardware with the following in mind:

- **Bot Management**: Create, manage, and chat with AI agent bots
- **MCP Integrations**: Model Context Protocol integrations (GitHub, Google Drive, Microsoft OneDrive)
- **Agent Plugins**: Loadable agents from local directories or remote Git repositories
- **Personalities**: Configure agent personalities with skills, abilities, and system prompts

## Prerequisites

- Apple Mac Mini A1347 Metal w/Ubuntu 22.04 LTS (or similar hardware)
    - 8GB+ RAM (must support running at least CPU-only LLM models)
- Ollama (local LLM)
- Python 3.13 with virtual environment (`venv`)
- Git (for remote agent plugins)
- Node.js and npm (for frontend assets)
- Git LFS (if using large files in remote agent plugins)

## Architecture

>The platform is organized into two Flask services, each using the **App Factory pattern** (`create_app()` factory), running on separate ports.

### UI Service — `UI/` (port 5001)

**Files:**
- `UI/__init__.py` — empty package marker
- `UI/app.py` — `create_ui_app()` Flask app factory + module-level `app` for WSGI deployment
- `UI/config.py` — paths, ports, defaults
- `UI/models.py` — Bot, Personality, BotConfig + JSON repos
- `UI/llm.py` — LLMRouter: local Ollama (priority) + remote fallback
- `UI/scheduler.py` — stdlib background scheduler for timed bot runs
- `UI/routes/` — Flask blueprints (bots, personalities, mcps, knowledge, settings, agents)

**Endpoints:**
- `GET /api/bots` — List all bots
- `POST /api/bots` — Create new bot (with personality + schedule)
- `GET /api/bots/{id}` — Get bot details
- `PUT /api/bots/{id}` — Update bot
- `DELETE /api/bots/{id}` — Delete bot
- `POST /api/bots/{id}/chat` — Send message to bot (natural language)
- `POST /api/bots/{id}/run` — Run bot's scheduled task
- `GET /api/personalities` — List personalities
- `POST /api/personalities` — Create new personality
- `GET /api/mcps` — List registered MCPs (proxied to MCP service)
- `GET /api/mcp/marketplace` — Open MCP marketplace
- `GET /api/settings` — Get settings (LLM provider, scheduler)
- `POST /api/settings` — Save settings
- `GET /api/agents` — List available Agent personalities
- `GET /api/health` — Health check

### MCP Service — `MCP/` (port 5002)

**Files:**
- `MCP/__init__.py` — empty package marker
- `MCP/app.py` — `create_mcp_app()` Flask app factory + module-level `app` for WSGI deployment
- `MCP/config.py` — paths, ports, marketplace
- `MCP/routes.py` — MCP CRUD + marketplace + execute endpoint

**Endpoints:**
- `GET /api/mcps` — List registered MCPs
- `POST /api/mcps` — Register new MCP
- `GET /api/mcp/{id}` — Get MCP details
- `PUT /api/mcp/{id}` — Update MCP
- `DELETE /api/mcp/{id}` — Delete MCP
- `GET /api/mcp/marketplace` — Open marketplace
- `POST /api/mcp/execute/{id}` — Execute an MCP (agent-callable)
- `GET /api/mcp/system/disk` — Disk space
- `POST /api/mcp/system/shell` — Run shell command
- `GET /api/mcp/knowledge/{bot_id}` — Get bot knowledge base
- `POST /api/mcp/knowledge/{bot_id}` — Append to bot knowledge base
- `GET /api/health` — Health check

### Agents Plugin System — `Agents/`

- Local plugins: `Agents/local/*.py` (scanned for `AgentBase` subclasses)
- Remote plugins: Git repository URLs in `Agents/sources.json`
- Plugin base class: `AgentBase` with `execute()` method

## Quick Start

>Start each service independently

MCP service (port 5002)
```bash
cd /home/z3r0/Server
source venv/bin/activate
python -m MCP.app
```
UI service (port 5001)
```bash
cd /home/z3r0/Server
source venv/bin/activate
python -m UI.app
```
Open browser to http://localhost:5001 (UI) to begin interacting with the platform

## Environment Variables

- `UI_INSTANCES_DIR` — directory for UI runtime JSON state (bots, personalities, MCPs, settings). Defaults to `UI/instances`.
- `MCP_INSTANCES_DIR` — directory for MCP runtime JSON state. Defaults to `MCP/instances`.
- `MCP_SERVICE_URL` — base URL of the MCP service used by the UI. Defaults to `http://localhost:5002`.
- `UI_PORT` / `MCP_PORT` — service ports. Defaults to `5001` / `5002`.
- `UI_START_SCHEDULER` — set to `false` to disable the background scheduler (used in tests).
- `MCP_KNOWLEDGE_DIR` — directory for MCP knowledge-base files. Defaults to `MCP/instances/knowledge`.

## Testing

- `pytest` runs unit tests for `UI`, `MCP`, and `Agents`.
- Root `conftest.py` sets `UI_START_SCHEDULER=false` before test collection.
- Tests import factories directly: `from UI.app import create_ui_app`, `from MCP.app import create_mcp_app`.
- Run all unit tests: `python -m pytest -q`
- Playwright end-to-end tests are in `test_homee_e2e.py` (root) and exercise bot CRUD, chat, scheduling, and the MCP marketplace UI:
  - `python -m pytest test_homee_e2e.py -q` (or included in `pytest`)
  - Requires Playwright browsers: `playwright install chromium`
- Environment variables above allow test isolation (temp instances directories, alternate ports).

## Playwright E2E

The root e2e suite starts both services in-process on ports 5123/5124 with isolated temp state directories and drives the SPA with Chromium. Tests cover homepage render, bot creation appearing in the sidebar, settings modal open/close, and marketplace card rendering.

## Bot Creation Flow

1. Open http://host-ip-or-dns:5001
2. Click "New Bot", enter a name, select an Agent personality (from registered Agents), and optionally configure a scheduled task
3. The bot embodies the selected personality's system prompt and skill set
4. Chat with the bot in natural language, or run its scheduled task on demand

## Settings

Click "Settings" to configure:
- LLM provider: local Ollama (default, priority #1) or remote cloud LLM (OpenAI-compatible)
- Local model (e.g., `qwen2.5`)
- Remote base URL, API key, and model
- Scheduler enabled and tick interval
