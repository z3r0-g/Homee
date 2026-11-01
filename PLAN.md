# Homee Plan to v1

> **Goal:** A simple, self-hosted home AI solution that runs on repurposed/low-end hardware (my use case: Mac Mini A1347 w/8GB RAM, CPU-only LLM). A simpler alternative to Open WebUI (no workspaces, admin panels, or plugin stores). If a feature needs a manual, it doesn't ship.

**Vision:** Home Assistant owns devices and voice satellites. Homee owns autonomous reasoning on trash-to-treasure hardware.

**Non-Goals (intentionally not built):**
- No Zigbee/Matter/Z-Wave drivers
- No Workspaces or Multi-tenant Auth
- No Vector Database (chat uses full-content injection)
- No GPU needed
- No cloud dependencies out-of-the box
- No voice (STT/TTS/wake word/satellites). HA owns that; Homee does not build or proxy it
- No OpenAI-compatible API server in v1 (its main use case is voice/Assist, which is out of scope)

**Design Rules:**
1. JSON File Repos (no DB required)
2. Ollama-first LLM integration
3. One in-flight op per bot, background tasks survive bot switch
4. Plain-language errors, live Ollama status pill, progress on model pulls

**Scope Guard (applies to every chapter below):** a new item ships only if it (a) works with zero manual reading, (b) stores state as JSON/JSONL files, (c) fits in 8GB RAM CPU-only, and (d) is off by default if it can change anything in the outside world.

## Current State Review

**Confirm Ship Ready:**
- `UI/model_catalog.py` RAM-aware default, Default badge, ollama.com-style cards, pull modal, green loaded + unload, primary/secondary slot dropdowns
- `UI/routes/llm.py` `/api/llm/catalog`, `/api/llm/status`, `/api/llm/pull`, `DELETE /models/{name}`, `/api/server-health`
- MCP: `/api/mcp/local`, `/remote`, `/import/{id}`, `/enable/{id}`, `/disable/{id}`, search box on cached catalog (no refetch per keystroke)
- Skills/Personalities: Active/Disabled, toggle, git sync that imports JSON + `SkillBase` code
- Chat: bot-info meta line (skill, schedule, last run, run count), Edit Bot modal (PUT), per-bot `working` in sidebar, fetch never aborted on switch, history refresh on return, composer disabled while busy
- Composer: starter chips (task prompt + "What can you do?"), Fast/Smart segmented switch wired via `model` field on chat route
- Settings: Local + Local / Local + Cloud / Local + Remote Local modes, scheduler as general setting above tabs, sticky tab nav

## Chapter 1: Complete the 5-Feature Contract — ✅ Done

### 1.1 Ask About a File — ✅ Done
- Frontend: paperclip in composer, `accept=.txt,.md,.json,.py,.log` < 1MB, show chip with filename + size + remove X
- Backend: `POST /api/bots/{id}/chat` accepts optional `multipart/form-data` with `file` field, reads as utf-8 (ignore errors), truncates to 12k chars, injects as:
  ```
  [User attached file: name.txt (1234 chars)]
  <file content>
  ```
- Constraints: file lives only in open chat view, dropped on bot switch or reload, never written to `UI/instances/`
- Tests: file injection, truncation, binary rejection
- Follow-up tuning is tracked in Chapter 4 (configurable cap, progress indicator)

### 1.2 Search Across Chats — ✅ Done
- Backend: `GET /api/search?q=` scans `UI/instances/bots/*/history.jsonl` in memory (no embeddings), returns top 20 with `bot_id`, `timestamp`, `snippet`
- Frontend: one input in sidebar above bot list, debounced 200ms, click opens bot and scrolls to match
- Performance: <100ms on Mini with 10k messages (linear scan is fine, no index needed)

**Definition of Done:** Both features marked Available in README, 2 new Playwright tests. ✅ Met — see `UI/tests/test_files_search.py` (unit) and `test_homee_e2e.py::test_file_attach_chip_and_send` / `::test_search_across_chats` (Playwright).

## Chapter 2: MQTT Bridge (Homee -> HA) — SkillBase Spec

