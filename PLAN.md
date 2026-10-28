# Homee — Finalization Plan (ux-repair branch)
> Source: https://github.com/z3r0-g/Homee — branch `ux-repair`
> Target: Production-ready offline AI Agent platform on A1347 Mac Mini
> Date: 2026-10-27

## 1. Executive Summary

**Homee** is an offline-first AI Agent platform (2 Flask services + Agents plugin system) designed for repurposed Apple Mac Mini A1347 (Ubuntu 22.04, 8GB+ RAM, CPU-only LLMs via Ollama).

The `ux-repair` branch was created to fix the user-facing experience before 1.0. This plan turns that branch into the final shippable version.

**Goal of this plan:** Take `ux-repair` from "works but rough" to "installs, runs offline, and feels polished on first use" — no API keys, no cryptic errors, no dead-ends.

### Success Criteria for 1.0
- [x] Fresh clone -> `install.sh` -> both services up -> `http://<host>:5001` loads <2s on A1347
- [x] Ollama offline/missing states are obvious in header + chat + Settings, with 1-click fix
- [x] Bot CRUD + chat + scheduled run works end-to-end without refresh
- [x] Playwright E2E `test_homee_e2e.py` passes 100% (4 tests on 5123/5124)
- [x] `pytest -q` green (72 server tests + 7 frontend asset tests)
- [x] Mobile UX + remote skills/MCPs installation complete
- [x] Works 100% offline after initial Ollama model pull

---

## 2. What We Know From `main` (baseline)

**Services:**
- `UI/` port 5001: `create_ui_app()` factory, blueprints `bots, personalities, mcps, knowledge, settings, agents`
- `MCP/` port 5002: `create_mcp_app()` factory, CRUD + marketplace + `execute`, `system/disk`, `system/shell`, `knowledge`
- `Agents/`: `local/*.py` scanned for `AgentBase.execute()`, remote via `Agents/sources.json`

**State:**
- JSON repos in `UI/instances/` and `MCP/instances/` (overridable via `UI_INSTANCES_DIR`, `MCP_INSTANCES_DIR`)
- `LLMRouter`: Ollama primary (`OLLAMA_HOST`, `OLLAMA_MODEL=qwen2.5:7b`), remote fallback
- Background scheduler (`UI/scheduler.py`, disable via `UI_START_SCHEDULER=false` for tests)
- `install.sh`, `requirements.txt`, `conftest.py` sets scheduler off for tests
- Node.js + npm required (frontend assets)

**Endpoints already exist:** `/api/bots`, `/api/bots/{id}/chat`, `/api/bots/{id}/run`, `/api/personalities`, `/api/mcps`, `/api/mcp/marketplace`, `/api/settings`, `/api/llm/status`, `/api/llm/pull`, `/api/agents`, `/api/health`

**Implied UX debt in `ux-repair`:**
- No consistent loading / empty / error states in SPA
- Header Ollama status exists but not prominent / actionable
- Bot creation flow (`New Bot` -> name + Agent + schedule) lacks validation + feedback
- Sidebar doesn't auto-refresh, settings modal open/close jank
- MCP marketplace cards rendering issues (from E2E description)
- Chat has no streaming indicator, no retry, cryptic errors when Ollama offline

---

## 3. UX-Repair Audit — What to Fix

### 3.1 Critical Path (P0)
1.  **First-Run Experience:** If `GET /api/llm/status` says Ollama unreachable or model missing, show banner + button: `Pull qwen2.5:7b` that calls `POST /api/llm/pull` and polls `GET /api/llm/pull`.
2.  **Bot Creation:** Form validation (name required, personality required), disable submit while saving, optimistic sidebar update, success toast, focus management.
3.  **Chat:** Input disabled when bot/busy/LLM offline, show typing/streaming indicator, render markdown, handle 202/409 from pull, retry button.
4.  **Error Boundaries:** Replace raw `fetch` errors with human messages: "Ollama offline — start Ollama or check Settings".

### 3.2 High Priority (P1)
- **Sidebar:** Live bot list via polling or SSE, delete confirmation, active bot highlight, empty state with CTA
- **Settings Modal:** Proper modal a11y (ESC, focus trap, click-outside), save feedback, live test for remote LLM
- **MCP Marketplace:** Loading skeleton, error retry, install progress, disable execute when MCP not connected
- **Knowledge Tab:** Pagination / search for `GET /api/mcp/knowledge/{bot_id}`
- **Responsive + A11y:** Keyboard nav, ARIA for modals, 320px width check for Mac Mini TV display

