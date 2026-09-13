"""OpenAI vision adapter. Structured output only, no performance data ever passed.

NOTE: installed openai SDK in this project is a very recent major version (checked via
`pip show openai`). The chat.completions + response_format={"type":"json_schema",...}
call shape below matches the widely-documented OpenAI API as of this writing; if the
installed SDK renamed/moved this method, adjust this adapter accordingly before the first
real (paid) run — verify with a $0 dry-run against the SDK's own docs/changelog first.
"""
from __future__ import annotations

import base64
import logging
import os
import time

from src.config_loader import get_model_config
from src.pricing import OPENAI_IMAGE_TOKEN_FORMULA, openai_image_tokens
from src.providers.base import (
    CreativeAnalysisInput,
    CreativeAnalysisResult,
    CreativeObservation,
    ProviderBase,
)

logger = logging.getLogger(__name__)


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


class OpenAIProvider(ProviderBase):
    name = "openai"

    def __init__(self):
        cfg = get_model_config()
        self.model = cfg["providers"]["openai"]["vision_model"]
        self.prompt_version = cfg["prompt_version"]
        self.schema_version = cfg["schema_version"]
        self.pricing = cfg["pricing_usd"]["openai"]

    def estimate_image_tokens(self, width: int, height: int) -> int:
        return openai_image_tokens(width, height)

    def image_token_formula_description(self) -> str:
        return OPENAI_IMAGE_TOKEN_FORMULA

    def analyze(self, item: CreativeAnalysisInput, prompt_text: str) -> CreativeAnalysisResult:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return self._error_result(item, "API_ERROR", "OPENAI_API_KEY 미설정")

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            content = [{"type": "text", "text": prompt_text}]
            for frame_path in item.frame_paths:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{_encode_image(frame_path)}"},
                    }
                )
            if item.transcript_text:
                content.append({"type": "text", "text": f"[Transcript]\n{item.transcript_text}"})

            start = time.time()
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "creative_analysis",
                        "schema": _analysis_json_schema(),
                        "strict": True,
                    },
                },
            )
            latency = time.time() - start

            raw_json = response.choices[0].message.content
            return self._parse_result(item, raw_json, response, latency)
        except Exception as e:  # noqa: BLE001 - never crash the harness on provider errors
            logger.error("OpenAI 분석 실패 (%s): %s", item.blind_id, e)
            return self._error_result(item, "API_ERROR", str(e))

    def _parse_result(self, item, raw_json: str, response, latency: float) -> CreativeAnalysisResult:
        import json

        try:
            data = json.loads(raw_json)
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
                input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
                output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
                latency_sec=latency,
                raw_status="OK",
            )
        except Exception as e:  # noqa: BLE001
            logger.error("OpenAI 응답 파싱 실패 (%s): %s", item.blind_id, e)
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


def _empty_observation(item: CreativeAnalysisInput) -> CreativeObservation:
    return CreativeObservation(
        asset_type=item.asset_type,
        first_3sec_core_element="not_observed",
        hook_type="not_observed",
        main_visual_focus="not_observed",
        offer_present=False,
        demo_present=False,
        actual_color_or_makeup_result="not_observed",
        before_after_present=False,
        person_type="none",
        proof_type="not_observed",
        subtitle_prominence="not_observed",
        core_message="not_observed",
        message_density="low",
        immediate_understandability="low",
        cta_type="not_observed",
        brand_or_product_name_exposure="not_observed",
        cut_pace="medium",
    )


def _analysis_json_schema() -> dict:
    """JSON schema mirroring CreativeAnalysisResult's observation+judgment fields.

    Kept as a plain dict (rather than pydantic's auto schema) because OpenAI structured
    outputs require every property listed in `required` and disallow `$defs`-style refs
    in strict mode for some SDK versions — flatten explicitly for safety.
    """
    return {
        "type": "object",
        "properties": {
            "observation": {
                "type": "object",
                "properties": {
                    "asset_type": {"type": "string", "enum": ["image", "video", "carousel"]},
                    "first_3sec_core_element": {"type": "string"},
                    "hook_type": {"type": "string"},
                    "product_first_exposure_time_sec": {"type": ["number", "null"]},
                    "main_visual_focus": {"type": "string"},
                    "offer_present": {"type": "boolean"},
                    "offer_type": {"type": ["string", "null"]},
                    "offer_first_exposure_time_sec": {"type": ["number", "null"]},
                    "demo_present": {"type": "boolean"},
                    "demo_start_time_sec": {"type": ["number", "null"]},
                    "actual_color_or_makeup_result": {"type": "string"},
                    "before_after_present": {"type": "boolean"},
                    "person_type": {"type": "string", "enum": ["influencer", "model", "ugc", "expert", "none"]},
                    "proof_type": {"type": "string"},
                    "subtitle_prominence": {"type": "string"},
                    "core_message": {"type": "string"},
                    "message_density": {"type": "string", "enum": ["low", "medium", "high", "not_observed"]},
                    "immediate_understandability": {"type": "string", "enum": ["low", "medium", "high", "not_observed"]},
                    "cta_type": {"type": "string"},
                    "cta_first_time_sec": {"type": ["number", "null"]},
                    "brand_or_product_name_exposure": {"type": "string"},
                    "cut_pace": {"type": "string", "enum": ["slow", "medium", "fast", "not_observed"]},
                    "average_cut_length_sec": {"type": ["number", "null"]},
                },
                "required": [
                    "asset_type", "first_3sec_core_element", "hook_type",
                    "product_first_exposure_time_sec", "main_visual_focus", "offer_present",
                    "offer_type", "offer_first_exposure_time_sec", "demo_present",
                    "demo_start_time_sec", "actual_color_or_makeup_result", "before_after_present",
                    "person_type", "proof_type", "subtitle_prominence", "core_message",
                    "message_density", "immediate_understandability", "cta_type",
                    "cta_first_time_sec", "brand_or_product_name_exposure", "cut_pace",
                    "average_cut_length_sec",
                ],
                "additionalProperties": False,
            },
            "ai_predicted_response": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
            "ai_confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
            "reason_1": {"type": "string"},
            "reason_2": {"type": "string"},
            "reason_3": {"type": "string"},
            "uncertainty_or_limitations": {"type": "string"},
        },
        "required": [
            "observation", "ai_predicted_response", "ai_confidence",
            "reason_1", "reason_2", "reason_3", "uncertainty_or_limitations",
        ],
        "additionalProperties": False,
    }
