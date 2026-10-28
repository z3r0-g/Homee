"""Skill Markdown files (SKILL.md-style, dependency-free).

Format (one file per skill, ``Skills/<id>.md``)::

    ---
    name: Burgundy
    description: ...
    ---

    <system prompt>

    ## Skills
    - ...

    ## Abilities
    - ...

Only ``name``/``description`` frontmatter and the prompt + list sections
are stored; anything else in a file is ignored on read and dropped on
write, so hand-edited files stay readable.
"""
from __future__ import annotations

from typing import Any, Dict, List


def parse_skill_md(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    data: Dict[str, Any] = {"name": "", "description": "", "skills": [],
                             "abilities": [], "system_prompt": ""}
    body = lines
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                for fm in lines[1:i]:
                    if ":" in fm:
                        k, v = fm.split(":", 1)
                        if k.strip() in ("name", "description"):
                            data[k.strip()] = v.strip().strip('"').strip("'")
                body = lines[i + 1:]
                break
    section = "system_prompt"
    prompt_lines: List[str] = []
    for line in body:
        s = line.strip()
        if s.startswith("## "):
            section = s[3:].strip().lower()
            continue
        if section == "skills" and s.startswith("- "):
            data["skills"].append(s[2:].strip())
        elif section == "abilities" and s.startswith("- "):
            data["abilities"].append(s[2:].strip())
        elif section == "system_prompt":
            prompt_lines.append(line)
    data["system_prompt"] = "\n".join(prompt_lines).strip()
    return data


def render_skill_md(skill) -> str:
    out = ["---", f"name: {skill.name}", f"description: {skill.description}", "---", ""]
    if skill.system_prompt:
        out.append(skill.system_prompt)
        out.append("")
    if skill.skills:
        out.append("## Skills")
        out += [f"- {s}" for s in skill.skills]
        out.append("")
    if skill.abilities:
        out.append("## Abilities")
        out += [f"- {s}" for s in skill.abilities]
        out.append("")
    return "\n".join(out)
