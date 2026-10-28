"""MCP routes for the UI service — proxies to the MCP service."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..config import MCP_SERVICE_URL

mcps_bp = Blueprint("mcps", __name__)


def _proxy(method: str, path: str, json_body=None):
    import requests as _req

    url = f"{MCP_SERVICE_URL}{path}"
    try:
        if method == "GET":
            resp = _req.get(url, timeout=30)
        elif method == "POST":
            resp = _req.post(url, json=json_body, timeout=30)
        elif method == "PUT":
            resp = _req.put(url, json=json_body, timeout=30)
        elif method == "DELETE":
            resp = _req.delete(url, timeout=30)
        else:
            return jsonify({"error": "Unsupported method"}), 500
        return (resp.json(), resp.status_code) if resp.headers.get("content-type", "").startswith("application/json") else (resp.text, resp.status_code)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"MCP service unreachable: {e}"}), 502


@mcps_bp.route("/api/mcps", methods=["GET", "POST"])
def list_mcps():
    if request.method == "GET":
        return _proxy("GET", "/api/mcps")
    return _proxy("POST", "/api/mcps", request.get_json(silent=True))


@mcps_bp.route("/api/mcps/<mcp_id>", methods=["GET", "PUT", "DELETE"])
def mcp_detail(mcp_id):
    if request.method == "GET":
        return _proxy("GET", f"/api/mcp/{mcp_id}")
    if request.method == "PUT":
        return _proxy("PUT", f"/api/mcp/{mcp_id}", request.get_json(silent=True))
    return _proxy("DELETE", f"/api/mcp/{mcp_id}")


@mcps_bp.route("/api/mcp/marketplace", methods=["GET"])
def mcp_marketplace():
    return _proxy("GET", "/api/mcp/marketplace")


def _proxy_data(method, path, json_body=None):
    """_proxy, unwrapped: (data, status) with error bodies as dicts."""
    result = _proxy(method, path, json_body)
    if isinstance(result, tuple):
        data, status = result
        if hasattr(data, "get_json"):
            try:
                data = data.get_json() or {}
            except Exception:  # noqa: BLE001
                data = {"error": "MCP service returned an unreadable response"}
        return data, status
    return result, 200


@mcps_bp.route("/api/mcp/local", methods=["GET"])
def mcp_local():
    """MCPs registered on this host's MCP service (the Local section)."""
    data, status = _proxy_data("GET", "/api/mcps")
    if status != 200 or not isinstance(data, dict):
        return jsonify(data if isinstance(data, dict) else {"error": str(data)}), status
    mcps = data.get("mcps", [])
    for mcp in mcps:
        mcp.setdefault("enabled", True)
        mcp.setdefault("type", "local")
    return jsonify({"mcps": mcps})


@mcps_bp.route("/api/mcp/remote", methods=["GET"])
def mcp_remote():
    """Remote marketplace: the MCP service's built-ins plus the
    MCP Market leaderboard snapshot (top 30). Leaderboard entries
    carry no endpoint, so cards offer Use-this (prefill the Add
    form) and View instead of Import. The snapshot loads from disk,
    so remote cards still render when the MCP service is down."""
    from ..leaderboard import load_leaderboard
    snap = load_leaderboard("mcp")
    merged = {}
    for entry in snap.get("entries", []):
        merged[entry["id"]] = {
            "id": entry["id"],
            "name": entry.get("name", entry["id"]),
            "description": entry.get("description", ""),
            "endpoint": "",
            "method": "GET",
            "source": "Leaderboard",
            "source_url": snap.get("source_url", ""),
            "auth_note": "",
            "rank": entry.get("rank"),
            "author": entry.get("author", ""),
            "category": entry.get("category", ""),
            "stars": entry.get("stars", ""),
        }
    data, status = _proxy_data("GET", "/api/mcp/marketplace")
    if status == 200 and isinstance(data, dict):
        for entry in data.get("mcps", []):
            entry = dict(entry)
            entry.setdefault("source", "Built-in marketplace")
            entry.setdefault("source_url", "")
            entry.setdefault("endpoint", "")
            entry.setdefault("method", "GET")
            entry.setdefault("auth_note", "")
            mcp_id = entry["id"]
            if mcp_id in merged:
                # Enrich leaderboard entry with resolved endpoint from
                # the marketplace catalogue (leaderboard entries ship with
                # endpoint="" by design, so "Use" never had a URL to offer).
                if entry.get("endpoint") and not merged[mcp_id].get("endpoint"):
                    merged[mcp_id]["endpoint"] = entry["endpoint"]
                    merged[mcp_id]["method"] = entry.get("method") or merged[mcp_id]["method"]
                    merged[mcp_id]["source_url"] = entry.get("source_url") or merged[mcp_id]["source_url"]
                    merged[mcp_id]["auth_note"] = entry.get("auth_note") or merged[mcp_id]["auth_note"]
            else:
                merged[mcp_id] = entry
    return jsonify({"mcps": list(merged.values())})


