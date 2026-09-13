"""Anthropic (Claude) vision adapter. Forced tool-use for structured output.

Same taxonomy/schema as openai_client.py — see providers/base.py for the shared contract.
NOTE: verify the exact `client.messages.create(...)` call shape against the installed
`anthropic` SDK version before the first real (paid) run; this mirrors the documented
tool-use pattern as of this writing.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import os
import time

from src.config_loader import get_model_config
from src.pricing import CLAUDE_IMAGE_TOKEN_FORMULA, claude_image_tokens
from src.providers.base import (
    CreativeAnalysisInput,
    CreativeAnalysisResult,
    CreativeObservation,
    ProviderBase,
)
from src.providers.openai_client import _analysis_json_schema, _empty_observation

logger = logging.getLogger(__name__)

TOOL_NAME = "submit_creative_analysis"
MAX_ATTEMPTS = 2  # Claude의 custom tool-use는 OpenAI strict mode와 달리 required 필드 준수를
# 100% 보장하지 않는다 — 실제로 max_tokens을 8192로 올려도 'reason_2' 등 필수 키가 간헐적으로
# 누락되는 사례가 있었다(2026-09-12). 모델의 비결정적 누락으로 보고, 값을 임의로 채우는 대신
# 한 번만 재시도한다 (그래도 실패하면 조용히 넘기지 않고 PARSE_ERROR + 어떤 키가 없었는지 남김).
REQUIRED_TOP_LEVEL_KEYS = [
    "observation",
    "ai_predicted_response",
    "ai_confidence",
    "reason_1",
    "reason_2",
    "reason_3",
    "uncertainty_or_limitations",
]


def _encode_image(path: str) -> tuple[str, str]:
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/jpeg"
    with open(path, "rb") as f:
        return mime, base64.b64encode(f.read()).decode("utf-8")


class AnthropicProvider(ProviderBase):
    name = "claude"

    def __init__(self):
        cfg = get_model_config()
        self.model = cfg["providers"]["claude"]["vision_model"]
        self.prompt_version = cfg["prompt_version"]
        self.schema_version = cfg["schema_version"]
        self.pricing = cfg["pricing_usd"]["claude"]

    def estimate_image_tokens(self, width: int, height: int) -> int:
        return claude_image_tokens(width, height)

    def image_token_formula_description(self) -> str:
        return CLAUDE_IMAGE_TOKEN_FORMULA

    def analyze(self, item: CreativeAnalysisInput, prompt_text: str) -> CreativeAnalysisResult:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return self._error_result(item, "API_ERROR", "ANTHROPIC_API_KEY 미설정")

        last_error: CreativeAnalysisResult | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                import anthropic

                client = anthropic.Anthropic(api_key=api_key)
                content = [{"type": "text", "text": prompt_text}]
                for frame_path in item.frame_paths:
                    mime, b64 = _encode_image(frame_path)
                    content.append(
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": mime, "data": b64},
                        }
                    )
                if item.transcript_text:
                    content.append({"type": "text", "text": f"[Transcript]\n{item.transcript_text}"})

                tool = {
                    "name": TOOL_NAME,
                    "description": "Submit the structured creative analysis result.",
                    "input_schema": _analysis_json_schema(),
                }

                start = time.time()
                response = client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": TOOL_NAME},
                    messages=[{"role": "user", "content": content}],
                )
                latency = time.time() - start

                if getattr(response, "stop_reason", None) == "max_tokens":
                    last_error = self._error_result(
                        item,
                        "PARSE_ERROR",
                        "Claude 응답이 max_tokens에서 잘림 (stop_reason=max_tokens) — "
                        "관찰값이 너무 길어 스키마를 다 채우지 못함.",
                    )
                    logger.warning("%s (claude) 시도 %d/%d: 응답 잘림, 재시도", item.blind_id, attempt, MAX_ATTEMPTS)
                    continue

                result = self._parse_result(item, response, latency)
                if result.raw_status == "OK":
                    return result
                last_error = result
                logger.warning(
                    "%s (claude) 시도 %d/%d: %s — 재시도", item.blind_id, attempt, MAX_ATTEMPTS, result.error_detail
                )
            except Exception as e:  # noqa: BLE001 - never crash the harness on provider errors
                logger.error("Claude 분석 실패 (%s, 시도 %d/%d): %s", item.blind_id, attempt, MAX_ATTEMPTS, e)
                last_error = self._error_result(item, "API_ERROR", str(e))

        return last_error

    def _parse_result(self, item, response, latency: float) -> CreativeAnalysisResult:
        try:
            tool_use_block = next(b for b in response.content if b.type == "tool_use")
            data = tool_use_block.input

            missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in data]
            if missing:
                return self._error_result(
                    item,
                    "PARSE_ERROR",
                    f"Claude 응답에 필수 키 누락: {missing} (Claude tool-use는 OpenAI strict mode와 "
                    "달리 required 필드를 강제하지 않아 간헐적으로 발생할 수 있음)",
                )

            observation = CreativeObservation.model_validate(data["observation"])
            usage = getattr(response, "usage", None)
            return CreativeAnalysisResult(
                schema_version=self.schema_version,
                prompt_version=self.prompt_version,
                blind_id=item.blind_id,
                provider=self.name,
                model=self.model,
                observation=observation,
                ai_predicted_response=data["ai_predicted_response"],
                ai_confidence=data["ai_confidence"],
                reason_1=data["reason_1"],
                reason_2=data["reason_2"],
                reason_3=data["reason_3"],
                uncertainty_or_limitations=data["uncertainty_or_limitations"],
                input_tokens=getattr(usage, "input_tokens", None) if usage else None,
                output_tokens=getattr(usage, "output_tokens", None) if usage else None,
                latency_sec=latency,
                raw_status="OK",
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Claude 응답 파싱 실패 (%s): %s", item.blind_id, e)
            return self._error_result(item, "PARSE_ERROR", str(e))

    def _error_result(self, item: CreativeAnalysisInput, status: str, detail: str) -> CreativeAnalysisResult:
        return CreativeAnalysisResult(
            schema_version=self.schema_version,
            prompt_version=self.prompt_version,
            blind_id=item.blind_id,
            provider=self.name,
            model=self.model,
            observation=_empty_observation(item),
            ai_predicted_response="MEDIUM",
            ai_confidence="LOW",
            reason_1="N/A", reason_2="N/A", reason_3="N/A",
            uncertainty_or_limitations=f"분석 실패: {status}",
            raw_status=status,
            error_detail=detail,
        )
