"""Common structured-output schema + Provider interface (spec §6/§9).

Both OpenAI and Claude adapters must return exactly this schema so comparison is fair
("Provider 간 입력조건 동일 유지" — spec §15). No performance data ever appears here by
construction: there simply is no field for it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.pricing import approx_text_tokens

Tri = Literal["HIGH", "MEDIUM", "LOW"]


class CreativeObservation(BaseModel):
    """V1 관찰 taxonomy (spec §6). 관찰 불가 항목은 'not_observed'/None으로 명시."""

    asset_type: Literal["image", "video", "carousel"]
    first_3sec_core_element: str
    hook_type: str
    product_first_exposure_time_sec: Optional[float] = None
    main_visual_focus: str
    offer_present: bool
    offer_type: Optional[str] = None
    offer_first_exposure_time_sec: Optional[float] = None
    demo_present: bool
    demo_start_time_sec: Optional[float] = None
    actual_color_or_makeup_result: str
    before_after_present: bool
    person_type: Literal["influencer", "model", "ugc", "expert", "none"]
    proof_type: str
    subtitle_prominence: str
    core_message: str
    message_density: Literal["low", "medium", "high", "not_observed"]
    immediate_understandability: Literal["low", "medium", "high", "not_observed"]
    cta_type: str
    cta_first_time_sec: Optional[float] = None
    brand_or_product_name_exposure: str
    cut_pace: Literal["slow", "medium", "fast", "not_observed"]
    average_cut_length_sec: Optional[float] = None


class CreativeAnalysisResult(BaseModel):
    schema_version: str
    prompt_version: str
    blind_id: str
    provider: str
    model: str

    observation: CreativeObservation
    ai_predicted_response: Tri
    ai_confidence: Tri
    reason_1: str
    reason_2: str
    reason_3: str
    uncertainty_or_limitations: str

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_sec: Optional[float] = None
    raw_status: str = Field(default="OK")  # "OK" | "API_ERROR" | "PARSE_ERROR"
    error_detail: Optional[str] = None

    # Transcript audit trail (2026-09-12 audio-extraction pipeline) — lets a later audit
    # answer "was a transcript actually available/sent for this call" without having to
    # cross-reference the separate transcript cache and the model's own free-text mentions.
    transcript_available: bool = False
    transcript_status: str = "N/A"  # transcript.py STATUS_* constants
    transcript_char_count: int = 0
    transcript_source: Optional[str] = None  # e.g. "whisper-1"
    transcript_hash: Optional[str] = None  # sha256(transcript text); None when no transcript
    transcript_error_code: Optional[str] = None
    audio_extraction_status: str = "N/A"  # OK | NO_AUDIO_STREAM | FFMPEG_ERROR | N/A(non-video)


class CreativeAnalysisInput(BaseModel):
    """Blind 패키지. 원본 매체/소재명/성과 데이터는 이 구조에 필드 자체가 없다."""

    blind_id: str
    asset_type: Literal["image", "video", "carousel"]
    frame_paths: list[str]
    transcript_text: Optional[str] = None
    transcript_status: str = "N/A"  # transcript.py STATUS_* constants
    transcript_char_count: int = 0
    transcript_source: Optional[str] = None
    transcript_hash: Optional[str] = None
    transcript_error_code: Optional[str] = None
    audio_extraction_status: str = "N/A"


@dataclass
class CostBreakdown:
    """Per-asset cost estimate shown on the dry-run/approval screen (user-requested detail).

    Image tokens are a precise application of the provider's documented formula to the
    asset's actual frame dimensions — not a guess. Output tokens are a genuine estimate
    (an LLM's response length isn't known ahead of time) and are marked as such via
    `output_tokens_is_estimate`.
    """

    provider: str
    model: str
    input_price_per_1k: float
    output_price_per_1k: float
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    image_token_formula: str
    output_tokens_is_estimate: bool = True


class ProviderBase(ABC):
    name: str
    model: str

    @abstractmethod
    def analyze(self, item: CreativeAnalysisInput, prompt_text: str) -> CreativeAnalysisResult:
        """Calls the provider's vision API and returns a validated CreativeAnalysisResult.

        Must never raise on provider/schema failure — return raw_status='API_ERROR' or
        'PARSE_ERROR' with error_detail instead (spec §12: 실패를 조용히 넘기지 않는다).
        """

    @abstractmethod
    def estimate_image_tokens(self, width: int, height: int) -> int:
        """Provider-specific vision token formula (see src/pricing.py), applied to one frame."""

    @abstractmethod
    def image_token_formula_description(self) -> str:
        """Human-readable description of estimate_image_tokens, shown on the approval screen."""

    def estimate_cost(
        self,
        image_dims: list[tuple[int, int]],
        prompt_text: str,
        transcript_estimated_tokens: int = 0,
    ) -> CostBreakdown:
        """Real per-token pricing (config/model_config.yaml pricing_usd) applied to:
        - image tokens: exact formula x actual frame dimensions
        - prompt tokens: ~4 chars/token approximation of the fixed prompt text
        - transcript tokens: caller's estimate (video only), also approximate
        - output tokens: config's est_output_tokens_per_analysis (always an estimate)
        """
        image_tokens = sum(self.estimate_image_tokens(w, h) for w, h in image_dims)
        prompt_tokens = approx_text_tokens(prompt_text)
        input_tokens = image_tokens + prompt_tokens + transcript_estimated_tokens
        output_tokens = int(self.pricing["est_output_tokens_per_analysis"])

        cost = (
            input_tokens / 1000 * self.pricing["input_per_1k_tokens"]
            + output_tokens / 1000 * self.pricing["output_per_1k_tokens"]
        )

        return CostBreakdown(
            provider=self.name,
            model=self.model,
            input_price_per_1k=self.pricing["input_per_1k_tokens"],
            output_price_per_1k=self.pricing["output_per_1k_tokens"],
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_cost_usd=round(cost, 6),
            image_token_formula=self.image_token_formula_description(),
        )