@mcps_bp.route("/api/mcp/import/<mcp_id>", methods=["POST"])
def mcp_import(mcp_id):
    """Copy a remote marketplace entry into the local registry.
    Leaderboard entries have no endpoint, so importing one is
    refused — the card offers Use-this (prefill the Add form)
    instead."""
    from ..leaderboard import load_leaderboard
    snap = load_leaderboard("mcp")
    candidates = {e["id"]: e for e in snap.get("entries", [])}
    data, status = _proxy_data("GET", "/api/mcp/marketplace")
    if status == 200 and isinstance(data, dict):
        for entry in data.get("mcps", []):
            candidates.setdefault(entry["id"], entry)
    entry = candidates.get(mcp_id)
    if not entry:
        return jsonify({"error": f"Remote MCP '{mcp_id}' not found"}), 404
    if not entry.get("endpoint"):
        return jsonify({"error": f"'{entry.get('name', mcp_id)}' has no endpoint — add it with the Add local MCP form."}), 400
    payload = {
        "id": entry["id"],
        "name": entry.get("name", mcp_id),
        "description": entry.get("description", ""),
        "endpoint": entry.get("endpoint", ""),
        "method": entry.get("method", "GET"),
        "auth_type": "none",
        "headers": {},
    }
    created, create_status = _proxy_data("POST", "/api/mcps", payload)
    if create_status != 200:
        return jsonify(created if isinstance(created, dict) else {"error": str(created)}), create_status
    return jsonify(created)


@mcps_bp.route("/api/mcp/enable/<mcp_id>", methods=["POST"])
def mcp_enable(mcp_id):
    return _proxy("PUT", f"/api/mcp/{mcp_id}", {"enabled": True})


@mcps_bp.route("/api/mcp/disable/<mcp_id>", methods=["POST"])
def mcp_disable(mcp_id):
    return _proxy("PUT", f"/api/mcp/{mcp_id}", {"enabled": False})


@mcps_bp.route("/api/mcp/execute/<mcp_id>", methods=["POST"])
def execute_mcp(mcp_id):
    return _proxy("POST", f"/api/mcp/execute/{mcp_id}", request.get_json(silent=True) or {})

@mcps_bp.route("/api/mcp/status", methods=["GET"])
def mcp_status():
    """Liveness + server count for the header MCP pill.

    Pings the MCP service's /api/health with short timeouts: a dead
    service must not hang the header check the way _proxy's 30s would.
    The count is best-effort — liveness is what the pill reports.
    """
    import requests as _req

    try:
        health = _req.get(f"{MCP_SERVICE_URL}/api/health", timeout=2)
    except Exception as e:  # noqa: BLE001
        return jsonify({"running": False, "error": f"MCP service unreachable: {e}"})
    if health.status_code != 200:
        return jsonify({"running": False, "error": f"MCP service unhealthy: HTTP {health.status_code}"})
    count = None
    try:
        resp = _req.get(f"{MCP_SERVICE_URL}/api/mcps", timeout=2)
        data = resp.json()
        if isinstance(data, list):
            count = len(data)
        elif isinstance(data, dict) and isinstance(data.get("mcps"), list):
            count = len(data["mcps"])
    except Exception:  # noqa: BLE001 - count is best-effort
        pass
    return jsonify({"running": True, "count": count})
