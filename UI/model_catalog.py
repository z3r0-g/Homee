"""Curated Ollama model catalog, sized to the host's available RAM.

The Settings → LLM tab shows these as cards, mirroring
https://ollama.com/search?c=local — except the ``s`` (max-size) filter is
computed from this host instead of hardcoded: a model only appears when its
download size fits in available RAM. The full Ollama listing stays one click
away via the computed search URL in the catalog payload.

Sizes are approximate download sizes in GB. Capability tags use Ollama's
own vocabulary (thinking / tool / vision) plus code and embedding, so the
tab can filter the same way ollama.com does.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# name, size_gb, capabilities, blurb
MODELS: List[Dict[str, Any]] = [
    {"name": "qwen2.5:7b", "size_gb": 4.7, "capabilities": ["tool"],
     "blurb": "General chat + tool use. Homee's default model."},
    {"name": "qwen3:8b", "size_gb": 5.2, "capabilities": ["thinking", "tool"],
     "blurb": "Reasoning model with tool use; shows its thinking."},
    {"name": "llama3.1:8b", "size_gb": 4.7, "capabilities": ["tool"],
     "blurb": "Meta's workhorse 8B with tool support."},
    {"name": "llama3.2:3b", "size_gb": 2.0, "capabilities": ["tool"],
     "blurb": "Small and fast; a good second model on tight RAM."},
    {"name": "mistral:7b", "size_gb": 4.1, "capabilities": ["tool"],
     "blurb": "Fast general-purpose 7B with function calling."},
    {"name": "gemma3:4b", "size_gb": 3.3, "capabilities": ["vision"],
     "blurb": "Small multimodal model — reads images as well as text."},
    {"name": "gemma3:12b", "size_gb": 8.1, "capabilities": ["vision"],
     "blurb": "Larger multimodal Gemma for image + text tasks."},
    {"name": "gemma3:27b", "size_gb": 17.0, "capabilities": ["vision"],
     "blurb": "Flagship multimodal Gemma; needs a roomy host."},
    {"name": "deepseek-r1:8b", "size_gb": 5.2, "capabilities": ["thinking"],
     "blurb": "Reasoning-first model; slower, shows its work."},
    {"name": "phi4:14b", "size_gb": 9.1, "capabilities": ["thinking"],
     "blurb": "Microsoft's 14B reasoning model."},
    {"name": "llava:7b", "size_gb": 4.7, "capabilities": ["vision"],
     "blurb": "Classic vision model for image questions."},
    {"name": "qwen2.5vl:7b", "size_gb": 6.0, "capabilities": ["vision"],
     "blurb": "Qwen's vision-language model."},
    {"name": "qwen2.5-coder:7b", "size_gb": 4.7, "capabilities": ["code", "tool"],
     "blurb": "Code-focused Qwen with tool use."},
    {"name": "codellama:7b", "size_gb": 3.8, "capabilities": ["code"],
     "blurb": "Meta's code specialist."},
    {"name": "starcoder2:7b", "size_gb": 4.0, "capabilities": ["code"],
     "blurb": "Open code model for completion and review."},
    {"name": "llama3.1:70b", "size_gb": 40.0, "capabilities": ["tool"],
     "blurb": "70B flagship; only offered on hosts with RAM to spare."},
    {"name": "nomic-embed-text", "size_gb": 0.3, "capabilities": ["embedding"],
     "blurb": "Text embeddings for search and retrieval."},
    {"name": "mxbai-embed-large", "size_gb": 0.7, "capabilities": ["embedding"],
     "blurb": "Larger embedding model, still tiny on disk."},
]

CAPABILITIES = ["thinking", "tool", "vision", "code", "embedding"]


def host_ram_gb() -> Optional[float]:
    """Available RAM in GB (psutil), or None when it cannot be measured."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 3)
    except Exception:  # noqa: BLE001 - psutil optional
        return None


def size_cap_gb() -> Optional[int]:
    """The ``s`` value for ollama.com/search: available RAM, floored.

    A model must fit in available RAM with room for the OS and the app, so
    the cap is the floor of available GB — the same number the search URL
    carries. Returns None when RAM cannot be measured (no filtering).
    """
    ram = host_ram_gb()
    if ram is None:
        return None
    return max(int(ram), 1)


def catalog() -> Dict[str, Any]:
    """Catalog payload for the Settings model browser."""
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
        "ram_available_gb": round(host_ram_gb(), 1) if host_ram_gb() is not None else None,
        "size_cap_gb": cap,
        "ollama_search_url": search_url,
        "capabilities": CAPABILITIES,
        "models": fitting,
        "hidden_count": hidden,
    }
