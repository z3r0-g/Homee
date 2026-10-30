"""MCP Service routes — CRUD, marketplace, and agent-callable execution."""

from __future__ import annotations

import time
from flask import Blueprint, jsonify, request

from .config import MARKETPLACE, MCPS_DIR
from .endpoints.system import system_bp
from .endpoints.knowledge import knowledge_bp

mcp_bp = Blueprint("mcp", __name__)

# In-memory MCP registry (persisted to mcps.json on disk)
_mcps: dict = {}


def _load_mcps() -> None:
    import json
    from pathlib import Path
    path = MCPS_DIR / "mcps.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            _mcps.clear()
            _mcps.update({m["id"]: m for m in json.load(f)})
    except (FileNotFoundError, json.JSONDecodeError):
        _mcps.clear()


def _save_mcps() -> None:
    import json
    from pathlib import Path
    path = MCPS_DIR / "mcps.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(_mcps.values()), f, indent=2)


_load_mcps()


# ══════════════════════════════════════════════════════════════════
# MCP CRUD
# ══════════════════════════════════════════════════════════════════

@mcp_bp.route("/api/mcps", methods=["GET", "POST"])
def api_mcps():
    if request.method == "GET":
        return jsonify({"mcps": list(_mcps.values())})
    data = request.get_json(silent=True) or {}
    mcp_id = data.get("id") or str(int(time.time() * 1000))
    _mcps[mcp_id] = {
        "id": mcp_id,
        "name": data.get("name", "New MCP"),
        "description": data.get("description", ""),
        "endpoint": data.get("endpoint", ""),
        "method": data.get("method", "GET"),
        "auth_type": data.get("auth_type", "none"),
        "headers": data.get("headers", {}),
        "created_at": time.time(),
    }
    _save_mcps()
    return jsonify({"success": True, "mcp": _mcps[mcp_id]})


@mcp_bp.route("/api/mcp/<mcp_id>", methods=["GET", "PUT", "DELETE"])
def api_mcp_detail(mcp_id):
    mcp = _mcps.get(mcp_id)
    if request.method == "GET":
        if mcp:
            return jsonify({"mcp": mcp})
        return jsonify({"error": "MCP not found"}), 404
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        if mcp_id in _mcps:
            _mcps[mcp_id].update(data)
            _mcps[mcp_id]["updated_at"] = time.time()
            _save_mcps()
            return jsonify({"success": True, "mcp": _mcps[mcp_id]})
        return jsonify({"error": "MCP not found"}), 404
    if request.method == "DELETE":
        if mcp_id in _mcps:
            del _mcps[mcp_id]
            _save_mcps()
            return jsonify({"success": True})
        return jsonify({"error": "MCP not found"}), 404


# ══════════════════════════════════════════════════════════════════
# Marketplace
# ══════════════════════════════════════════════════════════════════

@mcp_bp.route("/api/mcp/marketplace", methods=["GET"])
def api_mcp_marketplace():
    return jsonify({"mcps": list(MARKETPLACE.values()), "source": "open_marketplace"})


# ══════════════════════════════════════════════════════════════════
# Execute — agent-callable MCP endpoint
# ══════════════════════════════════════════════════════════════════

@mcp_bp.route("/api/mcp/execute/<mcp_id>", methods=["POST"])
def api_mcp_execute(mcp_id):
    data = request.get_json(silent=True) or {}
    # Built-in system MCP shortcuts (checked before registry)
    if mcp_id == "system_disk":
        from .endpoints.system import get_disk_space
        return jsonify({"result": get_disk_space()})
    if mcp_id == "system_shell":
        from .endpoints.system import run_shell
        cmd = data.get("command", "")
        return jsonify({"result": run_shell(cmd)})
    mcp = _mcps.get(mcp_id) or MARKETPLACE.get(mcp_id)
    if not mcp:
        return jsonify({"error": f"MCP {mcp_id} not found"}), 404
    # Generic HTTP-based MCP: forward to the configured endpoint
    import requests as _req
    try:
        resp = _req.request(
            method=mcp.get("method", "GET"),
            url=mcp.get("endpoint", ""),
            headers=mcp.get("headers", {}),
            json=data if mcp.get("method", "GET") != "GET" else None,
            timeout=30,
        )
        return jsonify({"result": resp.text, "status_code": resp.status_code})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 502