# AI Agent Bot Platform — Refactor Plan

## Structure (Python 3.13 App Factory Pattern, 2 Services)

```
/home/z3r0/Server/
├── README.md
├── PLAN.md
├── conftest.py             # Root pytest config (sets UI_START_SCHEDULER=false)
- `pytest.ini` — `pythonpath=.`, `testpaths=UI/tests MCP/tests Agents/tests` (unit tests); e2e tests run via `pytest e2e/`
- `test_homee_e2e.py` — Playwright end-to-end tests (root)
├── requirements.txt
├── Agents/                   # Agent plugin library (treated like its own repo)
│   ├── __init__.py
│   ├── app.py              # AgentBase + AgentResult + built-in tools + dispatch
│   ├── registry.py         # Discovers agents from local dir + git repos
│   ├── sources.json        # Agent sources: local dir + git repo URLs
│   ├── local/              # Local agent modules
│   │   ├── __init__.py
│   │   └── demo.py         # Example agent (Demo System Agent)
│   └── tests/
│       └── test_agents.py
├── UI/                    # PORT 5001 — Bot admin UX + chat + scheduling
│   ├── __init__.py        # Empty package marker
│   ├── app.py            # create_ui_app() + module-level app + entry point
│   ├── config.py         # Paths, ports, defaults
│   ├── llm.py            # LLMRouter: local Ollama (priority) + remote fallback
│   ├── models.py         # Bot, Personality, BotConfig + JSON repos
│   ├── scheduler.py      # Stdlib background scheduler for timed bot runs
│   ├── routes/           # Flask blueprints (app factory pattern)
│   │   ├── __init__.py
│   │   ├── bots.py
│   │   ├── personalities.py
│   │   ├── mcps.py       # Proxies to MCP service
│   │   ├── knowledge.py
│   │   ├── settings.py   # LLM provider + scheduler settings
│   │   └── agents.py     # Agent registry listing
│   ├── static/css/style.css
│   ├── static/js/app.js  # Frontend: NL chat + settings UX
│   ├── templates/index.html
│   ├── instances/        # Runtime JSON state (bots, knowledge, etc.)
│   └── tests/
│       ├── conftest.py
│       └── test_ui.py
├── MCP/                   # PORT 5002 — MCP endpoints consumed by Agents
    ├── __init__.py        # Empty package marker
    ├── app.py            # create_mcp_app() + module-level app + entry point
    ├── config.py         # Paths, ports, marketplace
    ├── routes.py         # MCP CRUD + marketplace + execute endpoint
    └── endpoints/        # Agent-callable MCP endpoints
        ├── __init__.py
        ├── system.py     # disk + shell
        └── knowledge.py  # KB read/append
    └── tests/
        ├── conftest.py
        └── test_mcp.py
```

## How Requirements Map

| Requirement | Implementation |
|---|---|
| **UI = simplified admin of Agents via NL + settings UX** | `/api/bots` CRUD, `/api/bots/<id>/chat` natural-language chat, `/api/settings` for LLM/provider/schedule defaults, SPA frontend |
| **Bot creation asks which Agent personality to embody** | New-bot form lists `/api/personalities`; bot stores `personality_id`; personality's `system_prompt` seeds every chat/scheduled run |
| **Bots run Agent skill as scheduled/configured** | `Bot.schedule` (interval) + `task_prompt`; stdlib background scheduler triggers runs via assigned Agent personality |
| **Local Ollama first, shared cloud LLM APIs configurable** | `LLMRouter`: local Ollama priority #1; remote via OpenAI-compatible endpoint (base_url/api_key/model from settings); automatic fallback |
| **Agents dir treated like a repo; external agents via git config** | `Agents/registry.py` discovers agents from `sources.json` `local_dir` (now `Agents/local/`) using `importlib` with `__package__ = "Agents"`; git repos listed in `sources.json` are cloned into `Agents/remote/<name>/` and scanned for `AgentBase` subclasses |
| **MCP = custom endpoints for Agents** | MCP service exposes `/api/mcp/execute/<name>`, `/api/mcp/system/disk`, `/api/mcp/system/shell`, `/api/mcp/knowledge/<bot_id>` plus CRUD/marketplace; UI proxies MCP calls |

## Services

- **UI Service** (`UI/`): `create_ui_app()` factory, port 5001
  - `app.py` contains the factory + module-level `app` for WSGI deployment
  - Entry point: `python -m UI.app`
  - WSGI handler: `UI.app:app`
- **MCP Service** (`MCP/`): `create_mcp_app()` factory, port 5002
  - `app.py` contains the factory + module-level `app` for WSGI deployment
  - Entry point: `python -m MCP.app`
  - WSGI handler: `MCP.app:app`

Start each service independently: `python -m UI.app` (port 5001) and `python -m MCP.app` (port 5002).

## Deployment (Azure App Service)

Configure the WSGI handler in App Settings:
- **UI**: `WSGI_HANDLER = UI.app:app`
- **MCP**: `WSGI_HANDLER = MCP.app:app`

The module-level `app` variable in each `app.py` is the WSGI callable.

## Testing

- Root `conftest.py` sets `UI_START_SCHEDULER=false` before test collection
- Tests import factories directly: `from UI.app import create_ui_app`, `from MCP.app import create_mcp_app`
- Run with: `python -m pytest -v`