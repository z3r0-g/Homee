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


@mcps_bp.route("/api/mcp/execute/<mcp_id>", methods=["POST"])
def execute_mcp(mcp_id):
    return _proxy("POST", f"/api/mcp/execute/{mcp_id}", request.get_json(silent=True) or {})