"""New-vs-cached tally + detailed cost breakdown + Y/N approval gate (spec §7).

No paid API call may happen before the user types Y at the prompt this module owns.
Cost estimates use each provider's actual verified per-token pricing (config/model_config.yaml
pricing_usd) and each provider's documented vision-token formula (src/pricing.py) applied to
real frame dimensions — only the output-token count and (for video) the transcript length are
genuine estimates, and both are flagged as such wherever they are shown.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.blind_mapper import MappingRow
from src.cache import build_cache_key, hash_asset
from src.config_loader import get_model_config
from src.frame_extractor import extract_frames
from src.prompt_loader import load_benchmark_prompt_text
from src.providers.base import ProviderBase
from src.transcript import peek_cached_transcript, predict_transcript_outcome

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRAME_CACHE_DIR = PROJECT_ROOT / "cache" / "frames"

logger = logging.getLogger(__name__)

# 영상 transcript 토큰 추정 가정치: 분당 150단어 발화 * 단어당 약 1.3 토큰 (근거: 일반적인 영어/한국어
# 대화 속도 추정 어림값 — 실제 발화량/무음구간에 따라 크게 달라질 수 있는 예상치).
ASSUMED_SPOKEN_WORDS_PER_MIN = 150
ASSUMED_TOKENS_PER_WORD = 1.3


def _asset_paths(row: MappingRow) -> list[Path]:
    """Paths used for cache hashing (identity of the asset content)."""
    path = Path(row.blind_path)
    if path.is_dir():
        return sorted(path.iterdir())
    return [path]


def _video_metadata(path: Path) -> tuple[float, int, int]:
    """(duration_sec, width, height) via cheap metadata read — no full decode."""
    try:
        import cv2

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            cap.release()
            return 0.0, 0, 0
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        cap.release()
        duration_sec = (frame_count / fps) if fps > 0 else 0.0
        return duration_sec, width, height
    except Exception:  # noqa: BLE001 - cost estimate must never crash the run
        return 0.0, 0, 0


def _estimate_video_frame_count(duration_sec: float) -> int:
    """Upper-bound estimate of frames extracted from a video (see frame_extractor.py).

    Assumes the scene-change budget is fully used — intentionally conservative (over-
    rather than under-estimating) so the pre-approval cost quote is never lower than what
    will actually be sent to the provider.
    """
    cfg = get_model_config()["frame_extraction"]
    if duration_sec <= 0:
        return 1  # can't probe — fall back to a safe minimum

    fixed_frames = sum(1 for ts in cfg["candidate_timestamps_sec"] if ts <= duration_sec)
    if cfg.get("include_last_frame"):
        fixed_frames += 1
    return fixed_frames + cfg.get("max_scene_change_frames", 0)


def _frame_dimensions_for_asset(row: MappingRow) -> list[tuple[int, int]]:
    """Real (width, height) per frame that will actually be sent to the vision API."""
    if row.asset_type == "video":
        duration_sec, width, height = _video_metadata(Path(row.blind_path))
        if width == 0 or height == 0:
            return [(1280, 720)]  # couldn't probe resolution — reasonable HD fallback
        frame_count = _estimate_video_frame_count(duration_sec)
        return [(width, height)] * frame_count

    from PIL import Image

    dims = []
    for path in _asset_paths(row):
        try:
            with Image.open(path) as img:
                dims.append(img.size)
        except Exception:  # noqa: BLE001 - cost estimate must never crash the run
            dims.append((1280, 720))
    return dims


def _frame_set_hash_for_asset(row: MappingRow) -> str:
    """실제 frame_set_hash — 이미지/캐러셀은 원본 파일 자체, 영상은 실제로 프레임을 추출해
    (로컬/무료 연산) 그 결과물을 해시한다. cache.build_cache_key와 동일 기준."""
    if row.asset_type != "video":
        return hash_asset(_asset_paths(row))
    extracted = extract_frames(Path(row.blind_path), FRAME_CACHE_DIR / row.blind_id)
    return hash_asset([f.path for f in extracted])


def _known_transcript_state(row: MappingRow) -> tuple[str, str, bool]:
    """(transcript_status, transcript_hash, is_known). is_known=False means the transcript
    has never been attempted under the current pipeline — we cannot predict its eventual
    hash without calling Whisper, so the caller must treat this asset as new/uncached rather
    than guessing a cache key that could never legitimately match anything."""
    if row.asset_type != "video":
        return "N/A", "", True
    cached = peek_cached_transcript(Path(row.blind_path))
    if cached is None:
        return "", "", False
    return cached.status, cached.transcript_hash or "", True


def _estimate_transcript_tokens(row: MappingRow) -> int:
    """Video only — rough token estimate for the (not-yet-generated) Whisper transcript."""
    if row.asset_type != "video":
        return 0
    duration_sec, _, _ = _video_metadata(Path(row.blind_path))
    words = (duration_sec / 60) * ASSUMED_SPOKEN_WORDS_PER_MIN
    return round(words * ASSUMED_TOKENS_PER_WORD)


@dataclass
class WhisperCostReport:
    new_count: int = 0
    cached_count: int = 0
    estimated_cost_usd: float = 0.0


def build_whisper_cost_report(mapping_rows: list[MappingRow]) -> WhisperCostReport:
    """Whisper transcript는 vision provider와 무관하게 (영상 해시, whisper model, pipeline
    version) 기준으로 단 한 번만 과금된다 — OpenAI/Claude 벤치마크 양쪽에서 공유되는 비용이므로
    한 번만 계산해서 보여준다 (transcript.py의 캐시 키와 동일 기준).

    25MB 한도는 추출된 오디오 기준이라(원본 영상 크기가 아니라) 원본 크기만으로는 사전에
    통과/실패를 알 수 없다 — 로컬 오디오 추출(무료)로 실제 결과를 예측한다."""
    report = WhisperCostReport()
    for row in mapping_rows:
        if row.asset_type != "video":
            continue
        path = Path(row.blind_path)

        cached = peek_cached_transcript(path)
        if cached is not None:
            report.cached_count += 1
            continue

        from src.cache import hash_file

        predicted_status, _ = predict_transcript_outcome(path, hash_file(path))
        if predicted_status != "PREDICTED_OK":
            continue  # 결정적으로 실패 예상 (오디오 없음/추출 후에도 용량 초과) — Whisper 호출 자체가 안 됨

        report.new_count += 1
        duration_sec, _, _ = _video_metadata(path)
        per_minute = get_model_config()["pricing_usd"]["whisper"]["per_minute"]
        report.estimated_cost_usd += (duration_sec / 60) * per_minute

    return report


@dataclass
class ProviderCostReport:
    provider_name: str
    model: str = ""
    input_price_per_1k: float = 0.0
    output_price_per_1k: float = 0.0
    new_count: int = 0
    cached_count: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    image_token_formula: str = ""
    new_blind_ids: list[str] = field(default_factory=list)


def build_cost_report(mapping_rows: list[MappingRow], provider: ProviderBase) -> ProviderCostReport:
    cfg = get_model_config()
    prompt_version = cfg["prompt_version"]
    schema_version = cfg["schema_version"]
    prompt_text = load_benchmark_prompt_text()

    report = ProviderCostReport(
        provider_name=provider.name,
        model=provider.model,
        input_price_per_1k=provider.pricing["input_per_1k_tokens"],
        output_price_per_1k=provider.pricing["output_per_1k_tokens"],
        image_token_formula=provider.image_token_formula_description(),
    )

    from src.cache import get_cached_result

    for row in mapping_rows:
        paths = _asset_paths(row)
        asset_hash = hash_asset(paths)

        transcript_status, transcript_hash, transcript_known = _known_transcript_state(row)
        if transcript_known:
            frame_set_hash = _frame_set_hash_for_asset(row)
            cache_key = build_cache_key(
                asset_hash, frame_set_hash, transcript_status, transcript_hash,
                provider.name, provider.model, prompt_version, schema_version,
            )
            if get_cached_result(cache_key) is not None:
                report.cached_count += 1
                continue
        # transcript_known이 False면(영상 transcript를 아직 한 번도 시도 안 함) 어떤 캐시 키가
        # 나올지 미리 알 수 없으므로 — 추측하지 않고 그냥 신규로 집계한다 (안전한 쪽으로 처리).

        report.new_count += 1
        report.new_blind_ids.append(row.blind_id)

        image_dims = _frame_dimensions_for_asset(row)
        transcript_tokens = _estimate_transcript_tokens(row)
        breakdown = provider.estimate_cost(image_dims, prompt_text, transcript_tokens)

        report.estimated_input_tokens += breakdown.estimated_input_tokens
        report.estimated_output_tokens += breakdown.estimated_output_tokens
        report.estimated_cost_usd += breakdown.estimated_cost_usd

    return report


def print_approval_summary(
    reports: list[ProviderCostReport],
    total_assets: int,
    whisper_report: WhisperCostReport | None = None,
) -> None:
    print("=" * 70)
    print(f"총 소재: {total_assets}개")
    for r in reports:
        print(f"\n[{r.provider_name}] model: {r.model}")
        print(f"  신규 API 분석 대상: {r.new_count}건 / 캐시 재사용: {r.cached_count}건")
        print(f"  input 단가: ${r.input_price_per_1k:.5f}/1K tokens  |  output 단가: ${r.output_price_per_1k:.5f}/1K tokens")
        print(f"  예상 input tokens (신규 {r.new_count}건 합계): {r.estimated_input_tokens:,}")
        print(f"  예상 output tokens (신규 {r.new_count}건 합계, 예상치): {r.estimated_output_tokens:,}")
        print(f"  vision/image 비용 계산 방식: {r.image_token_formula}")
        print(f"  예상 총 비용: ${r.estimated_cost_usd:.4f}")
    if whisper_report is not None and (whisper_report.new_count or whisper_report.cached_count):
        print(
            f"\n[whisper transcript] 신규 호출: {whisper_report.new_count}건 / 캐시 재사용: {whisper_report.cached_count}건 "
            f"— 예상 비용: ${whisper_report.estimated_cost_usd:.4f} "
            "(vision provider와 무관하게 1회만 과금됨; 영상 길이 metadata 기반 실측치)"
        )
    print("\n" + "=" * 70)
    print("참고: image 토큰 수는 실제 프레임 해상도 기반 공식 계산치. output 토큰 수와 영상")
    print("transcript 분량은 사전에 알 수 없어 예상치이며, 실제 비용은 이와 다를 수 있다.")
    print("=" * 70)


def prompt_approval() -> bool:
    answer = input("실행하시겠습니까? [Y/N] ").strip().lower()
    return answer == "y"