**Purpose:** Let Home Assistant discover Homee bots as entities. Homee stays brain, HA stays device/voice hub. No Zigbee code in Homee. This chapter pushes Homee out to HA; Chapter 3 pulls HA in.

### 2.1 SkillBase Contract (extended)
```python
class SkillBase:
    name: str
    description: str
    system_prompt: str  # injected into bot
    allowed_mcp: list[str] = []   # deny by default (see Ch 5)
    def execute(self, context: dict, params: dict) -> dict: ...
    def start(self, app_context: dict) -> None: ...   # NEW, optional: long-lived work (MQTT loop)
    def stop(self) -> None: ...                       # NEW, optional: clean shutdown
```

Why: `execute()` is request/response, but MQTT needs a long-lived subscriber. `start()`/`stop()` are called by the skill loader when a skill is enabled/disabled. Skills that don't need them ignore both.

All skills live in `Skills/local/*.py` scanned for `SkillBase` subclasses + remote Git via `Skills/sources.json`.

### 2.2 New Skill: `Skills/local/mqtt_bridge.py`

**Class:** `MQTTBridgeSkill(SkillBase)`

**Config (non-secret in `settings.json`, secrets in `MCP/instances/` only, never in both, never in Git):**
```json
{
  "mqtt_broker": "mqtt://homeassistant.local:1883",
  "mqtt_base_topic": "homee",
  "mqtt_discovery_prefix": "homeassistant"
}
```
`mqtt_user` / `mqtt_password` live in `MCP/instances/mqtt_credentials.json`.

**Entities per exposed bot (two, so every topic has a valid HA entity type):**

1. **Status sensor.** Topic `homeassistant/sensor/homee_{bot_id}/config`
```json
{
  "name": "Homee {bot.name} Status",
  "unique_id": "homee_{bot_id}_status",
  "state_topic": "homee/bot/{bot_id}/status",
  "json_attributes_topic": "homee/bot/{bot_id}/attributes",
  "availability_topic": "homee/availability",
  "device": {
    "identifiers": ["homee_{host_id}"],
    "name": "Homee",
    "model": "{detected_model}",
    "manufacturer": "z3r0-g/Homee"
  }
}
```
2. **Chat input (MQTT `text` entity).** Topic `homeassistant/text/homee_{bot_id}_chat/config`, with `command_topic: homee/bot/{bot_id}/chat`, same `device` and `availability_topic`.

Sensors have no `command_topic`, which is why the chat input is a separate `text` entity. Automations can also publish straight to `homee/bot/{id}/chat`.

**Behavior:**
- `start()` connects, sets a **Last Will** on `homee/availability` (`offline`, retained), publishes `online` (retained) on connect, then announces discovery for each bot with `mqtt_exposed: true`. Entities show "unavailable" in HA if Homee stops.
- Subscribes to `homee/bot/+/chat`. On message, calls `UI/llm.py` LLMRouter with that bot's skill + history and publishes the reply to `homee/bot/{id}/response`.
- **Busy handling (Design Rule 3):** if the bot already has an op in flight, publish `{"error":"busy"}` to `/response` immediately. No queue, no unbounded backlog.
- Status topic carries only `idle | working | error` (HA sensor state is capped at 255 chars; never put replies there).
- Attributes topic: `{last_run, run_count, primary_model, secondary_model, schedule}`.
- `{detected_model}` comes from the host (`sysctl hw.model` on macOS, `/sys/devices/virtual/dmi/id/product_name` on Linux), not hardcoded.

**Bot Integration:**
- No change to the `Bot` model. Bridge is opt-in: enable the skill in Settings → Skills, then each bot gets a toggle "Expose via MQTT".
- When enabled, the bot's `BotConfig` gets `mqtt_exposed: true`.

**Security:**
- No shell execution via MQTT. Only the chat route. Shell MCP remains behind `MCP_service` auth.
- Discovery messages retained, status non-retained, availability retained.
- Inbound chat payloads are capped (e.g., 2k chars) and treated as untrusted user text.

