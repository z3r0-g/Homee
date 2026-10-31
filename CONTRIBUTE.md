# Contributing to Homee

Homee is an offline-first AI Agent platform designed to be extensible through two complementary tool mechanisms: **Skills** and **MCP Servers**.

Homee discovers skills from two places, and both work the same way: put files in a directory, and Homee scans them.

- **Local:** `Skills/local/*.py` in this repo (scanned on startup).
- **Remote:** any public git repo, synced from the UI — open **Settings → Skills**, paste the repo URL, and press **Sync Skills**. Homee clones it to `Skills/remote/<repo-name>` (depth 1) and pulls `--ff-only` on every re-sync.

A repo can ship **skill Python scripts**, **skill MD files**, or both. Files whose names start with `_` are skipped.

> **Trust note:** skill `.py` files are imported and executed in-process. Only sync repos you trust, the same way you would only install software you trust.

---

## 1. Skill Scripts (`.py`)

Subclass `SkillBase` from `Skills/app.py`. Homee finds every subclass in every scanned `.py` file — one file may hold several skills.

```python
from Skills.app import SkillBase

class TideSkill(SkillBase):
    name = "Tide Agent"
    description = "Harbour tide times and warnings."
    system_prompt = (
        "You are a harbour assistant. Answer tide questions briefly "
        "and always give the next high and low tide."
    )
    model = "llama3.2:3b"  # use a full tag: bare "llama3.2" resolves to :latest
```

### Key SkillBase Properties

| Field | Meaning |
| --- | --- |
| `name` | Display name. Also the skill's id in the UI and the toggle/disable key. |
| `description` | One line summary, shown on the skill card and marketplace. |
| `system_prompt` | The persona and system instructions used during bot chats and runs. |
| `model` | Model for this skill (defaults to the host's configured model). |
| `tools` | Optional list of plain Python callables. Each becomes an LLM tool. |

### MCP Tool Access in Skills

Every skill execution turn automatically receives access to all host MCP servers and bot-assigned MCPs:
- Built-in MCPs: `mcp_system_disk`, `mcp_system_shell`
- User-installed MCPs: `mcp_<server_id>` (e.g. `mcp_github`, `mcp_fetch`, `mcp_slack`, `mcp_weather`, etc.)

Tool results are JSON-serialized and returned to the model automatically.

### Multimodal Image Support

If your skill generates diagrams or images (e.g. SVG, base64 data URIs, or URLs), include them in your response as standard Markdown:
```markdown
![Generated Chart](data:image/png;base64,iVBORw0KGgo...)
```
The Chat UI automatically renders these as responsive images with captions.

---

## 2. Skill Markdown Files (`.md`)

A skill can also be defined declaratively via Markdown with YAML frontmatter:

```markdown
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
- `name` is required. `id` defaults to the file stem (`librarian.md` → `librarian`).
- Re-syncing **upserts by id**: edit a skill in your repo, press **Sync Skills** in the UI, and Homee picks up the update.

---

## 3. Contributing MCP Servers

Homee integrates with the **Official Model Context Protocol Registry** (`registry.modelcontextprotocol.io`) and **Smithery**.

To make your MCP server available in Homee:
1. Ensure your server exposes an HTTP or SSE endpoint.
2. If your server requires authentication, specify `requires_auth: true` and document the required environment variable or header (`Authorization: Bearer <token>` or `x-api-key: <key>`).
3. Servers without authentication install in **one click** with zero configuration required.

---
## 4. Local Development Setup

1. Clone the repository:

```bash
git clone https://github.com/z3r0/homee.git
cd homee
```

2. Use devcontainer for automated setup or set up a Python virtual environment and install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Install Ollama:

```bash
brew install ollama
```

4. Start the MCP service:

```bash
python -m MCP.app
```

5. Start the UI service:

```bash
python -m UI.app
```

>Access the platform in your browser at `http://localhost:5001` (or at its local network IP from another device).

---

## 5. Testing Your Contributions

Before submitting pull requests:
```bash
# Run unit & integration tests
pytest UI/tests MCP/tests Skills/tests

# Run Playwright E2E browser tests
pytest test_homee_e2e.py

# Run full test suite
pytest
```

>Ensure all tests pass before submitting.
