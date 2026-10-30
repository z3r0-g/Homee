"""MCP routes for the UI service — proxies to the MCP service with auto-resolution and auth support."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..config import MCP_SERVICE_URL
from ..registry_sync import auto_resolve_endpoint, sync_mcp_registry

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
    """Remote marketplace synced from Official MCP Registry and Smithery.
    Every server includes resolved URLs and authentication requirement tags.
    """
    refresh = request.args.get("refresh", "").lower() in ("1", "true", "yes")
    snap = sync_mcp_registry(force_remote=refresh)
    merged = {}
    for entry in snap.get("entries", []):
        m_id = entry["id"]
        endpoint = auto_resolve_endpoint(entry)
        requires_auth = bool(entry.get("requires_auth") or entry.get("auth_type") not in (None, "", "none"))
        auth_type = entry.get("auth_type") or ("api_key" if requires_auth else "none")
        merged[m_id] = {
            "id": m_id,
            "name": entry.get("name", m_id),
            "description": entry.get("description", ""),
            "endpoint": endpoint,
            "method": entry.get("method", "GET"),
            "source": entry.get("source", "Official MCP Registry"),
            "source_url": entry.get("source_url", snap.get("source_url", "")),
            "requires_auth": requires_auth,
            "auth_type": auth_type,
            "auth_note": entry.get("auth_note", "Requires API key or token" if requires_auth else "No credentials required"),
            "rank": entry.get("rank"),
            "author": entry.get("author", ""),
            "category": entry.get("category", "General"),
            "stars": entry.get("stars", ""),
            "tags": entry.get("tags", ["auth-required" if requires_auth else "no-auth"]),
        }

    # Enrich with MCP service built-ins if running
    data, status = _proxy_data("GET", "/api/mcp/marketplace")
    if status == 200 and isinstance(data, dict):
        for entry in data.get("mcps", []):
            entry = dict(entry)
            m_id = entry["id"]
            entry.setdefault("source", "Built-in marketplace")
            entry.setdefault("source_url", "")
            entry["endpoint"] = auto_resolve_endpoint(entry)
            entry.setdefault("method", "GET")
            req_auth = bool(entry.get("requires_auth") or entry.get("auth_type") not in (None, "", "none"))
            entry["requires_auth"] = req_auth
            entry["auth_type"] = entry.get("auth_type", "api_key" if req_auth else "none")
            entry.setdefault("auth_note", "Requires credentials" if req_auth else "No credentials required")
            if m_id in merged:
                if entry.get("endpoint"):
                    merged[m_id]["endpoint"] = entry["endpoint"]
                if entry.get("method"):
                    merged[m_id]["method"] = entry["method"]
                if entry.get("auth_note"):
                    merged[m_id]["auth_note"] = entry["auth_note"]
            else:
                merged[m_id] = entry

    return jsonify({"mcps": list(merged.values())})


@mcps_bp.route("/api/mcp/sync", methods=["GET", "POST"])
def mcp_sync():
    """Sync MCP registry with Official MCP Registry and Smithery."""
    synced = sync_mcp_registry(force_remote=True)
    return jsonify({
        "success": True,
        "count": synced.get("count", len(synced.get("entries", []))),
        "source": synced.get("source", "Official MCP Registry & Smithery"),
    })


@mcps_bp.route("/api/mcp/import/<mcp_id>", methods=["POST"])
def mcp_import(mcp_id):
    """One-click install of an MCP server.
    Auto-resolves endpoints automatically and attaches credentials when provided.
    """
    req_data = request.get_json(silent=True) or {}
    snap = sync_mcp_registry(force_remote=False)
    candidates = {e["id"]: e for e in snap.get("entries", [])}
    
    data, status = _proxy_data("GET", "/api/mcp/marketplace")
    if status == 200 and isinstance(data, dict):
        for entry in data.get("mcps", []):
            candidates.setdefault(entry["id"], entry)
            
    entry = candidates.get(mcp_id)
    if not entry:
        # Check if known built-in or construct entry dynamically
        entry = {
            "id": mcp_id,
            "name": req_data.get("name", mcp_id),
            "description": req_data.get("description", ""),
            "endpoint": req_data.get("endpoint", ""),
            "method": req_data.get("method", "GET"),
        }

    # Auto-resolve endpoint if missing
    endpoint = req_data.get("endpoint") or entry.get("endpoint") or auto_resolve_endpoint(entry)

    # Resolve headers and authentication
    headers = dict(entry.get("headers", {}))
    headers.update(req_data.get("headers", {}))
    auth_type = req_data.get("auth_type") or entry.get("auth_type", "none")
    auth_token = req_data.get("auth_token") or req_data.get("token") or req_data.get("api_key")
    
    if auth_token:
        if auth_type == "bearer" or auth_type == "oauth":
            headers["Authorization"] = f"Bearer {auth_token}"
        elif auth_type == "api_key":
            headers["x-api-key"] = auth_token
        elif auth_type == "basic":
            headers["Authorization"] = f"Basic {auth_token}"
        else:
            headers["Authorization"] = f"Bearer {auth_token}"
            auth_type = "bearer"

    payload = {
        "id": entry["id"],
        "name": req_data.get("name") or entry.get("name", mcp_id),
        "description": req_data.get("description") or entry.get("description", ""),
        "endpoint": endpoint,
        "method": req_data.get("method") or entry.get("method", "GET"),
        "auth_type": auth_type,
        "headers": headers,
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
    """Liveness + server count for the header MCP pill."""
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