**Implementation notes:**
- `paho-mqtt>=2.0` requires `mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, ...)`; the old constructor signature raises.
- Run the paho network loop on its own thread via `loop_start()`; hand work to the same per-bot lock the UI uses.

**Tests:**
- Unit: discovery payload schema for both entities, topic formatting, busy reply, availability/LWT config
- E2E: mock paho-mqtt, announce → HA discovery → chat → response roundtrip

**Files to add:**
- `Skills/local/mqtt_bridge.py`
- `UI/routes/mqtt.py` (optional status proxy `GET /api/mqtt/status`)
- `requirements.txt`: `paho-mqtt>=2.0`

## Chapter 3: Home Assistant Bridge (REST, HA -> Homee) — SkillBase Spec

**Purpose:** Give bots read access to home state ("is the garage open?", "summarize what's on right now") and, optionally, a narrow, human-confirmed write path. HA stays the device hub; Homee only reads and, with a tap, nudges.

### 3.1 New Skill: `Skills/local/ha_bridge.py`

**Class:** `HABridgeSkill(SkillBase)`

**Config (non-secret in `settings.json`; token in `MCP/instances/ha_token.json`, never in Git):**
```json
{
  "ha_url": "http://homeassistant.local:8123",
  "ha_allowed_domains": ["light", "switch", "sensor", "binary_sensor", "climate", "scene", "input_boolean"],
  "ha_write_enabled": false,
  "ha_write_domains": ["light", "switch", "scene", "input_boolean"],
  "ha_context_max_chars": 1500
}
```

**Actions (`execute(context, params)`):**

| action | type | behavior |
|---|---|---|
| `status` | read | pings `/api/`, returns ok/error in plain language |
| `list_entities` | read | `GET /api/states`, filtered to allowed domains, cached 30s |
| `get_state` | read | one entity: state + friendly_name + last_changed |
| `summarize_home` | read | compact one-line-per-entity text for prompt injection |
| `propose_action` | none | validates a service call against allowlists, returns it for UI confirmation (no execution) |
| `call_service` | write | only runs with a confirm token from the UI, only if `ha_write_enabled` |

### 3.2 Context Injection (no vector DB)

When a bot has `ha_context: true` in `BotConfig`, the chat route prepends:
```
[Home state as of 11:07]
light.kitchen: on | climate.hall: 68F (heating) | binary_sensor.garage_door: open (2h)
```
- Capped at `ha_context_max_chars`, recently changed first, then pinned entities.
- Pinned entities are chosen per bot in the Edit Bot modal, so a "Garage Watcher" bot only sees the garage.
- Fetched on each chat turn with a 30s cache. No polling thread.

### 3.3 Safe Write Path

Small CPU models are unreliable at free-form tool calling, so don't rely on it.

1. Bot replies normally. If it wants an action, it emits JSON constrained by Ollama's `format` schema: `{"service": "light.turn_off", "entity_id": "light.kitchen"}`.
2. `propose_action` validates: domain in `ha_write_domains`, entity exists, service on a known-safe list.
3. UI renders a **confirm chip** ("Turn off light.kitchen? [Do it] [Cancel]"). Nothing runs until tapped.
4. Scheduled/unattended bots can never write unless the entity is on an explicit per-bot `auto_allow` list.

**Hard deny, not configurable in v1:** `lock`, `alarm_control_panel`, `cover` (garage), `camera`, `shell_command`, `script`, `automation.trigger`.

### 3.4 Security
- Token is an HA long-lived token, scoped by convention to a dedicated "homee" HA user.
- Write is off by default; enabling it takes a visible toggle in Settings → Skills (and is blocked entirely by Read-Only Mode, Ch 11).
- Entity names from HA are untrusted text (prompt injection via a device name). Strip control characters, cap at 60 chars, wrap in a clearly delimited block.
- Every `call_service` is appended to `UI/instances/ha_audit.jsonl` (time, bot, entity, service, result).
- Plain-language errors: "Home Assistant didn't answer at homeassistant.local:8123. Check it's on and the token is valid."

