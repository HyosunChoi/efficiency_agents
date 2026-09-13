"""Loads config/*.yaml once and exposes them as plain dicts.

No business rule or threshold lives in Python source — everything tunable comes from
config/*.yaml so the spec's numbers stay auditable and editable without touching code.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"필수 config 파일이 없습니다: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=None)
def get_evaluation_rules() -> dict:
    return _load_yaml("evaluation_rules.yaml")


@lru_cache(maxsize=None)
def get_normalization_rules() -> dict:
    return _load_yaml("normalization_rules.yaml")


@lru_cache(maxsize=None)
def get_column_aliases() -> dict:
    return _load_yaml("column_aliases.yaml")


@lru_cache(maxsize=None)
def get_model_config() -> dict:
    return _load_yaml("model_config.yaml")
