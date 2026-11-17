"""Load and lightly validate a company config (YAML or JSON)."""
from __future__ import annotations

import json
import os
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


def load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        if path.lower().endswith(".json"):
            cfg = json.load(f)
        else:
            cfg = yaml.safe_load(f)

    base_dir = os.path.dirname(os.path.abspath(path))
    cfg["_base_dir"] = base_dir

    for required in ("company", "reporting_currency", "taxonomy_file", "sources"):
        if required not in cfg:
            raise ConfigError(f"config {path} is missing required key {required!r}")
    if not cfg["sources"]:
        raise ConfigError(f"config {path} must declare at least one source")
    for src in cfg["sources"]:
        for required in ("id", "path", "id_column", "record_id_prefix", "amount", "date"):
            if required not in src:
                raise ConfigError(f"source {src.get('id')} missing required key {required!r}")

    cfg.setdefault("matching", {"enabled": False})
    cfg.setdefault("fx", {})
    cfg.setdefault("classification", {})
    return cfg


def resolve(cfg: dict[str, Any], relative_path: str) -> str:
    """Resolve a path from a config relative to the current working directory
    first (so `data/...` from the repo root works), falling back to the
    config file's own directory."""
    if os.path.isabs(relative_path) or os.path.exists(relative_path):
        return relative_path
    candidate = os.path.join(cfg["_base_dir"], relative_path)
    return candidate
