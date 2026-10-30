# Homee AI Agent Platform
>Designed to run on repurposed Mac Mini A1347 Metal.

![Homee](UI/static/homee.png)

## Overview

Homee is a simple, self-hosted home for local AI — a simpler alternative to Open WebUI for the house, built for the casual home enthusiast and designed to run on a repurposed Mac Mini. It keeps the loved essentials (chat with bots, tools, scheduled tasks, local Ollama models) and leaves out the clutter: no workspaces, admin panels, or plugin stores. The design rule is simple: if a feature needs a manual, it doesn't ship.

***WARNING*** This platform was designed with AI coding agents as a key component of the development workflow to provide a comprehensive system for managing AI agent bots on lightweight hardware with the following in mind:

- **Bot Management**: Create, manage, and chat with AI agent bots
- **MCP Integrations**: Model Context Protocol integrations (GitHub, Google Drive, Microsoft OneDrive)
- **Skills**: Loadable skills from local directories or remote Git repositories
- **Skills**: Configure skills with abilities and system prompts

## Features

Five features, done the simple way:

1. **Chat with multiple bots, flip while they work** — Available. Every bot lives in the sidebar with a live status word. Send a message or run a task, switch to another bot, and the first task keeps running in the background; its reply is waiting when you come back. One task per bot at a time, so nothing ever gets dropped or talked over.
2. **Starter prompts on empty chats** — Available. A new chat suggests up to two openers — the bot's own task prompt, if it has one, and "What can you do?" — so a first-time user never faces a blank box.
3. **Fast / Smart model switch** — Available. One switch in the composer: Fast answers with your primary local model, Smart with your configured secondary model. No sliders, no temperature, no parameter panels. (Smart is greyed out until a secondary model is set in Settings.)
4. **Ask about a file** — Available. Attach a text file to a chat (paperclip in the composer) and its text rides along as context for that conversation — full-content injection, no vector database, no embeddings to run on the Mini. Attachments live in the open chat view only: switching bots or reloading drops them, and they never land in saved history.
5. **Search across chats** — Available. One search box in the sidebar over everything you've asked, replacing folders, tags, and pins entirely. Click a match to open that bot's chat.

## Prerequisites

- Apple Mac Mini A1347 Metal w/Ubuntu 22.04 LTS (or similar hardware)
    - 8GB+ RAM (must support running at least CPU-only LLM models)
- Ollama (local LLM)
- Python 3.13 with virtual environment (`venv`)
- Git (for remote skill plugins)
- Node.js and npm (for frontend assets)
- Git LFS (if using large files in remote skill plugins)

## Architecture

>The platform is organized into two Flask services, each using the **App Factory pattern** (`create_app()` factory), running on separate ports.

### UI Service — `UI/` (port 5001)

**Files:**
- `UI/__init__.py` — empty package marker
- `UI/app.py` — `create_ui_app()` Flask app factory + module-level `app` for WSGI deployment
- `UI/config.py` — paths, ports, defaults
- `UI/models.py` — Bot, Skill, BotConfig + repos
- `UI/llm.py` — LLMRouter: local Ollama (priority) + remote fallback
- `UI/scheduler.py` — stdlib background scheduler for timed bot runs
- `UI/routes/` — Flask blueprints (bots, skills, mcps, knowledge, settings)

**Endpoints:**
- `GET /api/bots` — List all bots
- `POST /api/bots` — Create new bot (with skill + schedule)
- `GET /api/bots/{id}` — Get bot details
- `PUT /api/bots/{id}` — Update bot
- `DELETE /api/bots/{id}` — Delete bot
- `POST /api/bots/{id}/chat` — Send message to bot (natural language)
- `POST /api/bots/{id}/run` — Run bot's scheduled task
- `GET /api/skills` — List skills
- `POST /api/skills` — Create new skill
- `GET /api/mcps` — List registered MCPs (proxied to MCP service)
- `GET /api/mcp/marketplace` — Open MCP marketplace
- `GET /api/settings` — Get settings (LLM provider, scheduler)
- `POST /api/settings` — Save settings
- `GET /api/llm/status` — Ollama reachability, installed models, configured-model readiness
- `POST /api/llm/pull` — Pull a model in the background (202 + job; 409 if a pull is running)
- `GET /api/llm/pull` — Current model-pull job state
- `GET /api/llm/catalog` — Curated model browser sized to host RAM
- `DELETE /api/llm/models/{name}` — Unload a locally installed model
- `GET /api/mcp/local` — MCPs registered on this host
- `GET /api/mcp/remote` — Remote marketplace (built-ins + curated community)
- `POST /api/mcp/import/{id}` — Copy a remote MCP into the local registry
- `POST /api/mcp/enable/{id}` / `POST /api/mcp/disable/{id}` — Toggle a local MCP
- `GET /api/skills/active` — Skills with id, source, and enabled state
- `POST /api/skills/toggle/{id}` — Enable/disable a skill
- `POST /api/skills/refresh` — Re-discover skills + import remote skills
- `GET /api/skills` — List available skills
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

