"""Regression tests for Claude response reliability issues found in the real 2026-09-12
benchmark run:

1. A truncated response (max_tokens hit mid-JSON) must be flagged clearly, not surfaced as
   a confusing bare KeyError.
2. Claude's custom tool-use doesn't enforce 'required' fields the way OpenAI's structured
   output strict mode does — it can (non-deterministically) omit a required key like
   reason_2 even with plenty of max_tokens headroom. This must be (a) reported with a clear
   "missing keys" message rather than a bare KeyError, and (b) retried once automatically,
   since it's a transient model hiccup rather than a systematic schema/limit problem.
"""
from types import SimpleNamespace

from PIL import Image

from src.providers.anthropic_client import MAX_ATTEMPTS, AnthropicProvider
from src.providers.base import CreativeAnalysisInput


def _observation_dict(**overrides):
    base = {
        "asset_type": "image",
        "first_3sec_core_element": "x",
        "hook_type": "x",
        "product_first_exposure_time_sec": None,
        "main_visual_focus": "x",
        "offer_present": False,
        "offer_type": None,
        "offer_first_exposure_time_sec": None,
        "demo_present": False,
        "demo_start_time_sec": None,
        "actual_color_or_makeup_result": "x",
        "before_after_present": False,
        "person_type": "none",
        "proof_type": "x",
        "subtitle_prominence": "x",
        "core_message": "x",
        "message_density": "low",
        "immediate_understandability": "high",
        "cta_type": "x",
        "cta_first_time_sec": None,
        "brand_or_product_name_exposure": "x",
        "cut_pace": "medium",
        "average_cut_length_sec": None,
    }
    base.update(overrides)
    return base


def _tool_use_response(input_dict):
    tool_use_block = SimpleNamespace(type="tool_use", input=input_dict)
    return SimpleNamespace(stop_reason="tool_use", content=[tool_use_block], usage=None)


def _complete_input_dict():
    return {
        "observation": _observation_dict(),
        "ai_predicted_response": "HIGH",
        "ai_confidence": "HIGH",
        "reason_1": "r1",
        "reason_2": "r2",
        "reason_3": "r3",
        "uncertainty_or_limitations": "none",
    }


class _FakeMessages:
    """Returns one response per call, in order; repeats the last one if exhausted."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    def create(self, **kwargs):
        idx = min(self.call_count, len(self._responses) - 1)
        self.call_count += 1
        return self._responses[idx]


class _FakeAnthropicClient:
    def __init__(self, fake_messages):
        self.messages = fake_messages


def _install_fake_client(monkeypatch, responses):
    fake_messages = _FakeMessages(responses)
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key: _FakeAnthropicClient(fake_messages))
    return fake_messages


def _make_item(tmp_path, blind_id):
    image_path = tmp_path / f"{blind_id}.jpg"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(image_path)
    return CreativeAnalysisInput(blind_id=blind_id, asset_type="image", frame_paths=[str(image_path)])


def test_max_tokens_truncation_is_reported_clearly_not_as_a_bare_keyerror(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    truncated_response = SimpleNamespace(stop_reason="max_tokens", content=[], usage=None)
    fake_messages = _install_fake_client(monkeypatch, [truncated_response])

    provider = AnthropicProvider()
    result = provider.analyze(_make_item(tmp_path, "asset_001"), "prompt text")

    assert result.raw_status == "PARSE_ERROR"
    assert "max_tokens" in result.error_detail
    assert "reason_2" not in result.error_detail  # no more bare KeyError leaking through
    assert fake_messages.call_count == MAX_ATTEMPTS  # both attempts truncated -> gives up cleanly


def test_normal_response_is_not_flagged_as_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    fake_messages = _install_fake_client(monkeypatch, [_tool_use_response(_complete_input_dict())])

    provider = AnthropicProvider()
    result = provider.analyze(_make_item(tmp_path, "asset_002"), "prompt text")

    assert result.raw_status == "OK"
    assert result.reason_2 == "r2"
    assert fake_messages.call_count == 1  # no retry needed


def test_missing_required_key_is_reported_clearly_and_retried(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    incomplete = _complete_input_dict()
    del incomplete["reason_2"]  # exactly what happened for real: Claude omitted this key

    # First attempt: Claude omits reason_2. Second attempt (retry): complete response.
    responses = [_tool_use_response(incomplete), _tool_use_response(_complete_input_dict())]
    fake_messages = _install_fake_client(monkeypatch, responses)

    provider = AnthropicProvider()
    result = provider.analyze(_make_item(tmp_path, "asset_003"), "prompt text")

    assert result.raw_status == "OK"  # retry recovered
    assert result.reason_2 == "r2"
    assert fake_messages.call_count == 2


def test_missing_required_key_on_every_attempt_gives_up_with_clear_message(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    incomplete = _complete_input_dict()
    del incomplete["reason_2"]
    fake_messages = _install_fake_client(monkeypatch, [_tool_use_response(incomplete)])

    provider = AnthropicProvider()
    result = provider.analyze(_make_item(tmp_path, "asset_004"), "prompt text")

    assert result.raw_status == "PARSE_ERROR"
    assert "reason_2" in result.error_detail  # names exactly which key was missing
    assert fake_messages.call_count == MAX_ATTEMPTS
