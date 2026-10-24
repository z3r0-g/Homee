"""Pytest fixtures for the MCP service tests."""

from __future__ import annotations

from pathlib import Path

import pytest

import MCP.routes as routes_mod
from MCP.app import create_mcp_app
from MCP.config import MCPS_DIR


def _reset_state() -> None:
    """Clear the in-memory MCP registry and persisted file for test isolation."""
    routes_mod._mcps.clear()
    try:
        Path(MCPS_DIR / "mcps.json").unlink(missing_ok=True)
    except OSError:
        pass


@pytest.fixture
def app():
    app = create_mcp_app()
    app.config["TESTING"] = True
    _reset_state()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_mcps():
    _reset_state()