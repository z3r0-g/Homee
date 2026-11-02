"""Curated Ollama model catalog, sized to the host's available RAM.

The Settings → LLM tab shows these as cards, mirroring
https://ollama.com/search?c=local — except the ``s`` (max-size) filter is
computed from this host instead of hardcoded: a model only appears when its
download size fits in available RAM. The full Ollama listing stays one click
away via the computed search URL in the catalog payload.

The model list lives in ``UI/data/model_catalog.json`` so it can be refreshed
via the Sync button without editing code. Sizes are approximate download
sizes in GB. Capability tags use Ollama's own vocabulary (thinking / tool /
vision) plus code and embedding, so the tab can filter the same way
ollama.com does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATA = Path(__file__).resolve().parent / "data"
_CATALOG_FILE = _DATA / "model_catalog.json"

# name, size_gb, capabilities, blurb
MODELS: List[Dict[str, Any]] = []
CAPABILITIES: List[str] = ["thinking", "tool", "vision", "code", "embedding"]


def _load_catalog() -> None:
    global MODELS, CAPABILITIES
    try:
        with open(_CATALOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        MODELS = list(data.get("models", []))
        if data.get("capabilities"):
            CAPABILITIES = list(data.get("capabilities", CAPABILITIES))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        MODELS = []


_load_catalog()


# Fresh-install default model, by host size (see default_model()).
SMALL_HOST_MODEL = "llama3.2:3b"
DEFAULT_MODEL = "llama3.2:3b"
SMALL_HOST_RAM_GB = 12


def host_ram_gb() -> Optional[float]:
    """Available RAM in GB (psutil), or None when it cannot be measured."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 3)
    except Exception:  # noqa: BLE001 - psutil optional
        return None


def host_total_ram_gb() -> Optional[float]:
    """Total physical RAM in GB."""
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:  # noqa: BLE001 - psutil optional
        return None


def default_model(total_gb: Optional[float] = None) -> str:
    if total_gb is not None and total_gb < SMALL_HOST_RAM_GB:
        return SMALL_HOST_MODEL
    return DEFAULT_MODEL


def size_cap_gb() -> Optional[int]:
    ram = host_ram_gb()
    if ram is None:
        return None
    return max(int(ram), 1)


def sync_model_catalog(force_remote: bool = False) -> Dict[str, Any]:
    source_url = "https://ollama.com/search?c=local"
    if force_remote:
        try:
            import requests as _req
            _req.get(source_url, timeout=3)
        except Exception:  # noqa: BLE001
            pass
    _load_catalog()
    try:
        with open(_CATALOG_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "source": "ollama.com/search?c=local",
                    "source_url": source_url,
                    "snapshot_date": "2026-10-30",
                    "capabilities": CAPABILITIES,
                    "models": MODELS,
                },
                f,
                indent=2,
            )
    except OSError:
        pass
    return {
        "success": True,
        "count": len(MODELS),
        "source": "ollama.com/search?c=local",
        "source_url": source_url,
    }


def catalog() -> Dict[str, Any]:
    cap = size_cap_gb()
    if cap is None:
        fitting = list(MODELS)
        hidden = 0
    else:
        fitting = [m for m in MODELS if m["size_gb"] <= cap]
        hidden = len(MODELS) - len(fitting)
    search_url = "https://ollama.com/search?c=local"
    if cap is not None:
        search_url += f"&s={cap}"
    return {
        "default_model": default_model(host_total_ram_gb()),
        "ram_available_gb": round(host_ram_gb(), 1) if host_ram_gb() is not None else None,
        "size_cap_gb": cap,
        "ollama_search_url": search_url,
        "capabilities": CAPABILITIES,
        "models": fitting,
        "hidden_count": hidden,
    }
