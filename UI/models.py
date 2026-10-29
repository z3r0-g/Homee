"""Data models and JSON persistence for the UI service."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import (
    BOTS_DIR,
    KNOWLEDGE_DIR,
    MCPS_DIR,
    INSTANCES_DIR,
    SKILLS_DIR,
    SETTINGS_FILE,
    load_settings,
    save_settings,
)

from .skill_md import parse_skill_md, render_skill_md


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ══════════════════════════════════════════════════════════════════
# Models
# ══════════════════════════════════════════════════════════════════

@dataclass
class Skill:
    """specialized skills and abilities."""

    id: str
    name: str
    description: str
    skills: List[str] = field(default_factory=list)
    abilities: List[str] = field(default_factory=list)
    system_prompt: str = ""
    created_at: str = field(default_factory=_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Skill":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BotConfig:
    """Scheduling + execution configuration for a Bot."""

    schedule_type: str = "none"
    interval_seconds: int = 3600
    cron_expression: str = ""
    task_prompt: str = ""
    enabled: bool = False
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    run_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BotConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Bot:
    """Skill bot instance — embodies a Skill to accomplish tasks."""

    id: str
    name: str
    skill_id: str = ""
    status: str = "idle"
    created_at: str = field(default_factory=_iso)
    updated_at: str = field(default_factory=_iso)
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_base_path: str = ""
    mcps: List[str] = field(default_factory=list)
    config: BotConfig = field(default_factory=BotConfig)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["config"] = self.config.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Bot":
        cfg = d.pop("config", {})
        return cls(
            **{k: v for k, v in d.items() if k in cls.__dataclass_fields__},
            config=BotConfig.from_dict(cfg) if isinstance(cfg, dict) else BotConfig(),
        )

    def knowledge_path(self) -> Path:
        if self.knowledge_base_path:
            return Path(self.knowledge_base_path)
        return KNOWLEDGE_DIR / f"kb_{self.id}.md"


# ══════════════════════════════════════════════════════════════════
# Repository (JSON file-backed)
# ══════════════════════════════════════════════════════════════════

class BotRepository:
    def __init__(self) -> None:
        self._bots: Dict[str, Bot] = {}
        self._path = BOTS_DIR / "bots_state.json"

    def load(self) -> Dict[str, Bot]:
        data = _load_json(self._path, {}) or {}
        self._bots = {}
        for bot_id, raw in data.items():
            try:
                bot = Bot.from_dict(raw)
                if not bot.knowledge_base_path:
                    bot.knowledge_base_path = str(bot.knowledge_path())
                self._bots[bot_id] = bot
            except Exception as e:
                print(f"[UI] Error loading bot {bot_id}: {e}")
        return self._bots

    def save(self) -> None:
        data = {bid: b.to_dict() for bid, b in self._bots.items()}
        _save_json(self._path, data)

    def get(self, bot_id: str) -> Optional[Bot]:
        return self._bots.get(bot_id)

    def add(self, bot: Bot) -> None:
        self._bots[bot.id] = bot
        self.save()

    def update(self, bot_id: str, **fields: Any) -> Optional[Bot]:
        bot = self._bots.get(bot_id)
        if not bot:
            return None
        config_fields: Dict[str, Any] = {}
        for k in list(fields.keys()):
            if k == "config" and isinstance(fields[k], dict):
                config_fields.update(fields.pop(k))
            elif k in BotConfig.__dataclass_fields__:
                config_fields[k] = fields.pop(k)
        for k, v in fields.items():
            if hasattr(bot, k):
                setattr(bot, k, v)
        for k, v in config_fields.items():
            if hasattr(bot.config, k):
                setattr(bot.config, k, v)
        bot.updated_at = _iso()
        self.save()
        return bot

    def delete(self, bot_id: str) -> bool:
        bot = self._bots.pop(bot_id, None)
        if bot:
            self.save()
            kb = Path(bot.knowledge_base_path) if bot.knowledge_base_path else None
            if kb and kb.exists():
                try:
                    kb.unlink()
                except OSError:
                    pass
            return True
        return False

    def all(self) -> List[Bot]:
        return list(self._bots.values())


class SkillRepository:
    """Skills stored as one Markdown file per skill in SKILLS_DIR."""

    def __init__(self) -> None:
        self._skills: List[Skill] = []
        self._dir = SKILLS_DIR

    def load(self) -> List[Skill]:
        self._migrate_legacy()
        skills: List[Skill] = []
        if self._dir.exists():
            for path in sorted(self._dir.glob("*.md")):
                try:
                    data = parse_skill_md(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not data.get("name"):
                    continue
                skills.append(Skill(
                    id=path.stem,
                    name=data.get("name", ""),
                    description=data.get("description", ""),
                    skills=data.get("skills", []),
                    abilities=data.get("abilities", []),
                    system_prompt=data.get("system_prompt", ""),
                ))
        self._skills = skills
        return self._skills

    def save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        for skill in self._skills:
            (self._dir / f"{skill.id}.md").write_text(
                render_skill_md(skill), encoding="utf-8")

    def add(self, skill: Skill) -> None:
        self._skills.append(skill)
        self.save()

    def get(self, skill_id: str) -> Optional[Skill]:
        for s in self._skills:
            if s.id == skill_id:
                return s
        return None

    def all(self) -> List[Skill]:
        return list(self._skills)

    def delete(self, skill_id: str) -> bool:
        remaining = [s for s in self._skills if s.id != skill_id]
        if len(remaining) == len(self._skills):
            return False
        self._skills = remaining
        (self._dir / f"{skill_id}.md").unlink(missing_ok=True)
        return True

    def _migrate_legacy(self) -> None:
        """One-time: legacy single-file personalities.json -> .md files."""
        legacy = INSTANCES_DIR / "personalities" / "personalities.json"
        if not legacy.exists():
            return
        if self._dir.exists() and any(self._dir.glob("*.md")):
            return
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else []
            self._dir.mkdir(parents=True, exist_ok=True)
            for item in items:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                try:
                    skill = Skill.from_dict(item)
                    (self._dir / f"{skill.id}.md").write_text(
                        render_skill_md(skill), encoding="utf-8")
                except (KeyError, TypeError, ValueError):
                    continue
            legacy.rename(legacy.with_suffix(".json.bak"))
        except (OSError, ValueError):
            return


class MCPRepository:
    def __init__(self) -> None:
        self._mcps: List[Dict[str, Any]] = []
        self._path = MCPS_DIR / "mcps.json"

    def load(self) -> List[Dict[str, Any]]:
        data = _load_json(self._path, []) or []
        self._mcps = data
        return self._mcps

    def save(self) -> None:
        _save_json(self._path, self._mcps)

    def add(self, mcp: Dict[str, Any]) -> None:
        self._mcps.append(mcp)
        self.save()

    def get(self, mcp_id: str) -> Optional[Dict[str, Any]]:
        for m in self._mcps:
            if m.get("id") == mcp_id:
                return m
        return None

    def update(self, mcp_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for m in self._mcps:
            if m.get("id") == mcp_id:
                m.update(fields)
                self.save()
                return m
        return None

    def delete(self, mcp_id: str) -> bool:
        for i, m in enumerate(self._mcps):
            if m.get("id") == mcp_id:
                self._mcps.pop(i)
                self.save()
                return True
        return False

    def all(self) -> List[Dict[str, Any]]:
        return list(self._mcps)


# ══════════════════════════════════════════════════════════════════
# Singleton repositories
# ══════════════════════════════════════════════════════════════════

bots_repo = BotRepository()
skills_repo = SkillRepository()
mcps_repo = MCPRepository()
