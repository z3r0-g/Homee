# Contributing skills to Homee

Homee discovers skills from two places, and both work the same way: put
files in a directory, and Homee scans them.

- **Local:** `Skills/local/*.py` in this repo (scanned on startup).
- **Remote:** any public git repo, synced from the UI — open **Settings →
  Skills**, paste the repo URL, and press **Sync Skills**.
  Homee clones it to `Skills/remote/<repo-name>` (depth 1) and pulls
  `--ff-only` on every re-sync.

A repo can ship **skill Python scripts**, **skill MD files**, or
both. Files whose names start with `_` are skipped.

> **Trust note:** skill `.py` files are imported and executed in-process.
> Only sync repos you trust, the same way you would only install software
> you trust.

## Repo layout

```
my-agents/
├── weather.py              # a SkillBase subclass (code skill)
├── librarian.md          # a skill (data only)
└── README.md               # what your agents do (optional, recommended)
```

## Agent scripts (`.py`)

Subclass `SkillBase` from `Skills/app.py`. Homee finds every subclass in
every scanned `.py` file — one file may hold several agents.

```python
from Skills.app import SkillBase

class TideSkill(SkillBase):
    name = "Tide Agent"
    description = "Harbour tide times and warnings."
    system_prompt = (
        "You are a harbour assistant. Answer tide questions briefly "
        "and always give the next high and low tide."
    )
    model = "llama3.2:3b"  # use a full tag: bare "llama3.2" resolves to
                           # :latest, which an installed llama3.2:3b does
                           # NOT satisfy, and first chat will fail.
```

The fields that matter:

| Field | Meaning |
| --- | --- |
| `name` | Display name. Also the agent's id in the UI and the toggle/disable key. |
| `description` | One line, shown on the agent card. |
| `system_prompt` | The system prompt every chat turn starts with. |
| `model` | Ollama model for this agent (defaults to the platform default). |
| `tools` | Optional list of plain Python callables. Each becomes an Ollama tool; the function name and docstring are what the model sees, so document them well. |

You normally do not override `execute()` — the base implementation builds
the system + history + user messages, calls Ollama with your tools, and
returns a `SkillResult`. Override it only when a skill needs custom
control flow (for example, calling an MCP before answering).

Keep skill modules dependency-light: the standard library, `ollama`, and
`Skills.app` are safe. Anything else must be installed on the host or the
module is skipped (the skip is logged, not fatal).

## Skill MD files

A skill is data, not code: a name, a system prompt, and optional
skills/abilities. It appears in the **New Bot** skill picker and in
**Settings → Skills** after a sync.

```md
---
name: Librarian
description: Precise answers with sources, no guessing.
---

You are a careful librarian. If you do not know something, say so, and never invent a citation.

## Skills
- research
- summarizing

## Abilities
- cite-sources
```

Rules:

- `name` is required. `id` defaults to the file stem (`librarian.md` →
  `librarian`) when omitted.
- One skill per file; ship several skills as several files.
- Unknown sections are ignored; missing `description`, `skills`, and
  `abilities` default to empty.
- Re-syncing **upserts by id**: edit a skill in your repo, press
  **Sync Skills** again, and Homee picks up the edit.

## Loading your repo in Homee

1. Push the repo somewhere Homee can clone (GitHub, Gitea, a local git
   server — anything `git clone` understands).
2. Open Homee → **Settings → Skills**.
3. Paste the repo URL into **Remote Skills Repo** and press **Sync Skills**.
4. Your skills appear under **Active Skills** (local skills are enabled
   by default; the ✕ button disables any skill, the ✓ re-enables it),
   and your skills appear in the **New Bot** picker.
5. Create a bot, pick the skill, and chat.

To test locally before pushing, drop skill modules into `Skills/local/`
(restart the UI service — discovery runs on startup) or skill MD files
directly into `Skills/` (picked up on next load).

## Checklist before sharing a repo

- [ ] Every skill has a distinct `name` (collisions overwrite silently).
- [ ] Every `model` uses a full tag (`llama3.2:3b`, not `llama3.2`).
- [ ] Skill modules import cleanly with only stdlib + `ollama` + `Skills.app`.
- [ ] Skill MD parses (frontmatter + sections as above).
- [ ] A README says what each skill does and what model it expects.
