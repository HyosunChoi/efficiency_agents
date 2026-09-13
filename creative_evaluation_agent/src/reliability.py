"""Reliability tiers R0~R3 (spec §5), thresholds from config/evaluation_rules.yaml."""
from __future__ import annotations

from src.config_loader import get_evaluation_rules


def _tier_for_value(value: float, bands: dict) -> str:
    for tier in ("R0", "R1", "R2", "R3"):
        band = bands[tier]
        min_v = band.get("min", 0)
        max_v = band.get("max")
        if value >= min_v and (max_v is None or value <= max_v):
            return tier
    raise ValueError(f"값 {value}에 해당하는 reliability tier를 찾지 못했습니다 (config 확인 필요)")


def conversion_reliability(conversion_count: float) -> str:
    bands = get_evaluation_rules()["reliability"]["conversion"]
    return _tier_for_value(conversion_count, bands)


def traffic_reliability(click_count: float) -> str:
    bands = get_evaluation_rules()["reliability"]["traffic"]
    return _tier_for_value(click_count, bands)


def is_low_reliability(tier: str) -> bool:
    """R0/R1은 확정 Winner/Underperformer 판정을 하지 않는다."""
    return tier in ("R0", "R1")
