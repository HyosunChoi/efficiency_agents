"""Small helpers to build AdRow fixtures without needing real Excel files."""
from __future__ import annotations

from src.loader import AdRow


def make_row(
    row_number: int,
    product: str,
    objective: str,
    media: str,
    creative_name: str,
    impressions: float,
    clicks: float,
    spend: float,
    conversions: float,
    revenue: float,
) -> AdRow:
    from src.normalizer import build_creative_id, normalize_creative_name, normalize_media

    media_norm = normalize_media(media)
    creative_norm = normalize_creative_name(creative_name)
    return AdRow(
        row_number=row_number,
        Product=product,
        Objective_Raw=objective,
        Media_Raw=media,
        Creative_Name_Raw=creative_name,
        Media_Normalized=media_norm,
        Creative_Name_Normalized=creative_norm,
        Creative_ID=build_creative_id(media_norm, creative_norm),
        Impressions=impressions,
        Clicks=clicks,
        Spend=spend,
        Conversions=conversions,
        Revenue=revenue,
    )
