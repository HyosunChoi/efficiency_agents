"""Explicit, non-semantic normalization for media/creative names (spec §4).

Only "명백한 표기 정규화" is allowed here: extension stripping, whitespace/unicode
normalization, and explicit media alias substitution from config. No fuzzy/semantic
matching lives in this module — that is reserved for matcher.py's status reporting.
"""
from __future__ import annotations

import re
import unicodedata

from src.config_loader import get_normalization_rules


def _strip_known_extension(name: str, extensions: list[str]) -> str:
    lower = name.lower()
    for ext in extensions:
        ext = ext.lower()
        if lower.endswith(ext):
            return name[: -len(ext)]
    return name


def normalize_name(raw: str) -> str:
    """Normalize a single media name or creative name for matching/Creative_ID use."""
    rules = get_normalization_rules()
    char_rules = rules.get("character_normalization", {})

    value = raw if raw is not None else ""
    value = str(value)

    value = _strip_known_extension(value, rules.get("strip_extensions", []))

    if char_rules.get("unicode_nfkc", True):
        value = unicodedata.normalize("NFKC", value)

    if char_rules.get("strip_leading_trailing_whitespace", True):
        value = value.strip()

    if char_rules.get("collapse_internal_whitespace", True):
        value = re.sub(r"\s+", " ", value)

    media_aliases = rules.get("media_aliases") or {}
    for canonical, variants in media_aliases.items():
        if value == canonical or value in (variants or []):
            value = canonical
            break

    return value


def normalize_media(raw_media: str) -> str:
    return normalize_name(raw_media)


def normalize_creative_name(raw_creative_name: str) -> str:
    return normalize_name(raw_creative_name)


def build_creative_id(normalized_media: str, normalized_creative_name: str) -> str:
    rules = get_normalization_rules()
    template = rules.get("creative_id_template", "{normalized_media}__{normalized_creative_name}")
    return template.format(
        normalized_media=normalized_media,
        normalized_creative_name=normalized_creative_name,
    )
