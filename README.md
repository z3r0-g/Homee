# Homee AI Agent Platform
![Homee](UI/static/homee.png)

## Overview
Homee is a self-hosted AI agent platform that lets you run autonomous AI agents,
local LLMs, RAG knowledge bases, and workflow automations entirely on your own
hardware. Designed for homelabs, edge computing, and privacy-first deployments,
Homee provides a local alternative to cloud AI platforms while maintaining full
control of your data.

## Prerequisites

- Apple Mac Mini A1347 Metal w/Ubuntu 22.04 LTS (or similar hardware / OS)
    - 8GB+ RAM (supports running CPU-only LLM models)
- Ollama (local LLM backend)
- Python 3.13+ with virtual environment (`venv`)
- Git (for remote skill plugins)
- Node.js and npm (optional, for frontend assets)

## Features

- **Bots with assigned Skills** — every bot replies through its assigned skill(s): combine multiple skills per bot (composite system prompt + union of tools), assign multiple MCP servers, set an optional scheduled task prompt, and chat adhoc anytime. Local skills are discovered from `Skills/local/`; marketplace skills install in one click.
- **Ask About a File** — ✅ Available. Paperclip in the composer attaches a text file (`.txt,.md,.json,.py,.log`, <1MB); it is injected into the prompt (truncated to 12k chars) and never written to disk.
- **Search Across Chats** — ✅ Available. Sidebar search box scans every bot's full chat history (`UI/instances/bots/*/history.jsonl`), debounced, and opens the bot scrolled to the match.
- **MCP Marketplace** — one-click install from the Official MCP Registry & Smithery; assign MCPs per bot.
- **Local-first LLM** — Ollama-first with remote fallback, RAM-aware model catalog.

## Architecture

> The platform is organized into two Flask services, each using the **App Factory pattern** (`create_app()` factory), running on separate ports.

### UI Service — `UI/` (port 5001)

**Files:**
- `UI/__init__.py` — empty package marker
- `UI/app.py` — `create_ui_app()` Flask app factory + module-level `app` for WSGI deployment
- `UI/config.py` — paths, ports, defaults
- `UI/models.py` — Bot, Skill, BotConfig + repos
- `UI/llm.py` — LLMRouter: local Ollama (priority) + remote fallback
- `UI/registry_sync.py` — Official MCP Registry and Smithery sync engine with auto-resolution
- `UI/scheduler.py` — stdlib background scheduler for timed bot runs
- `UI/routes/` — Flask blueprints (bots, skills, mcps, knowledge, settings)

**Runtime state — `UI/instances/`** (auto-created on startup; safe to delete for a full reset):
- `settings.json` — persisted UI settings (LLM mode, scheduler, env vars)
- `bots/` — bot state (`bots_state.json`) and per-bot chat history (`<bot_id>/history.jsonl`)
- `knowledge/` — per-bot RAG knowledge bases (`kb_<bot_id>.md`), written when a bot's knowledge base is saved
- `mcps/` — locally registered MCP servers (`mcps.json`), written when an MCP is added/imported

`knowledge/` and `mcps/` stay empty until the first knowledge base or MCP registration is saved — empty does not mean unused.

**Key Endpoints:**
- `GET /api/bots` — List all bots
- `POST /api/bots` — Create new bot (with assigned skill + schedule)
- `POST /api/bots/{id}/chat` — Chat with bot (uses assigned skill, MCP tools, and multimodal attachments)
- `POST /api/bots/{id}/run` — Run bot's scheduled task
- `GET /api/mcp/remote` — Synced MCP marketplace from Official MCP Registry & Smithery
- `POST /api/mcp/import/{id}` — 1-click install remote MCP (with auto-resolved endpoint and credentials)
- `POST /api/mcp/sync` — Sync MCP registry with Official Registry and Smithery
- `GET /api/skills/marketplace` — Skills marketplace synced from Smithery
- `POST /api/skills/sync` — Sync skills marketplace from Smithery
- `GET /api/skills/active` — Active skills list
- `GET /api/llm/status` — Ollama status and installed models
- `GET /api/health` — Health check

### MCP Service — `MCP/` (port 5002)

**Files:**
- `MCP/__init__.py` — empty package marker
- `MCP/app.py` — `create_mcp_app()` Flask app factory + module-level `app` for WSGI deployment
- `MCP/config.py` — paths, ports, marketplace definitions
- `MCP/routes.py` — MCP CRUD + marketplace + agent-callable execution endpoint forwarding auth headers

## Testing

Homee features a comprehensive unit, integration, and Playwright end-to-end test suite:

```bash
# Run entire test suite (159 tests)
pytest

# Run Playwright E2E browser tests
pytest test_homee_e2e.py

# Skill contract + utility suites (PLAN.md Ch 12)
pytest Skills/tests/
```

## Quick Start (Install Everything)
The installer provides a one-click setup for Homee, including all dependencies and services.

```bash
bash install.sh
```

Access the platform in your browser at `http://localhost:5001`, or at its local network IP from another device.
