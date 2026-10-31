# Homee Plan to v1

> **Goal:** A simple, self-hosted home AI solution that runs on repurposed/low-end hardware (my use case: Mac Mini A1347 w/8GB RAM, CPU-only LLM). A simpler alternative to Open WebUI (no workspaces, admin panels, or plugin stores). If a feature needs a manual, it doesn't ship.

**Vision:** Home Assistant owns devices and voice satellites. Homee owns autonomous reasoning on trash-to-treasure hardware.

**Non-Goals (intentionally not built):**
- No Zigbee/Matter/Z-Wave drivers
- No Workspaces or Multi-tenant Auth
- No Vector Database (chat uses full-content injection)
- No GPU needed
- No cloud dependencies out-of-the box

**Design Rules:**
1. JSON File Repos (no DB required)
2. Ollama-first LLM integration
3. One in-flight op per bot, background tasks survive bot switch
4. Plain-language errors, live Ollama status pill, progress on model pulls

## Current State Review

**Confirm Ship Ready:**
- `UI/model_catalog.py` RAM-aware default, Default badge, ollama.com-style cards, pull modal, green loaded + unload, primary/secondary slot dropdowns
- `UI/routes/llm.py` `/api/llm/catalog`, `/api/llm/status`, `/api/llm/pull`, `DELETE /models/{name}`, `/api/server-health`
- MCP: `/api/mcp/local`, `/remote`, `/import/{id}`, `/enable/{id}`, `/disable/{id}`, search box on cached catalog (no refetch per keystroke)
- Skills/Personalities: Active/Disabled, toggle, git sync that imports JSON + `SkillBase` code
- Chat: bot-info meta line (skill, schedule, last run, run count), Edit Bot modal (PUT), per-bot `working` in sidebar, fetch never aborted on switch, history refresh on return, composer disabled while busy
- Composer: starter chips (task prompt + "What can you do?"), Fast/Smart segmented switch wired via `model` field on chat route
- Settings: Local + Local / Local + Cloud / Local + Remote Local modes, scheduler as general setting above tabs, sticky tab nav

## Chapter 1: Complete the 5-Feature Contract

### 1.1 Ask About a File
- Frontend: paperclip in composer, `accept=.txt,.md,.json,.py,.log` < 1MB, show chip with filename + size + remove X
- Backend: `POST /api/bots/{id}/chat` accepts optional `multipart/form-data` with `file` field, reads as utf-8 (ignore errors), truncates to 12k chars, injects as:
  ```
  [User attached file: name.txt (1234 chars)]
  <file content>
  ```
- Constraints: file lives only in open chat view, dropped on bot switch or reload, never written to `UI/instances/`
- Tests: file injection, truncation, binary rejection

### 1.2 Search Across Chats
- Backend: `GET /api/search?q=` scans `UI/instances/bots/*/history.jsonl` in memory (no embeddings), returns top 20 with `bot_id`, `timestamp`, `snippet`
- Frontend: one input in sidebar above bot list, debounced 200ms, click opens bot and scrolls to match
- Performance: <100ms on Mini with 10k messages (linear scan is fine, no index needed)

**Definition of Done:** Both features marked Available in README, 2 new Playwright tests.

## Chapter 2: MQTT Bridge — SkillBase Spec

**Purpose:** Let Home Assistant discover Homee bots as entities. Homee stays brain, HA stays device/voice hub. No Zigbee code in Homee.

### 2.1 SkillBase Contract (existing)
```python
class SkillBase:
    name: str
    description: str
    system_prompt: str  # injected into bot
    def execute(self, context: dict, params: dict) -> dict: ...
```

All skills live in `Skills/local/*.py` scanned for `SkillBase` subclasses + remote Git via `Skills/sources.json`.

### 2.2 New Skill: `Skills/local/mqtt_bridge.py`

**Class:** `MQTTBridgeSkill(SkillBase)`

**Config (via `settings.json` or env):**
```json
{
  "mqtt_broker": "mqtt://homeassistant.local:1883",
  "mqtt_user": "",
  "mqtt_password": "",
  "mqtt_base_topic": "homee",
  "mqtt_discovery_prefix": "homeassistant"
}
```

**Behavior:**
- On `execute()` with `action=announce`, publishes HA MQTT discovery for each enabled bot:

Topic: `homeassistant/sensor/homee_{bot_id}/config`
Payload:
```json
{
  "name": "Homee Bot {bot.name}",
  "unique_id": "homee_{bot_id}",
  "state_topic": "homee/bot/{bot_id}/status",
  "json_attributes_topic": "homee/bot/{bot_id}/attributes",
  "command_topic": "homee/bot/{bot_id}/chat",
  "device": {
    "identifiers": ["homee_{host_id}"],
    "name": "Homee Mini",
    "model": "Mac Mini A1347",
    "manufacturer": "z3r0-g/Homee"
  }
}
```

- Subscribes to `homee/bot/+/chat` — when HA automation publishes a message, skill calls `UI/llm.py` LLMRouter with that bot's skill + history and publishes reply to `homee/bot/{id}/response`.

- Publishes status:
  - `homee/bot/{id}/status`: `idle | working | error`
  - `homee/bot/{id}/attributes`: `{last_run, run_count, primary_model, secondary_model, schedule}`

**Bot Integration:**
- No code change to `Bot` model. Bridge is opt-in: Enable skill in Settings → Skills, then each bot gets a toggle "Expose via MQTT".
- When enabled, bot's `BotConfig` gets `mqtt_exposed: true`.

