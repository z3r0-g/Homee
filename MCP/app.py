"""MCP Service — Flask app factory and entry point.

Usage:
    from MCP.app import create_mcp_app
    app = create_mcp_app()

    # or run directly:
    #   python -m MCP.app
"""

from __future__ import annotations

from flask import Flask

from .config import HOST, PORT, DEBUG
from .routes import mcp_bp, system_bp, knowledge_bp


def create_mcp_app() -> Flask:
    """Create and configure the MCP Flask application (App Factory pattern)."""
    app = Flask(__name__)

    app.register_blueprint(mcp_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(knowledge_bp)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "mcp", "port": PORT}

    return app


# Production entry point — module-level `app` for WSGI servers (gunicorn, Azure App Service).
# Azure WSGI_HANDLER: MCP.app:app
app = create_mcp_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)