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
    """Remote marketplace: the MCP service's built-ins plus the curated
    community catalog (mcpmarket.com and other popular listings). The
    curated entries win on id collisions so cards carry endpoints and
    auth notes."""
    from ..mcp_catalog import remote_catalog
    data, status = _proxy_data("GET", "/api/mcp/marketplace")
    merged = {entry["id"]: entry for entry in remote_catalog()}
    if status == 200 and isinstance(data, dict):
        for entry in data.get("mcps", []):
            entry = dict(entry)
            entry.setdefault("source", "Built-in marketplace")
            entry.setdefault("source_url", "")
            entry.setdefault("endpoint", "")
            entry.setdefault("method", "GET")
            entry.setdefault("auth_note", "")
            merged.setdefault(entry["id"], entry)
    return jsonify({"mcps": list(merged.values())})


@mcps_bp.route("/api/mcp/import/<mcp_id>", methods=["POST"])
def mcp_import(mcp_id):
    """Copy a remote marketplace entry into the local registry."""
    from ..mcp_catalog import remote_catalog
    data, status = _proxy_data("GET", "/api/mcp/marketplace")
    candidates = {e["id"]: e for e in remote_catalog()}
    if status == 200 and isinstance(data, dict):
        for entry in data.get("mcps", []):
            candidates.setdefault(entry["id"], entry)
    entry = candidates.get(mcp_id)
    if not entry:
        return jsonify({"error": f"Remote MCP '{mcp_id}' not found"}), 404
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