### 3.5 Tests
- Unit: allowlist filtering, deny-list, context truncation, name sanitizing
- E2E: mock HA REST (`/api/states`, `/api/services/...`) covering read, propose, confirm, execute, audit line
- Playwright: confirm chip appears; Cancel sends nothing

### 3.6 Files to add
- `Skills/local/ha_bridge.py`
- `UI/routes/ha.py` (`GET /api/ha/status`, `POST /api/ha/confirm/{token}`)
- Edit Bot toggles: "Include home state", "Allow proposing actions"
- No new dependencies (`requests`/`httpx` already present)

**Definition of Done:** A bot answers "is the garage open?" from live HA state on the Mini. The write path demonstrably refuses a lock and requires a tap for a light.

## Chapter 4: Resource Management for Low-Grade Hardware

- **Simplest first:** ship Ollama defaults of `OLLAMA_MAX_LOADED_MODELS=1` and a short `keep_alive` (e.g., 5m, configurable). This does most of the job with almost no code.
- **Auto-unload (only if still needed after the above):** background thread in `UI/scheduler.py` checks `psutil.virtual_memory().available` (not `.percent`, which counts reclaimable cache on macOS and cries wolf). If available < 10% of total for 30s and 2 models loaded, unload LRU non-primary.
- **Context cap by RAM tier:** set `num_ctx` from detected RAM (e.g., 8GB → 2048, 16GB → 4096), overridable in Settings. A large context can OOM an 8GB box before the weights do.
- **File attach cap (follows Ch 1.1):** make the truncation limit a setting, default 6k chars (about 1.5k tokens), because prompt processing on CPU-only 8GB can take a minute for 12k. Show "reading file…" while the first token is pending.
- **Pull guard:** keep the existing 409 if a pull is running. Add a disk guard: check `MCP /api/mcp/system/disk` before pull, refuse if <5GB free with a plain message.
- **History pruning:** `UI/instances/` JSONL grows. Add `max_history_per_bot=200` in settings, oldest dropped with a notice.

## Chapter 5: Skills Ecosystem Hardening

- `CONTRIBUTE.md` already documents repo format. Add JSON schema validation in `POST /api/skills/refresh`.
- Pin Git SHA in `Skills/sources.json` (`url#sha`), add an "Update" button that pulls the latest SHA.
- Skill permissions: `SkillBase` gets `allowed_mcp: ["disk", "shell"]`, deny by default.
- Show requested permissions in plain words on the skill card before enabling ("This skill can: read Home Assistant, publish MQTT").
- Skills with side effects (Ch 2, 3, 9) must declare `writes_external = True` so Read-Only Mode (Ch 11) can disable them in one switch.

## Chapter 6: Testing, A11y, Homelab Polish

- Keep Playwright in-process on 5123/5124 with temp dirs. Add tests for file attach, search, MQTT announce, HA confirm chip, notify send, auto-unload, streaming.
- Keep a11y improvements: focus rings, Escape closes modals, live regions, `prefers-reduced-motion`.
- Keep the `-apple-system` font stack, since you target Mac Mini hardware.

## Chapter 7: Licensing — Free Community, Paid Commercial

**Current:** Apache-2.0 (allows anyone to sell without paying you).

**Intent:** Free for community / personal / homelab use; if someone else wants to sell it as a product/service, they pay.

**Recommended: Dual-license — PolyForm Noncommercial 1.0.0 + Paid Commercial License**

Why PolyForm Noncommercial over AGPL/SSPL/BSL:
- Simple, plain-language, allows personal, educational, research, homelab use; forbids selling the software or a hosted version as a paid product.
- You retain copyright and can grant separate commercial licenses for a fee.
- Less scary than AGPL for homelab users, more enforceable than Commons Clause.
- Note: it is **source-available, not OSI-approved open source**. Say so plainly in the README so nobody is misled.

**Things to settle before switching (have a lawyer review; this is not legal advice):**
- **Contributors:** to dual-license, you need a CLA or copyright assignment from anyone who contributes, or you can't relicense their code commercially.
- **Existing releases:** versions already published under Apache-2.0 stay Apache-2.0 for anyone who has them. The new license applies going forward.
- **Dependencies:** confirm all third-party dependencies permit this arrangement.

