"""Agent registry — discovers AgentBase subclasses from local Agents/ dir
and optional git-sourced repos listed in Agents/sources.json."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .app import AgentBase

SERVER_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = SERVER_DIR / "Agents"
SOURCES_FILE = AGENTS_DIR / "sources.json"
REMOTE_DIR = AGENTS_DIR / "remote"


def load_sources() -> Dict[str, Any]:
    if SOURCES_FILE.exists():
        try:
            with open(SOURCES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"local_dir": "Agents/local", "git_repos": []}


class AgentRegistry:
    """Scans local and remote agent modules, returning AgentBase subclasses."""

    def __init__(self, extra_git_url: Optional[str] = None) -> None:
        self._agents: Dict[str, type[AgentBase]] = {}
        self._sources = load_sources()
        self._extra_git_url = extra_git_url
        self._discovered: bool = False

    def configure_git_url(self, url: Optional[str]) -> None:
        """Set an extra git repo URL (from UI settings) and force re-discovery."""
        if url != self._extra_git_url:
            self._extra_git_url = url
            self._discovered = False

    @property
    def _git_repos(self) -> List[str]:
        repos = list(self._sources.get("git_repos", []))
        if self._extra_git_url and self._extra_git_url not in repos:
            repos.append(self._extra_git_url)
        return repos

    def discover(self, force: bool = False) -> Dict[str, type[AgentBase]]:
        if self._discovered and not force:
            return self._agents
        self._agents = {}
        self._discover_local()
        self._discover_git()
        self._discovered = True
        return self._agents

    def _discover_local(self) -> None:
        local_dir = self._sources.get("local_dir", "Agents/local")
        path = SERVER_DIR / local_dir
        if not path.exists():
            return
        for py_file in sorted(path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            self._load_module_from_file(py_file.stem, py_file)

    def _discover_git(self) -> None:
        for repo_url in self._git_repos:
            repo_name = self._repo_name(repo_url)
            target = REMOTE_DIR / repo_name
            if not target.exists():
                try:
                    REMOTE_DIR.mkdir(parents=True, exist_ok=True)
                    subprocess.run(
                        ["git", "clone", "--depth", "1", repo_url, str(target)],
                        check=False,
                        capture_output=True,
                        timeout=120,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"[Registry] Failed to clone {repo_url}: {e}")
                    continue
            else:
                # Pull latest
                try:
                    subprocess.run(
                        ["git", "-C", str(target), "pull", "--ff-only"],
                        check=False,
                        capture_output=True,
                        timeout=60,
                    )
                except Exception:  # noqa: BLE001
                    pass
            if target.exists():
                for py_file in sorted(target.rglob("*.py")):
                    if py_file.name.startswith("_"):
                        continue
                    mod_name = f"remote_{repo_name}_{py_file.stem}"
                    self._load_module_from_file(mod_name, py_file, package_hint=repo_name)

    @staticmethod
    def _repo_name(repo_url: str) -> str:
        name = repo_url.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
        return name

    def _load_module_from_file(
        self, mod_name: str, file_path: Path, package_hint: Optional[str] = None
    ) -> None:
        try:
            spec = importlib.util.spec_from_file_location(mod_name, str(file_path))
            if spec is None or spec.loader is None:
                return
            module = importlib.util.module_from_spec(spec)
            # Set package context so relative imports (e.g. "from .app import ...")
            # resolve correctly when loading agent modules from disk.
            module.__package__ = package_hint or "Agents"
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)  # type: ignore[attr-defined]

            found = False
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, AgentBase)
                    and obj is not AgentBase
                ):
                    agent = obj()
                    self._agents[agent.name] = obj
                    found = True
            if not found:
                # No AgentBase subclass in this module — not an error, just skip.
                pass
        except Exception as e:  # noqa: BLE001
            print(f"[Registry] Skipping {file_path}: {e}")

    def list_agents(self) -> List[Dict[str, Any]]:
        self.discover()
        return [
            {
                "name": cls.name,
                "description": cls.description,
                "system_prompt": cls.system_prompt,
                "model": cls.model,
                # Remote agents load from modules named remote_<repo>_*
                "source": "remote" if cls.__module__.startswith("remote_") else "local",
            }
            for cls in self._agents.values()
        ]

    def get_agent(self, name: str) -> Optional[type[AgentBase]]:
        self.discover()
        return self._agents.get(name)


# Singleton
agent_registry = AgentRegistry()