### Skills Plugin System — `Skills/`

- Local plugins: `Skills/local/*.py` (scanned for `SkillBase` subclasses)
- Remote plugins: Git repository URLs in `Skills/sources.json`
- Plugin base class: `SkillBase` with `execute()` method

## Quick Start (Ollama first — no API keys)

Homee works out of the box with local Ollama. No cloud account needed:

1. Install Ollama: `curl -fsSL https://ollama.com/install.sh | sh`
2. Pull the default model: `ollama pull llama3.2:3b` (Homee's default local model; override with `OLLAMA_MODEL`)
   (or start the UI first and pull it from **Settings → Models**)
3. Start the services below and open http://host-ip-or-dns:5001 —
   the header shows the live Ollama status, and chat works immediately.
   If Ollama is offline or the model is missing, the header and the chat
   area say so plainly instead of failing with a cryptic error.

## Quick Start (services)

>Start each service independently

MCP service (port 5002)
```bash
source venv/bin/activate
python -m MCP.app
```
UI service (port 5001)
```bash
source venv/bin/activate
python -m UI.app
```
Open browser to http://host-ip-or-dns:5001 (UI) to begin interacting with the platform

## Environment Variables

- `UI_INSTANCES_DIR` — directory for UI runtime JSON state (bots, MCPs, settings). Defaults to `UI/instances`.
- `MCP_INSTANCES_DIR` — directory for MCP runtime JSON state. Defaults to `MCP/instances`.
- `MCP_SERVICE_URL` — base URL of the MCP service used by the UI. Defaults to `http://localhost:5002`.
- `UI_PORT` / `MCP_PORT` — service ports. Defaults to `5001` / `5002`.
- `OLLAMA_MODEL` — default local model. Defaults to `llama3.2:3b` (matches `install.sh`).
- `OLLAMA_HOST` — Ollama server URL. Defaults to `http://localhost:11434`.
- `UI_START_SCHEDULER` — set to `false` to disable the background scheduler (used in tests).
- `MCP_KNOWLEDGE_DIR` — directory for MCP knowledge-base files. Defaults to `MCP/instances/knowledge`.

## Testing

- `pytest` runs unit tests for `UI`, `MCP`, and `Skills`.
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
2. Click "New Bot", enter a name, select a skill (from registered skills), and optionally configure a scheduled task
3. The bot embodies the selected skill's system prompt and skill set
4. Chat with the bot in natural language, or run its scheduled task on demand

## Settings

Click "Settings" to configure:
- LLM provider: local Ollama (default, priority #1) or remote cloud LLM (OpenAI-compatible)
- Local models: a card browser sized to host RAM (click a card to pull it;
  loaded models show green, unload, and fill the Primary / Secondary slots)
- LLM mode: Local + Local, Local + Cloud, or Local + Remote Local — the
  Cloud / Remote Local section below the cards takes focus in those modes
- MCP Marketplace: add your own MCPs, plus local and remote (mcpmarket.com
  and community) listings
- Skills: local skills on by default and disableable, plus a
  remote git repo to sync skills from
- Scheduler enabled and tick interval (a general setting, above the tabs)

## Contributing skills

Write your own skills in a git repo and load them from
**Settings → Skills → Sync Skills**. See
[CONTRIBUTE.md](CONTRIBUTE.md) for the skill contract, the skill
JSON schema, and a repo layout you can copy.
