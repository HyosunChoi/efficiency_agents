"""Verify our formulas reproduce the worked examples from each provider's own docs exactly."""
import pytest

from src.pricing import approx_text_tokens, claude_image_tokens, openai_image_tokens


def test_openai_worked_example_1024x1024_high_detail():
    # developers.openai.com/api/docs/guides/images-vision: 1024x1024, high detail -> 1024 patches -> 1229 tokens
    assert openai_image_tokens(1024, 1024) == 1229


@pytest.mark.parametrize(
    "width,height,expected_tokens",
    [
        (200, 200, 64),
        (1000, 1000, 1296),
        (1092, 1092, 1521),
        (1920, 1080, 2691),   # not resized on high-res tier
        (2000, 1500, 3888),   # not resized on high-res tier
        (3840, 2160, 4784),   # resized to 2576x1449, capped at 4784
    ],
)
def test_claude_worked_examples_high_resolution_tier(width, height, expected_tokens):
    assert claude_image_tokens(width, height) == expected_tokens


def test_approx_text_tokens_is_roughly_char_over_four():
    assert approx_text_tokens("a" * 400) == 100
    assert approx_text_tokens("") == 1  # never zero
