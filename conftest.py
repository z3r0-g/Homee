"""Root pytest configuration — runs before any test collection."""

import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

# Disable background schedulers during tests.
os.environ.setdefault("UI_START_SCHEDULER", "false")

# Isolated temp state for all tests (unit + e2e).
_E2E_TMP = Path(tempfile.mkdtemp(prefix="homee-test-"))
_UI_INST = _E2E_TMP / "ui_instances"
_MCP_INST = _E2E_TMP / "mcp_instances"
_UI_INST.mkdir()
_MCP_INST.mkdir()

os.environ.setdefault("UI_INSTANCES_DIR", str(_UI_INST))
os.environ.setdefault("MCP_INSTANCES_DIR", str(_MCP_INST))
os.environ.setdefault("MCP_KNOWLEDGE_DIR", str(_UI_INST / "knowledge"))

_MCP_PORT = int(os.getenv("MCP_PORT", "5124"))
_UI_PORT = int(os.getenv("UI_PORT", "5123"))
# Only override ports if not explicitly provided; defaults keep unit tests on
# standard ports? E2E needs distinct ports, so force e2e ports here.
os.environ["MCP_SERVICE_URL"] = f"http://127.0.0.1:{_MCP_PORT}"

import pytest


def _start_servers():
    for _name in list(sys.modules):
        if _name in ("UI", "MCP", "Agents") or _name.startswith(("UI.", "MCP.", "Agents.")):
            del sys.modules[_name]
    import MCP.app as mcp_app_mod
    import UI.app as ui_app_mod
    from werkzeug.serving import make_server

    mcp_server = make_server("127.0.0.1", _MCP_PORT, mcp_app_mod.create_mcp_app())
    ui_server = make_server("127.0.0.1", _UI_PORT, ui_app_mod.create_ui_app())

    def _run(server):
        server.serve_forever()

    threading.Thread(target=_run, args=(mcp_server,), daemon=True).start()
    threading.Thread(target=_run, args=(ui_server,), daemon=True).start()

    def _wait(port):
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError(f"server on {port} did not start")

    _wait(_MCP_PORT)
    _wait(_UI_PORT)


@pytest.fixture(scope="session")
def e2e_servers():
    """Start both services for end-to-end tests (session-scoped)."""
    _start_servers()
    return f"http://127.0.0.1:{_UI_PORT}"


@pytest.fixture(scope="session")
def base_url(e2e_servers):
    return e2e_servers


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser, base_url):
    context = browser.new_context()
    page = context.new_page()
    page.goto(base_url, wait_until="networkidle")
    yield page
    context.close()