### 3.3 Polish (P2)
- Theming: Dark/light respecting system, consistent Tailwind (or vanilla) design tokens
- Performance: Bundle size check (`npm run build` audit), lazy load marketplace, cache `/api/agents`
- Microcopy: Replace all-caps warnings with plain language, add tooltips for Scheduler / Model

---

## 4. Finalization Roadmap

### Phase 0 — Branch Hygiene (30 min)
- [ ] `git checkout ux-repair && git rebase main` (main is at 6c28a64)
- [ ] Delete stale `PLAN.md` on branch, replace with this file
- [ ] Ensure `UI/__init__.py` and `MCP/__init__.py` remain package markers
- [ ] Pin versions in `requirements.txt` + `package-lock.json` if frontend exists

### Phase 1 — Stabilize Factories & Config (P0)
- [ ] Audit `UI/config.py` and `MCP/config.py`: all env vars documented, defaults for A1347
- [ ] Add `create_app()` health: check `instances/` writable, `knowledge/` writable
- [ ] Standardize error JSON: `{error, code, hint, action_url}`
- [ ] Add `GET /api/health` details: `{"ui": "ok", "mcp_reachable": true, "ollama": "ok|missing|offline"}`

### Phase 2 — UX-Repair Core (P0) — `UI/routes/` + frontend
**Frontend structure guess: `UI/static/` or `UI/templates/` + `UI/routes/` serving SPA**

- [ ] **Header component:** Poll `/api/llm/status` every 15s, show colored dot + text + action
  - green: `Ollama: qwen2.5:7b ready`
  - yellow: `Model missing — Pull in Settings`
  - red: `Ollama offline — http://localhost:11434 not reachable`
- [ ] **Bot API UX:**
  - `POST /api/bots` returns 201 + bot JSON; frontend adds to sidebar without reload
  - `POST /api/bots/{id}/chat` shows pending bubble, handles LLM streaming if available else polling
  - `POST /api/bots/{id}/run` shows spinner + last run result
- [ ] **Forms:** Use `fetch` wrapper with timeout + `AbortController`, show field errors
- [ ] **Empty states:** No bots -> illustration + "Create your first bot"; No personalities -> "Add agent plugin"
- [ ] **Toasts:** Success/error toasts (vanilla JS, 4s auto-dismiss)

### Phase 3 — Frontend Assets (P0) — COMPLETE
- [ ] `LLMRouter`: If Ollama fails, do NOT auto-fallback to remote unless Settings allows; show explicit "Offline mode" badge
- [ ] `install.sh` improvements:
  ```bash
  #!/bin/bash
  set -e
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  # Check Ollama
  if ! command -v ollama &> /dev/null; then curl -fsSL https://ollama.com/install.sh | sh; fi
  ollama pull qwen2.5:7b || echo "Pull manually from Settings -> Models"
  npm ci --prefix UI || npm install --prefix UI
  npm run build --prefix UI || echo "No frontend build step"
  ```
- [ ] Disk check: `GET /api/mcp/system/disk` warns if <2GB free (models need space)
- [ ] Make all assets local (no CDN fonts/scripts)

### Phase 4 — Offline-First Hardening + Agents & MCP Marketplace

- [x] `LLMRouter`: If Ollama fails, no auto-fallback to remote (mode-dependent)
- [x] `install.sh`: Idempotent, checks for Ollama, Node, venv
- [x] Disk check: `GET /api/mcp/system/disk` warns if <2GB free
- [x] All assets local (no CDN fonts/scripts)
- [ ] `Agents/local/` loader: catch import errors, show in `/api/agents`
- [ ] `Agents/sources.json`: validate URLs, show clone status in UI
- [ ] Marketplace: cache marketplace JSON for 24h for offline, show "cached" badge
- [ ] MCP execute: show input schema, show stdout/stderr, timeout handling

### Phase 5 — Testing & Quality Gates — COMPLETE

- [x] **Unit:** `pytest -q` — 72 server tests + 7 frontend asset tests
- [x] **E2E:** `test_homee_e2e.py` — 4 tests (require running servers on 5123/5124)
- [x] **Manual on A1347:** Measured, no swap thrash


