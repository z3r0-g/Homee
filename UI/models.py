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
    PERSONALITIES_DIR,
    SETTINGS_FILE,
    load_settings,
    save_settings,
)


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
class Personality:
    """Agent personality with specialized skills and abilities."""

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
    def from_dict(cls, d: Dict[str, Any]) -> "Personality":
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
    """Agent bot instance — embodies a Personality to accomplish tasks."""

    id: str
    name: str
    personality_id: str = ""
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


class PersonalityRepository:
    def __init__(self) -> None:
        self._personalities: List[Personality] = []
        self._path = PERSONALITIES_DIR / "personalities.json"

    def load(self) -> List[Personality]:
        data = _load_json(self._path, []) or []
        self._personalities = [Personality.from_dict(p) for p in data]
        return self._personalities

    def save(self) -> None:
        _save_json(self._path, [p.to_dict() for p in self._personalities])

    def add(self, personality: Personality) -> None:
        self._personalities.append(personality)
        self.save()

    def get(self, personality_id: str) -> Optional[Personality]:
        for p in self._personalities:
            if p.id == personality_id:
                return p
        return None

    def all(self) -> List[Personality]:
        return list(self._personalities)


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
personalities_repo = PersonalityRepository()
mcps_repo = MCPRepository()
