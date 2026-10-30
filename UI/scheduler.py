"""Background scheduler for running Bots on their configured schedule."""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Optional

from .config import load_settings


class BotScheduler:
    """Lightweight stdlib scheduler that polls due Bots and invokes a callback.

    Runs in a background daemon thread. Not a replacement for APScheduler/Cron,
    but sufficient for per-bot interval scheduling without extra dependencies.
    """

    def __init__(self, on_run: Callable[[str], None]) -> None:
        self._on_run = on_run
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._tick_seconds = 30
        self._enabled = False

    # ════════════════════════════════════════════════════════════════
    # Lifecycle
    # ════════════════════════════════════════════════════════════════

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            settings = load_settings()
            self._tick_seconds = int(settings.get("scheduler", {}).get("tick_seconds", 30))
            self._enabled = bool(settings.get("scheduler", {}).get("enabled", True))
            self._thread = threading.Thread(target=self._loop, daemon=True, name="bot-scheduler")
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

    def reconfigure(self) -> None:
        settings = load_settings()
        self._tick_seconds = int(settings.get("scheduler", {}).get("tick_seconds", 30))
        self._enabled = bool(settings.get("scheduler", {}).get("enabled", True))

    # ════════════════════════════════════════════════════════════════
    # Loop
    # ════════════════════════════════════════════════════════════════

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._enabled:
                self._tick()
            self._stop.wait(self._tick_seconds)

    def _tick(self) -> None:
        # Imported lazily to avoid circular imports
        from .models import bots_repo  # noqa: WPS433

        now = time.time()
        for bot in bots_repo.all():
            cfg = bot.config
            if not cfg.enabled or cfg.schedule_type != "interval":
                continue
            if cfg.interval_seconds <= 0:
                continue
            last = 0.0
            if cfg.last_run:
                try:
                    last = _parse_iso(cfg.last_run).timestamp()
                except Exception:  # noqa: BLE001
                    last = 0.0
            if now - last >= cfg.interval_seconds:
                try:
                    self._on_run(bot.id)
                except Exception as e:  # noqa: BLE001
                    print(f"[Scheduler] Error running bot {bot.id}: {e}")


def _parse_iso(value: str) -> "datetime":
    from datetime import datetime

    return datetime.fromisoformat(value)