**Security:**
- No shell execution via MQTT. Only chat route. Shell MCP remains behind `MCP_service` auth.
- Broker credentials stored in `MCP/instances/` not in Git.
- Discovery messages retained, status non-retained.

**Tests:**
- Unit: discovery payload schema, topic formatting
- E2E: mock paho-mqtt, announce → HA discovery → chat → response roundtrip

**File to add:**
- `Skills/local/mqtt_bridge.py`
- `UI/routes/mqtt.py` (optional status proxy `GET /api/mqtt/status`)
- `requirements.txt`: `paho-mqtt>=2.0`

## Chapter 3: Voice Satellite (Minimal)

**Goal:** Don't rebuild Whisper/Piper. Consume HA's pipeline.

- Add small client `satellite/` — Python script for ESP32-S3 / Raspberry Pi Zero 2 W that does wake-word locally (openWakeWord) and forwards STT to HA Assist, then HA forwards to Homee via MQTT chat topic.
- UI: No voice UI in Homee yet. Voice comes via HA. Later, add `POST /api/bots/{id}/voice` that accepts WAV and returns TTS via Piper (local).

**Do NOT build:** Custom wake-word training UI, TTS voice cloning.

## Chapter 4: Resource Management for Low-Grade Hardware

- **Auto-unload:** Background thread in `UI/scheduler.py` checks `psutil.virtual_memory().percent`. If >90% for 30s and 2 models loaded, unload LRU non-primary.
- **Pull guard:** Already have 409 if pull running — keep. Add disk guard: check `MCP /api/mcp/system/disk` before pull, refuse if <5GB free with plain message.
- **History pruning:** `UI/instances/` JSONL grows. Add `max_history_per_bot=200` in settings, oldest dropped with notice.

## Chapter 5: Skills Ecosystem Hardening

- `CONTRIBUTE.md` already documents repo format — add JSON schema validation in `POST /api/skills/refresh`.
- Pin Git SHA in `Skills/sources.json` (`url#sha`), add "Update" button that pulls latest SHA.
- Skill permissions: `SkillBase` gets `allowed_mcp: ["disk", "shell"]` list, deny by default.

## Chapter 6: Remote Access & Mobile

- Don't build auth. Document Tailscale + Caddy as recommended remote. Add `install.sh --tailscale` flag.
- PWA: Add manifest + service worker for installable mobile chat (no offline, just shell).
- Backup: `POST /api/backup` zips `UI/instances/` + `MCP/instances/` excluding models.

## Chapter 7: Testing, A11y, Homelab Polish

- Keep Playwright in-process on 5123/5124 with temp dirs. Add tests for file attach, search, MQTT announce, auto-unload.
- Keep a11y improvements: focus rings, Escape closes modals, live regions, `prefers-reduced-motion`.
- Keep `-apple-system` font stack — you target Mac Mini hardware.

## Chapter 8: Licensing — Free Community, Paid Commercial

**Current:** Apache-2.0 (allows anyone to sell without paying you).

**Your intent:** Free for community / personal / homelab use, but if someone else wants to sell it as a product/service, you want to get paid.

**Recommended: Dual-license — PolyForm Noncommercial 1.0.0 + Paid Commercial License**

Why PolyForm Noncommercial over AGPL/SSPL/BSL:
- Simple, OSI-approved intent, allows personal, educational, research, homelab — forbids selling the software itself or a hosted version as a paid product.
- You retain copyright, can grant separate commercial licenses for a fee.
- Less scary than AGPL for homelab users, more enforceable than Commons Clause.

**Plan:**

1. **Relicense `main` after PR #2 merge:**
   - Change `LICENSE` to PolyForm Noncommercial 1.0.0 with `Licensor: Justin Blair (z3r0-g)`
   - Keep `Apache-2.0` for code contributed before relicense? No — get contributor consent (only you so far, 0 forks). Easy.

2. **Add `COMMERCIAL_LICENSE.md`:**
   ```
   Community use: free under PolyForm Noncommercial 1.0.0.
   Commercial use (selling Homee, offering hosted Homee, embedding in paid hardware):
   Contact justinblair01 [at] ... for a paid license. Typical fee: $X per unit / $Y per year.
   ```

3. **Add `LICENSES/` directory:**
   - `LICENSES/community.md` = PolyForm Noncommercial
   - `LICENSES/commercial.md` = template for paid license

4. **In README footer:**
   > Free for personal and community use. Commercial use requires a paid license — see COMMERCIAL_LICENSE.md. This funds continued development for low-grade hardware.

**Alternative if you want copyleft teeth:** Use AGPL-3.0 + Commercial dual license (like Grafana). AGPL forces anyone hosting Homee as a service to release source, which also pushes them to buy commercial. PolyForm Noncommercial is simpler for your stated goal.

**Action:** Decide between PolyForm Noncommercial vs AGPL+Commercial, then run `git log --format=%an | sort -u` to confirm no external contributors need consent (repo shows 0 forks).

## Roadmap & Release Checklist

**v1.0 — True Home AI:**
- [ ] Finish 3.1 file attach + 3.2 search (mark Available)
- [ ] Relicense to PolyForm Noncommercial + add COMMERCIAL_LICENSE.md
- [ ] Chapter 4 MQTT Bridge Skill
- [ ] Chapter 6 auto-unload + disk guard
- [ ] Chapter 8 Tailscale docs + backup zip
- [ ] Update README positioning: "Home Assistant for devices, Homee for reasoning on a Mini"
- [ ] Tag `v1.0.0`, publish release notes with RAM test results on A1347

**v1.1 — Voice:**
- [ ] Chapter 5 satellite client docs, optional Piper TTS endpoint
