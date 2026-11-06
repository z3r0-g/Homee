"""System MCP endpoints — disk space, shell access, and current date."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

system_bp = Blueprint("system", __name__)


@system_bp.route("/api/mcp/system/disk", methods=["GET"])
def mcp_system_disk():
    total, used, free = shutil.disk_usage("/")
    return jsonify({
        "total_gb": total // (2 ** 30),
        "used_gb": used // (2 ** 30),
        "free_gb": free // (2 ** 30),
    })


@system_bp.route("/api/mcp/system/shell", methods=["POST"])
def mcp_system_shell():
    data = request.get_json(silent=True) or {}
    command = data.get("command", "")
    if not command:
        return jsonify({"error": "No command provided"}), 400
    try:
        result = subprocess.run(
            command, shell=True, text=True, capture_output=True, timeout=10
        )
        return jsonify({
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        })
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@system_bp.route("/api/mcp/system/date", methods=["GET"])
def mcp_system_date():
    now = datetime.now(timezone.utc)
    return jsonify({
        "utc": now.isoformat(),
        "date": now.date().isoformat(),
        "time": now.strftime("%H:%M:%S"),
        "day": now.strftime("%A"),
    })


def get_disk_space() -> str:
    total, used, free = shutil.disk_usage("/")
    return f"{free // (2 ** 30)} GB free out of {total // (2 ** 30)} GB"


def get_current_date() -> str:
    """Return the current date and time as a human-readable string (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def run_shell(command: str) -> str:
    try:
        result = subprocess.run(
            command, shell=True, text=True, capture_output=True, timeout=10
        )
        return result.stdout or result.stderr
    except Exception as e:  # noqa: BLE001
        return str(e)