1. **Add `COMMERCIAL_LICENSE.md`:**
   ```
   Community use: free under PolyForm Noncommercial 1.0.0.
   Commercial use (selling Homee, offering hosted Homee, embedding in paid hardware):
   Contact justinblair01 [at] ... for a paid license. Typical fee: $X per unit / $Y per year.
   ```
2. **Add `LICENSES/` directory:**
   - `LICENSES/community.md` = PolyForm Noncommercial
   - `LICENSES/commercial.md` = template for paid license
3. **README footer:**
   > Free for personal and community use. Commercial use requires a paid license — see COMMERCIAL_LICENSE.md. This funds continued development for low-grade hardware.
4. **Add `CLA.md`** and a one-line contributor notice in `CONTRIBUTE.md`.

## Chapter 8: Remote Access, Backup & Mobile

- Don't build auth. Document Tailscale + Caddy as the recommended remote setup. Add an `install.sh --tailscale` flag.
- PWA: manifest + service worker for installable mobile chat (no offline, just the shell).
- **Backup:** `POST /api/backup` zips `UI/instances/` + `MCP/instances/`, excluding models.
  - **Secrets excluded by default** (MQTT, HA, notify tokens). Optional "include secrets" checkbox that encrypts the zip with a passphrase.
  - Add `POST /api/restore` and a Playwright roundtrip test. A backup you can't restore is half a feature.

## Chapter 9: Notify Bridge — SkillBase Spec (NEW)

**Purpose:** Autonomous bots currently finish silently. Pushing results to a phone is what makes "Homee owns autonomous reasoning" feel real. One POST, no new dependencies.

- New skill `Skills/local/notify_bridge.py` (`NotifyBridgeSkill`), `writes_external = True`.
- Targets (pick one in Settings → Skills): **ntfy** (default, self-hostable), **Gotify**, or **HA notify** via the Ch 3 token (`POST /api/services/notify/<target>`).
- Config: `notify_provider`, `notify_url`, `notify_topic` in `settings.json`; token in `MCP/instances/`.
- Per-bot toggle in Edit Bot: "Notify when a scheduled run finishes" with an option "only on error or change".
- Message is title (bot name) + first ~200 chars of the result + status. Never the full history.
- Rate limit: max 1 notification per bot per 5 minutes, to avoid spam from a looping schedule.
- Errors in plain language: "Couldn't reach ntfy at <url>. Check the address."
- Tests: payload per provider, rate limit, failure message; mock HTTP.

## Chapter 10: Responsiveness on Slow Hardware (NEW)

CPU-only inference runs at a few tokens per second. Making that visible is cheaper than making it faster.

- **Streaming responses (SSE)** on the chat route using Ollama's streaming API. Composer stays disabled while busy (Design Rule 3); a Stop button cancels only the current reply.
- **Speed readout:** show tokens/sec under each reply (Ollama returns `eval_count` and `eval_duration`) and a one-line hint like "This model runs ~3 tok/s here; Fast mode is ~9."
- **Slow-start hint:** if first token takes >10s (cold model load or long prompt), show "Loading model / reading your message…" instead of a frozen UI.
- **Stats are not stored in a DB:** append `tok_s` to the existing history JSONL line.
- Tests: streaming order, Stop mid-stream, history line includes `tok_s`.

## Chapter 11: Doctor, Templates, Export, Read-Only Mode (NEW)

### 11.1 Doctor page (`GET /api/doctor`, one screen)
Checks, each with a green/yellow/red dot and a plain-language fix:
- Ollama reachable, selected models pulled
- RAM available, disk free
- MQTT broker connected (if the skill is on)
- HA reachable and token valid (if the skill is on)
- Notify target reachable (if the skill is on)

This is the cheapest way to honor "if a feature needs a manual, it doesn't ship."

