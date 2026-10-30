# Homee — Finalization & Production Readiness Plan
> Source: https://github.com/z3r0-g/Homee
> Target: Production-ready offline AI Agent platform on A1347 Mac Mini
> Updated: 2026-10-30

## 1. Executive Summary

**Homee** is an offline-first AI Agent platform (2 Flask services + Skills plugin system) designed for repurposed Apple Mac Mini A1347 (Ubuntu 22.04, 8GB+ RAM, CPU-only LLMs via Ollama).

This milestone delivers **1-Click MCP Marketplace installs**, **Official MCP Registry & Smithery integration**, **Multimodal Image Support**, and full **Bot Skill & MCP Execution Alignment**.

### Success Criteria & Status
- [x] **Official/Public MCP Registry:** Switched from static snapshots without endpoints to the Official MCP Registry API (`registry.modelcontextprotocol.io`) and Smithery catalog with valid URLs.
- [x] **One-Click Installs & Auto-Resolve:** Endpoints auto-resolve automatically upon install in `UI/routes/mcps.py` and `MCP/routes.py`.
- [x] **Auth Warnings & Filter Tags:** MCP cards display auth warning badges (`Auth Required` vs `No Auth`) and provide chip filters. Credentials (API key / token) are only requested when a server requires them.
- [x] **Smithery UI Sync:** Replaced static leaderboard logic with UI sync functions for both MCPs (`/api/mcp/sync`) and Skills (`/api/skills/sync`) with dedicated refresh buttons.
- [x] **Bot Skill Confirmation:** All bot chats and task runs strictly resolve and execute the Skill assigned to them (discovered, saved, or general).
- [x] **Bot MCP Execution:** All bot chats can use local and configured MCP tools as intended via automated tool specification generation and `mcp_executor` dispatching.
- [x] **Multimodal Chat UI:** Chat UI presents images created by MCPs and Skills (markdown images, data URIs, image links) and enables upload of image attachments (`image/*`) when a vision model is active.
- [x] **Test Suite & Playwright E2E:** 100% green across all 91 tests in pytest and Playwright (`test_homee_e2e.py`).

---

## 2. Architecture & Service Map

### UI Service — `UI/` (port 5001)
- `UI/app.py`: `create_ui_app()` App Factory + WSGI handler.
- `UI/config.py`: Environment configuration and paths.
- `UI/registry_sync.py`: Official MCP Registry + Smithery synchronization, offline cache fallback, and endpoint auto-resolution.
- `UI/routes/bots.py`: Bot management, assigned skill execution in chats & tasks, MCP tool integration, and multimodal attachment parsing.
- `UI/routes/mcps.py`: MCP proxy, one-click install, credential management, and `/api/mcp/sync`.
- `UI/routes/skills.py`: Skill management, marketplace, and `/api/skills/sync`.
- `UI/static/app.js`: SPA frontend, multimodal image renderer, vision model image uploader, auth modal, and sync controls.
- `UI/static/app.css`: Modern responsive styles, auth tags, and `.chat-image` responsive containers.
- `UI/templates/app.html`: Core DOM structure, settings sub-panels, modal dialogs, and file upload input.

### MCP Service — `MCP/` (port 5002)
- `MCP/app.py`: `create_mcp_app()` App Factory.
- `MCP/config.py`: Service configuration, storage paths, and pre-configured marketplace entries with endpoints and auth metadata.
- `MCP/routes.py`: MCP CRUD, execution router (`POST /api/mcp/execute/<id>`) forwarding auth headers, system tools (`system_disk`, `system_shell`), and knowledge base.

### Skills Engine — `Skills/`
- `Skills/app.py`: `SkillBase` and `SkillResult` with dynamic MCP tool spec generation (`_build_tool_specs`) and multimodal execution support.
- `Skills/registry.py`: Local and remote git skill discovery.

---

## 3. Production Release Checklist

1. [x] Run full pytest suite: `python -m pytest` (91 passed).
2. [x] Run full Playwright E2E suite: `python -m pytest test_homee_e2e.py` (8 passed).
3. [x] Verify offline startup and graceful degradation when internet is disconnected.
4. [x] Validate vision image upload behavior on multimodal models.
5. [x] Documentation updated in `PLAN.md`, `README.md`, and `CONTRIBUTE.md`.
6. [x] Ready branch for merge with `main`.
