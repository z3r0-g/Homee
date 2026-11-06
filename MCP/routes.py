"""MCP Service routes — CRUD, marketplace, and agent-callable execution."""

from __future__ import annotations

import time
import requests as _req
from flask import Blueprint, jsonify, request

from .config import MARKETPLACE, MCPS_DIR
from .endpoints.system import system_bp
from .endpoints.knowledge import knowledge_bp

mcp_bp = Blueprint("mcp", __name__)

# In-memory MCP registry (persisted to mcps.json on disk).
#
# The service runs under gunicorn with multiple workers, each with its own
# copy of ``_mcps``. To keep every worker (and the UI, which proxies these
# endpoints) consistent, reads are reloaded from ``mcps.json`` on every
# request and writes go through a file lock + atomic replace. The file on
# disk is the single source of truth.
_mcps: dict = {}

_MCPS_LOCK_FILE = "mcps.lock"


def _mcps_path():
    from pathlib import Path
    return MCPS_DIR / "mcps.json"


def _lock_path():
    from pathlib import Path
    return MCPS_DIR / _MCPS_LOCK_FILE


def _read_mcps_unlocked() -> dict:
    import json
    try:
        with open(_mcps_path(), "r", encoding="utf-8") as f:
            return {m["id"]: m for m in json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_mcps_unlocked(mcps: dict) -> None:
    import json
    import os
    path = _mcps_path()
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(list(mcps.values()), f, indent=2)
    os.replace(tmp, path)  # atomic on POSIX


def _load_mcps() -> None:
    """Refresh the in-memory registry from disk (single source of truth)."""
    _mcps.clear()
    _mcps.update(_read_mcps_unlocked())


def _locked(fn):
    """Run ``fn`` holding the cross-process file lock (POSIX fcntl)."""
    with open(_lock_path(), "a+", encoding="utf-8") as lock:
        try:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - non-POSIX fallback
            fcntl = None
        try:
            return fn()
        finally:
            if fcntl:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _mutate_mcps(mutator):
    """Locked read-modify-write against the on-disk registry.

    Reloads from disk, applies ``mutator(mcps)``, atomically persists, and
    refreshes the in-memory cache — all under one lock so concurrent gunicorn
    workers can't lose updates or resurrect deleted entries. Returns the
    mutator's return value.
    """
    def _do():
        mcps = _read_mcps_unlocked()
        result = mutator(mcps)
        _write_mcps_unlocked(mcps)
        _mcps.clear()
        _mcps.update(mcps)
        return result
    return _locked(_do)


_load_mcps()


# ══════════════════════════════════════════════════════════════════
# MCP CRUD
# ══════════════════════════════════════════════════════════════════

@mcp_bp.route("/api/mcps", methods=["GET", "POST"])
def api_mcps():
    if request.method == "GET":
        _load_mcps()
        return jsonify({"mcps": list(_mcps.values())})
    data = request.get_json(silent=True) or {}
    mcp_id = data.get("id") or str(int(time.time() * 1000))
    protocol = data.get("protocol", "http")
    if protocol not in ("http", "mcp"):
        return jsonify({"error": "protocol must be 'http' or 'mcp'"}), 400

    def _add(mcps):
        mcps[mcp_id] = {
            "id": mcp_id,
            "name": data.get("name", "New MCP"),
            "description": data.get("description", ""),
            "endpoint": data.get("endpoint", ""),
            "method": data.get("method", "GET"),
            "protocol": protocol,
            "auth_type": data.get("auth_type", "none"),
            "headers": data.get("headers", {}),
            "created_at": time.time(),
        }
        return mcps[mcp_id]

    mcp = _mutate_mcps(_add)
    return jsonify({"success": True, "mcp": mcp})


@mcp_bp.route("/api/mcp/<mcp_id>", methods=["GET", "PUT", "DELETE"])
def api_mcp_detail(mcp_id):
    if request.method == "GET":
        _load_mcps()
        mcp = _mcps.get(mcp_id)
        if mcp:
            return jsonify({"mcp": mcp})
        return jsonify({"error": "MCP not found"}), 404
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}

        def _update(mcps):
            if mcp_id not in mcps:
                return None
            mcps[mcp_id].update(data)
            mcps[mcp_id]["updated_at"] = time.time()
            return mcps[mcp_id]

        mcp = _mutate_mcps(_update)
        if mcp is None:
            return jsonify({"error": "MCP not found"}), 404
        return jsonify({"success": True, "mcp": mcp})
    if request.method == "DELETE":
        def _delete(mcps):
            return mcps.pop(mcp_id, None) is not None

        if _mutate_mcps(_delete):
            return jsonify({"success": True})
        return jsonify({"error": "MCP not found"}), 404


# ══════════════════════════════════════════════════════════════════
# Marketplace
# ══════════════════════════════════════════════════════════════════

@mcp_bp.route("/api/mcp/marketplace", methods=["GET"])
def api_mcp_marketplace():
    return jsonify({"mcps": list(MARKETPLACE.values()), "source": "open_marketplace"})


@mcp_bp.route("/api/mcp/reload", methods=["POST"])
def api_mcp_reload():
    """Reload the registry from ``mcps.json`` into this worker's memory.

    Reads already reload from disk on every request, so this is only a
    convenience/health hook (e.g. after an out-of-band edit of the file) —
    it confirms the file parses and reports what was loaded. With gunicorn
    load-balancing, call it once per worker or just rely on read-through.
    """
    _load_mcps()
    return jsonify({
        "success": True,
        "count": len(_mcps),
        "ids": sorted(_mcps.keys()),
    })


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
    if mcp_id == "system_date":
        from .endpoints.system import get_current_date
        return jsonify({"result": get_current_date()})
    _load_mcps()
    mcp = _mcps.get(mcp_id) or MARKETPLACE.get(mcp_id)
    if not mcp:
        return jsonify({"error": f"MCP {mcp_id} not found"}), 404
    if mcp.get("protocol") == "mcp":
        # MCP-protocol server (e.g. https://api.agentic-news.ai/mcp): speak
        # JSON-RPC initialize/tools-list/tools-call instead of plain HTTP.
        from .mcp_client import MCPError, execute_mcp
        try:
            return jsonify(execute_mcp(mcp, data))
        except MCPError as e:
            body = {"error": str(e)}
            if e.status_code is not None:
                body["status_code"] = e.status_code
                return jsonify(body)
            return jsonify(body), 502
    # Generic HTTP-based MCP: forward to the configured endpoint. GET
    # requests carry the args as query params (e.g. open-meteo needs
    # latitude/longitude); other methods send them as a JSON body.
    method = mcp.get("method", "GET").upper()
    try:
        resp = _req.request(
            method=method,
            url=mcp.get("endpoint", ""),
            headers=mcp.get("headers", {}),
            params=data if method == "GET" else None,
            json=data if method != "GET" else None,
            timeout=30,
        )
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 502
    if resp.status_code >= 400:
        return jsonify({
            "error": f"MCP endpoint returned status {resp.status_code}",
            "status_code": resp.status_code,
        })
    return jsonify({"result": resp.text, "status_code": resp.status_code})