### 11.2 Bot templates
Ship 4-5 ready-made bots as JSON in `Skills/` or `Personalities/`: **Garage Watcher** (needs Ch 3), **Morning Brief**, **Log Summarizer**, **Note Helper**, **Plain-English Explainer**. A "Create from template" list replaces the blank first-run page. Templates are plain JSON, so they work with git sync.

### 11.3 Chat export
`GET /api/bots/{id}/export?format=md|json` returns the history file as Markdown or JSON. Nearly free given JSONL storage.

### 11.4 Read-Only Mode
One switch in Settings that disables every skill marked `writes_external = True` (HA writes, MQTT publish, notify) and shell MCP. The UI shows a persistent badge while it is on. Good for guests, travel, and peace of mind.

## Chapter 12: Skill Utility Refinement — Test-Defined Behavior (NEW)

**Purpose:** Each local skill earns its place by being *useful*, and usefulness is pinned by tests. The contract suite (`Skills/tests/test_skill_contract.py`) already guarantees the mechanics for every skill — `SkillBase` subclass, `execute()` signature, `SkillResult` return, system-prompt injection, MCP tool gating. This chapter defines the *utility* bar per skill: what each one must actually be good at, as tests.

**Rule:** before changing a skill's behavior, write the test that defines the new utility. No test, no behavior change. Utility tests live in `Skills/tests/test_<skill>_utility.py` and run in the default suite with all external dependencies mocked (no Ollama, no Docker, no network, no MCP service).

### 12.1 Demo (System Skill)
- **Utility bar:** accurate server health report, live process snapshot, safe disk/shell tools.
- **Tests to define:** health report renders disk/memory/CPU sections with bars and trends; `ps` output parses into the aligned table; missing `htop` falls back to the psutil summary line (never `top`); ANSI escapes stripped; shell tool honors its timeout.

### 12.2 Burgundy (Weather Skill)
- **Utility bar:** friendly, accurate forecast from a zip, lat/long, or browser geolocation — imperial and metric.
- **Tests to define:** location resolution precedence (zip > lat/long > location string > plain-language error); metric vs imperial field selection; "Stay classy" sign-off present; HTTP error and connection error produce plain-language messages (partially covered in `Skills/tests/test_skills.py` — extend, don't duplicate).

### 12.3 HomeKeeper (Uptime & Backups)
- **Utility bar:** deterministic steward — instant answers with no LLM loaded.
- **Tests to define:** disk >80% used triggers the alert line; Ollama down triggers an alert; health check appends to `knowledge_path`; vault inventory reflects only the bot's assigned MCPs; unrecognized requests return the health+briefing default; MCP executor absent → dry-mode output, no crash.

### 12.4 Shipwright (SRE Skill)
- **Utility bar:** container health and logs with hard guardrails on destructive actions.
- **Tests to define:** Docker unavailable → plain-language error, no crash; destructive tool without `confirmed_by_admin` is refused; log fetch truncates to the requested tail; health report counts running vs stopped containers.

**Definition of Done:** all four utility suites exist and pass; each covers the happy path plus the "dependency missing" path. A skill that can't pass its utility bar is fixed or removed from `Skills/local/`.

## Suggested Ship Order

1. ~~Ch 1~~ ✅ done: file attach + cross-chat search
2. Ch 12: skill utility tests (locks in what every shipped skill is good at)
3. Ch 4 (defaults only): `OLLAMA_MAX_LOADED_MODELS=1`, `keep_alive`, `num_ctx` tiers, file cap setting
4. Ch 10: streaming + tok/s (biggest felt-quality gain on slow hardware)
5. Ch 11.1 + 11.2: Doctor and templates (first-run experience)
6. Ch 3: HA read-only first, write path behind the toggle after
7. Ch 9: notify
8. Ch 2: MQTT bridge
9. Ch 5, 6, 8: hardening, tests, backup/restore
10. Ch 7: licensing (once CLA and legal review are done, before the v1 tag)

## Explicitly Deferred (not in v1)

- Voice of any kind (STT, TTS, wake word, satellite handling)
- OpenAI-compatible `/v1/chat/completions` endpoint
- Any native device protocol drivers
- Multi-user auth or per-user bots
