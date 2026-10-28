# Homee — Full rebrand: Agents/Personalities → Skills

Checkpoint plan (committed first so a later session can resume if credits run out).
Branch: `ux-repair`. Prior work on this branch: pill CSS + cache-busting,
Skills UI rebrand, leaderboard tabs (MCP + Skills). This plan covers only the
deep rebrand below.

## Decisions (user, 2026-10-27)
- Feed method: BACKLOG. Skills + MCP remote content are static snapshots,
  not live feeds. Nothing feed-related ships here.
- Skill MD files live in `Skills/` (repo root), NOT `UI/instances/skills/`.
- NO compat shims: no `AgentBase` alias, no settings/env/bot-field fallbacks,
  no legacy remote JSON import. Consequences (accepted): bots lose their
  skill assignment once (re-pick it); settings `agents` key is ignored;
  remote `.py` plugins must subclass `SkillBase`.
- `UI/routes/personalities.py` + `UI/routes/agents.py` merge into ONE
  `UI/routes/skills.py` (both would otherwise be `skills.py`).
- MD format (SKILL.md-style, no new dependency): frontmatter
  `name`/`description`/`model` + system-prompt body + `## Skills` /
  `## Abilities` bullet lists + `## Guardrails` / `## Tools` as ```json
  fences. One file per skill: `Skills/<id>.md`. Parser/writer:
  `UI/skill_md.py` (dependency-free frontmatter parser).
- Skill store: a directory of `.md` files (replaces single
  `personalities.json`). First load migrates a legacy `personalities.json`
  if present: writes `.md` files, renames the JSON to `.bak`. This is the
  ordered JSON→MD conversion, not a compat shim.
- Verified 2026-10-27: the old `UI/instances/personalities/*.json`
  definition files do NOT exist on `ux-repair` (absent from the branch).
  No definition files ship as `.md` here; local skills are the
  `Skills/local/*.py` plugins, and `.md` files appear as users create
  skills (modal) or sync repos. The main-branch definitions are recoverable
  from git history if ever wanted as `.md`.

## File map
- `Agents/` → `Skills/` (`app.py`, `registry.py`, `sources.json`,
  `local/*.py`, `tests/test_agents.py` → `test_skills.py`).
- `UI/routes/skills.py` (merged, blueprint `skills_bp`).
- `UI/models.py`: `Personality` → `Skill`, `personalities_repo` →
  `skills_repo`, `Bot.personality_id` → `skill_id`.
- `UI/config.py`: `PERSONALITIES_DIR` → `SKILLS_DIR` (repo-root `Skills/`).
- `UI/routes/bots.py`, `UI/routes/settings.py`, `UI/app.py`: call updates.
- `UI/static/app.js`, `UI/templates/app.html`, `UI/static/app.css`:
  identifier + route sweep (see below).
- Docs: `README.md`, `CONTRIBUTE.md` (MD skill format, new routes),
  `install.sh` (paths).
- Delete: `Agents/*`, `UI/routes/agents.py`, `UI/routes/personalities.py`.

## Identifier map
- `AgentBase` → `SkillBase`, `AgentResult` → `SkillResult`,
  `AgentRegistry` → `SkillRegistry`, `agent_registry` → `skill_registry`,
  `AGENT_MODEL` → `SKILL_MODEL` (value still from `OLLAMA_MODEL`).
- Plugin classes `*Agent` → `*Skill`; display names `* Agent` →
  `* Skill` (e.g. `Burgundy (Weather Skill)`).
- `list_agents`/`get_agent` → `list_skills`/`get_skill`;
  `REMOTE_DIR`/`LOCAL_DIR` → `Skills/remote`, `Skills/local`.
- Routes: `/api/skills/*` (list, CRUD, active, toggle, import-git,
  available, sources, refresh, leaderboard). Response keys `skills`,
  `skills_imported`. Item `type`: `skill` (with `source`: `saved` /
  `discovered`).
- Settings key `agents` → `skills`; env prefix `AGENT_` → `SKILL_`.
- Frontend: `loadPersonalitiesForNewBot` → `loadSkillsForNewBot`,
  `renderAgentPersonalities` → `renderSkills`,
  `resolvePersonalityName` → `resolveSkillName`, `bot.personality_id` →
  `bot.skill_id`, `/api/personalities` + `/api/agents/*` → `/api/skills/*`,
  DOM ids `personality*` → `skill*` (`skillModal`, `skillForm`, `skillName`,
  `skillDescription`, `skillSkills`, `skillAbilities`, `skillSystemPrompt`,
  `skillList`, `newBotSkill`, `editBotSkill`), `data-tab`/`tab-skills`,
  CSS `personality-*` → `skill-*`.

## Order
1. This file — commit alone as checkpoint.
2. `Skills/` package (renamed files + identifiers + registry paths).
3. `UI/skill_md.py` + Skill model + dir-based SkillRepository + migration.
4. `UI/routes/skills.py` (merged) + `app.py`/`bots.py`/`settings.py`/
   `config.py` call updates.
5. Frontend sweep (`app.js`/`app.html`/`app.css`).
6. Docs + `install.sh`.
7. Tests + push + delete old paths + read-back verify.

## Verification
- `pytest UI/tests Skills/tests` green; `node --check app.js`;
  smoke `GET /` + `GET /api/skills/leaderboard`.
- Branch read-back: no `Agents/` paths, no `personalities.py`/`agents.py`,
  no `/api/agents` or `/api/personalities` strings in code, no `AgentBase`
  or `agent_registry` references outside this plan.
