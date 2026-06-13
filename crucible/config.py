"""Centralized configuration loader.

Reads YAML configs once, exposes them as typed dictionaries.
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

import yaml


_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@lru_cache(maxsize=8)
def _load(name: str) -> dict:
    path = _CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path, "r") as f:
        return yaml.safe_load(f)


def settings() -> dict:
    return _load("settings")


def models() -> dict:
    return _load("models")


def tools() -> dict:
    return _load("tools")


def get_model_config(persona: str) -> dict:
    """Get config for a specific model persona (e.g., 'prospector')."""
    roster = models().get("roster", {})
    if persona not in roster:
        raise KeyError(f"Unknown persona: {persona}. Available: {list(roster.keys())}")
    return roster[persona]


def get_paths() -> dict:
    """Get all configured paths, resolving relative to project root."""
    root = Path(__file__).resolve().parent.parent
    raw = settings().get("paths", {})
    return {k: str(root / v) for k, v in raw.items()}
