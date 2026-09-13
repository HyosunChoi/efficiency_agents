"""Provider-specific vision token formulas, verified against each provider's own docs
(fetched 2026-09-12):

- OpenAI gpt-5.6-terra: https://developers.openai.com/api/docs/guides/images-vision
  patch_count = ceil(w/32) * ceil(h/32) (after detail-level resize), tokens = ceil(patch_count * 1.2)
- Claude (Claude 4.7+ / high-resolution tier, includes claude-sonnet-5):
  https://platform.claude.com/docs/en/build-with-claude/vision#evaluate-image-size
  tokens = ceil(w/28) * ceil(h/28) (after resolution-cap resize)

Both formulas were checked against the worked examples on those pages (1024x1024 -> 1229
tokens for OpenAI high detail; 1920x1080 -> 2691 tokens and 3840x2160 -> 2576x1449 px / 4784
tokens for Claude high-resolution tier) and match exactly. The resize step for images that
exceed the provider's cap is this module's own implementation of the documented rule, not
independently verified against the provider's internal algorithm — treat it as an estimate
for oversized images (most ad-creative frames won't hit this cap).
"""
from __future__ import annotations

import math


def approx_text_tokens(text: str) -> int:
    """~4 characters/token heuristic (no tokenizer library loaded) — an approximation,
    not an exact count for either provider's tokenizer."""
    return max(1, len(text) // 4)


# ---- OpenAI gpt-5.6-terra ----

OPENAI_PATCH_PX = 32
OPENAI_TOKEN_MULTIPLIER = 1.2
OPENAI_HIGH_DETAIL_MAX_PX = 2048
OPENAI_HIGH_DETAIL_MAX_PATCHES = 2500

OPENAI_IMAGE_TOKEN_FORMULA = (
    "gpt-5.6-terra: detail=high 기준 2048x2048 이내로 축소 후 "
    "patch=ceil(w/32)*ceil(h/32) (최대 2500 patch로 추가 축소), "
    "tokens=ceil(patch*1.2). 출처: developers.openai.com/api/docs/guides/images-vision"
)


def openai_image_tokens(width: int, height: int) -> int:
    w, h = float(width), float(height)

    if w > OPENAI_HIGH_DETAIL_MAX_PX or h > OPENAI_HIGH_DETAIL_MAX_PX:
        scale = OPENAI_HIGH_DETAIL_MAX_PX / max(w, h)
        w, h = w * scale, h * scale

    patch_count = math.ceil(w / OPENAI_PATCH_PX) * math.ceil(h / OPENAI_PATCH_PX)

    if patch_count > OPENAI_HIGH_DETAIL_MAX_PATCHES:
        scale = math.sqrt(OPENAI_HIGH_DETAIL_MAX_PATCHES / patch_count)
        w, h = w * scale, h * scale
        patch_count = math.ceil(w / OPENAI_PATCH_PX) * math.ceil(h / OPENAI_PATCH_PX)

    return math.ceil(patch_count * OPENAI_TOKEN_MULTIPLIER)


# ---- Claude (high-resolution tier: Claude 4.7 and later, incl. claude-sonnet-5) ----

CLAUDE_PATCH_PX = 28
CLAUDE_MAX_LONG_EDGE = 2576
CLAUDE_MAX_VISUAL_TOKENS = 4784

CLAUDE_IMAGE_TOKEN_FORMULA = (
    "claude-sonnet-5 (high-resolution tier): 긴 변 2576px 이내로 축소 후 "
    "tokens=ceil(w/28)*ceil(h/28) (최대 4784 token로 추가 축소). "
    "출처: platform.claude.com/docs/en/build-with-claude/vision#evaluate-image-size"
)


def claude_image_tokens(width: int, height: int) -> int:
    w, h = float(width), float(height)

    long_edge = max(w, h)
    if long_edge > CLAUDE_MAX_LONG_EDGE:
        scale = CLAUDE_MAX_LONG_EDGE / long_edge
        w, h = w * scale, h * scale

    tokens = math.ceil(w / CLAUDE_PATCH_PX) * math.ceil(h / CLAUDE_PATCH_PX)

    if tokens > CLAUDE_MAX_VISUAL_TOKENS:
        scale = math.sqrt(CLAUDE_MAX_VISUAL_TOKENS / tokens)
        w, h = w * scale, h * scale
        tokens = math.ceil(w / CLAUDE_PATCH_PX) * math.ceil(h / CLAUDE_PATCH_PX)

    return tokens
