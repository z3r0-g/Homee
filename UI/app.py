"""UI Service — Flask app factory and entry point.

Usage:
    from UI.app import create_ui_app
    app = create_ui_app()

    # or run directly:
    #   python -m UI.app
"""

from __future__ import annotations

import os

from flask import Flask

from .config import HOST, PORT, DEBUG, load_settings
from .models import bots_repo, personalities_repo, mcps_repo
from .scheduler import BotScheduler
from .routes import (
    bots_bp,
    personalities_bp,
    mcps_bp,
    knowledge_bp,
    settings_bp,
    agents_bp,
)

from Agents.registry import agent_registry


# Module-level scheduler so it stays alive for the app's lifetime
_scheduler: BotScheduler | None = None


def create_ui_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # Load persisted state
    bots_repo.load()
    personalities_repo.load()
    mcps_repo.load()

    # Register blueprints
    app.register_blueprint(bots_bp)
    app.register_blueprint(personalities_bp)
    app.register_blueprint(mcps_bp)
    app.register_blueprint(knowledge_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(agents_bp)

    # Health check
    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "ui", "port": PORT}

    # Root — serve the SPA
    @app.get("/")
    def app_ui():
        from flask import render_template
        return render_template("app.html")

    # Configure the independent Agents package from UI settings.
    # A git URL (if set) is cloned into Agents/remote/<name>; when unset the
    # local /Agents directory on the Server is used.
    settings = load_settings()
    agents_cfg = settings.get("agents", {}) if isinstance(settings, dict) else {}
    agent_registry.configure_git_url(agents_cfg.get("git_url") or None)
    agent_registry.discover(force=True)

    # Start the background scheduler (disabled under tests via UI_START_SCHEDULER=false)
    if os.getenv("UI_START_SCHEDULER", "true").lower() != "false":
        global _scheduler
        _scheduler = BotScheduler(on_run=_run_scheduled_bot)
        _scheduler.start()

    # Sanitize Permissions-Policy: drop unrecognized Privacy Sandbox / ad features
    # that Chrome reports as "Unrecognized feature" warnings (run-ad-auction,
    # join-ad-interest-group, private-aggregation, attribution-reporting).
    @app.after_request
    def _permissions_policy(resp):
        resp.headers["Permissions-Policy"] = (
            "accelerometer=(), "
            "ambient-light-sensor=(), "
            "autoplay=(), "
            "battery=(), "
            "camera=(), "
            "display-capture=(), "
            "document-domain=(), "
            "encrypted-media=(), "
            "execution-while-not-rendered=(), "
            "execution-while-out-of-viewport=(), "
            "geolocation=(), "
            "gyroscope=(), "
            "keyboard-map=(), "
            "magnetometer=(), "
            "microphone=(), "
            "midi=(), "
            "navigation-override=(), "
            "payment=(), "
            "picture-in-picture=(), "
            "publickey-credentials-get=(), "
            "screen-wake-lock=(), "
            "serial=(), "
            "sync-xhr=(), "
            "usb=(), "
            "web-share=(), "
            "xr-spatial-tracking=()"
        )
        return resp

    return app


def _run_scheduled_bot(bot_id: str) -> None:
    from .routes.bots import _execute_bot_task  # noqa: WPS433

    try:
        _execute_bot_task(bot_id)
    except Exception as e:  # noqa: BLE001
        print(f"[Scheduler] Error running bot {bot_id}: {e}")


# Production entry point — module-level `app` for WSGI servers (gunicorn, Azure App Service).
# Azure WSGI_HANDLER: UI.app:app
app = create_ui_app()
create_ui_app._cached_app = app  # type: ignore[attr-defined]

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)