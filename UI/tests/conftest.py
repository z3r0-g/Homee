"""Pytest fixtures for the UI service tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from UI.app import create_ui_app
from UI.config import SETTINGS_FILE
from UI.models import bots_repo, personalities_repo, mcps_repo


def _reset_state() -> None:
    """Clear in-memory repo state and persisted JSON files for test isolation."""
    bots_repo._bots.clear()
    personalities_repo._personalities.clear()
    mcps_repo._mcps.clear()
    for path in (
        bots_repo._path,
        personalities_repo._path,
        mcps_repo._path,
        Path(SETTINGS_FILE),
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    """UI Flask app with settings persisted to a temp dir and scheduler disabled."""
    tmp_settings = tmp_path / "settings.json"
    monkeypatch.setenv("UI_START_SCHEDULER", "false")
    monkeypatch.setattr("UI.config.SETTINGS_FILE", tmp_settings)

    app = create_ui_app()
    app.config["TESTING"] = True
    _reset_state()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_repos():
    _reset_state()