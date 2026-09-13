"""Budget Share / Equal Share / Scale Index / Scale Level (spec §5).

Budget Share 그룹은 제품명 x 소재명(Creative_ID)이며 Objective와 무관하게 소재 단위로
집계한다. Valid Creative = 분석기간 내 Spend > 0.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.config_loader import get_evaluation_rules
from src.loader import AdRow


@dataclass
class CreativeScale:
    product: str
    creative_id: str
    creative_spend: float
    product_total_spend: float
    valid_creative_count: int
    is_valid_creative: bool
    spend_share: float | None  # fraction 0..1, None if product_total_spend == 0
    equal_share: float | None  # fraction 0..1, None if no valid creatives
    scale_index: float | None
    scale_level: str | None
    status: list[str]


def scale_level_for_index(scale_index: float) -> str:
    bands = get_evaluation_rules()["scale"]["bands"]
    for band in bands:
        min_incl = band.get("min_inclusive")
        min_excl = band.get("min_exclusive")
        max_incl = band.get("max_inclusive")
        max_excl = band.get("max_exclusive")

        if min_incl is not None and scale_index < min_incl:
            continue
        if min_excl is not None and scale_index <= min_excl:
            continue
        if max_incl is not None and scale_index > max_incl:
            continue
        if max_excl is not None and scale_index >= max_excl:
            continue
        return band["label"]
    raise ValueError(f"scale_index {scale_index}에 해당하는 band을 찾지 못했습니다 (config 확인 필요)")


def meets_scale_threshold(scale_index: float) -> bool:
    threshold = get_evaluation_rules()["scale"]["final_classification_threshold"]
    return scale_index >= threshold


def compute_scale(rows: list[AdRow]) -> dict[str, CreativeScale]:
    """Returns {creative_id: CreativeScale}. rows with Spend issues are excluded from sums."""
    spend_by_creative_per_product: dict[str, dict[str, float]] = {}

    for row in rows:
        if row.Spend is None:
            continue
        product_map = spend_by_creative_per_product.setdefault(row.Product, {})
        product_map[row.Creative_ID] = product_map.get(row.Creative_ID, 0.0) + row.Spend

    results: dict[str, CreativeScale] = {}

    for product, creative_spends in spend_by_creative_per_product.items():
        product_total_spend = sum(creative_spends.values())
        valid_creative_ids = [cid for cid, spend in creative_spends.items() if spend > 0]
        valid_count = len(valid_creative_ids)
        equal_share = (1.0 / valid_count) if valid_count > 0 else None

        for creative_id, creative_spend in creative_spends.items():
            is_valid = creative_spend > 0
            status: list[str] = []

            spend_share = None
            scale_index = None
            scale_level = None

            if product_total_spend == 0:
                status.append("CHECK:PRODUCT_TOTAL_SPEND_ZERO")
            else:
                spend_share = creative_spend / product_total_spend

            if not is_valid:
                status.append("CHECK:INVALID_CREATIVE_ZERO_SPEND")
            elif equal_share is None or equal_share == 0:
                status.append("CHECK:NO_VALID_CREATIVES")
            elif spend_share is not None:
                scale_index = spend_share / equal_share
                scale_level = scale_level_for_index(scale_index)

            results[creative_id] = CreativeScale(
                product=product,
                creative_id=creative_id,
                creative_spend=creative_spend,
                product_total_spend=product_total_spend,
                valid_creative_count=valid_count,
                is_valid_creative=is_valid,
                spend_share=spend_share,
                equal_share=equal_share,
                scale_index=scale_index,
                scale_level=scale_level,
                status=status,
            )

    return results
