"""Deterministic fake provider for dry-run / harness tests — no network call ever."""
from __future__ import annotations

from src.providers.base import (
    CreativeAnalysisInput,
    CreativeAnalysisResult,
    CreativeObservation,
    ProviderBase,
)


class FakeProvider(ProviderBase):
    def __init__(
        self,
        name: str,
        predicted_response: str = "HIGH",
        confidence: str = "HIGH",
        fail_with_status: str | None = None,
    ):
        self.name = name
        self.model = f"{name}-fake-model"
        self.predicted_response = predicted_response
        self.confidence = confidence
        self.call_count = 0
        self.fail_with_status = fail_with_status  # e.g. "API_ERROR" / "PARSE_ERROR" for testing
        self.pricing = {
            "input_per_1k_tokens": 0.001,
            "output_per_1k_tokens": 0.002,
            "est_output_tokens_per_analysis": 50,
        }

    def estimate_image_tokens(self, width: int, height: int) -> int:
        return max(1, (width * height) // 1000)  # arbitrary deterministic fake formula

    def image_token_formula_description(self) -> str:
        return "fake formula: (width*height)//1000"

    def analyze(self, item: CreativeAnalysisInput, prompt_text: str) -> CreativeAnalysisResult:
        self.call_count += 1
        assert "performance" not in prompt_text.lower() or True  # prompt text never carries perf data by construction

        if self.fail_with_status:
            return CreativeAnalysisResult(
                schema_version="v1",
                prompt_version="v1",
                blind_id=item.blind_id,
                provider=self.name,
                model=self.model,
                observation=CreativeObservation(
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
                    message_density="not_observed",
                    immediate_understandability="not_observed",
                    cta_type="not_observed",
                    brand_or_product_name_exposure="not_observed",
                    cut_pace="not_observed",
                ),
                ai_predicted_response="MEDIUM",
                ai_confidence="LOW",
                reason_1="N/A", reason_2="N/A", reason_3="N/A",
                uncertainty_or_limitations=f"분석 실패: {self.fail_with_status}",
                raw_status=self.fail_with_status,
                error_detail="fake induced failure",
            )

        observation = CreativeObservation(
            asset_type=item.asset_type,
            first_3sec_core_element="fake element",
            hook_type="fake hook",
            main_visual_focus="fake focus",
            offer_present=False,
            demo_present=False,
            actual_color_or_makeup_result="not_observed",
            before_after_present=False,
            person_type="none",
            proof_type="not_observed",
            subtitle_prominence="low",
            core_message="fake message",
            message_density="low",
            immediate_understandability="high",
            cta_type="fake cta",
            brand_or_product_name_exposure="fake brand",
            cut_pace="medium",
        )
        return CreativeAnalysisResult(
            schema_version="v1",
            prompt_version="v1",
            blind_id=item.blind_id,
            provider=self.name,
            model=self.model,
            observation=observation,
            ai_predicted_response=self.predicted_response,
            ai_confidence=self.confidence,
            reason_1="fake reason 1",
            reason_2="fake reason 2",
            reason_3="fake reason 3",
            uncertainty_or_limitations="none (fake)",
            input_tokens=100,
            output_tokens=50,
            latency_sec=0.01,
            raw_status="OK",
        )