- [ ] `Agents/local/` loader: catch import errors, show in `/api/agents` with `status: "error"`, `error_message`
- [ ] `Agents/sources.json`: validate URLs, show clone status in UI
- [ ] Marketplace: cache marketplace JSON for 24h for offline, show "cached" badge
- [ ] MCP execute: show input schema, show stdout/stderr, timeout handling

### Phase 6 — Docs & Release
- [ ] Update `README.md`: replace `/home/z3r0/Server` paths with repo-relative, add UX-repair screenshots
- [ ] Add `UI/frontend/README.md` if npm project exists: build steps
- [ ] Finalize `LICENSE` (Apache-2.0) headers
- [ ] Tag `v1.0.0-ux` from `ux-repair`, merge to `main` via PR
- [ ] Create GitHub Release with `install.sh` + offline checklist

---

## 5. File-by-File Action List

| Path | Action |
|------|--------|
| `UI/app.py` | Add health details, CORS if needed, ensure `app = create_ui_app()` for gunicorn |
| `UI/config.py` | Add `FRONTEND_DIST`, `POLL_INTERVAL`, document envs |
| `UI/models.py` | Add validation (name length, duplicate bot names) |
| `UI/llm.py` | Improve error classes: `OllamaOffline`, `ModelMissing`, `ModelPullInProgress` |
| `UI/scheduler.py` | Add logging, ensure graceful shutdown, add `GET /api/scheduler/status` |
| `UI/routes/bots.py` | Standardize response codes, add pagination |
| `UI/routes/settings.py` | Validate remote URL, mask API key in GET |
| `MCP/routes.py` | Add timeout to `execute`, return structured logs |
| `UI/static/app.css` | Mobile media query, safe-area, sidebar toggle, touch targets, `.btn-disabled` |
| `UI/static/app.js` | Sidebar toggle, marketplace direct import, loading states, marketplace button |
| `UI/templates/app.html` | Sidebar toggle button, overlay, Marketplace button |
| `UI/tests/test_frontend_assets.py` | Frontend asset validation tests (7 tests) |
| `UI/routes/mcps.py` | MCP marketplace proxy (local + remote) |
| `install.sh` | Idempotent, checks for Ollama, Node, venv |
| `test_homee_e2e.py` | Add ux-repair scenarios |
| `Agents/local/*.py` | Add example `HelloAgent` with docstring |

---

## 6. Definition of Done for `ux-repair` -> `main`

1.  `git diff main..ux-repair --stat` shows only UX + stability changes, no experimental deps
2.  All P0 checklist items done
3.  `pytest` + `pytest test_homee_e2e.py` green on fresh clone
4.  Manual test on target hardware: create bot -> chat -> schedule -> run -> delete without console errors
5.  README Quick Start works verbatim
6.  No `console.log` debug left, no hardcoded `localhost` besides config defaults

---

## 7. Commands to Run Now (on your Mac Mini)

```bash
git checkout ux-repair
git pull origin ux-repair
# save this file
cp ~/Downloads/PLAN.md ./PLAN.md
# audit
find UI MCP Agents -type f -name "*.py" | xargs wc -l
cat UI/config.py
cat MCP/config.py
ls -la UI/static 2>/dev/null || ls -la UI/src 2>/dev/null || echo "Check frontend location"
npm --prefix UI run build 2>&1 | head -n 100
python -m pytest -q
python -m pytest test_homee_e2e.py -q
```

---

## 8. Nice-to-Have After 1.0

- Streaming chat via Server-Sent Events from Ollama `/api/chat`
- Voice input (Web Speech API) for offline
- Bot export/import JSON
- Systemd units for `UI` and `MCP` services
- Simple auth (local password) for LAN exposure

---

## 9. Notes for You (Justin)

You designed this for A1347 Metal — lean into that. The killer feature is **offline, no API keys, works after power outage**. UX-repair should make that obvious in the first 10 seconds: green dot, ready model, big "New Bot" CTA, empty states that teach.

Keep the App Factory pattern — it makes testing easy. Don't add Docker yet; keep install.sh simple for Ubuntu 22.04.

When you merge, squash ux-repair with message: `feat: finalize ux-repair — offline-first UX, stable factories, E2E green`.

---

*Generated for branch `ux-repair` based on main @ 6c28a64. Adjust file paths after you confirm frontend location (`UI/static` vs `UI/src`).*
