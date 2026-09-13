"""One-time migration for the 2026-09-12 transcript pipeline change (video -> local audio
extraction -> Whisper) and the resulting vision-analysis cache-key redesign.

Why this exists: cache.build_cache_key() now takes 8 components instead of 5 (frame_set_hash,
transcript_status, transcript_hash added). Every previously-cached vision result was written
under the OLD 5-component key, so under the new formula every single one of them would look
like a cache miss — even the 68 that are completely unaffected by the transcript change
(all images/carousels, plus every video whose transcript already worked before). Reprocessing
all of those with real paid API calls just because the key format changed would be wasteful
and pointless.

This module reconstructs, for each (asset, provider) pair, what transcript condition was
in effect when the OLD cached result was produced (from the OLD transcript cache, which
predates PIPELINE_VERSION), predicts the NEW pipeline's outcome using ONLY local/free
operations (audio extraction + size/format checks — never calling Whisper), and:
  - migrates the old cached result forward to its new cache key when the transcript
    condition is unchanged (no reprocessing needed, no API cost), or
  - leaves it alone (a genuine cache miss under the new key) when the transcript condition
    will actually change, so the existing approval-gated `benchmark run` flow picks it up
    and reprocesses it normally.

Deliberately never calls Whisper or a vision provider — see plan_migration()/apply_migration()
docstrings for exactly what each does.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.blind_mapper import MappingRow, load_mapping
from src.cache import (
    ANALYSIS_CACHE_DIR,
    build_cache_key,
    build_transcript_cache_key,
    hash_asset,
    hash_file,
    save_cached_transcript,
)
from src.config_loader import get_model_config
from src.frame_extractor import extract_frames
from src.providers.base import CreativeAnalysisResult
from src.transcript import hash_text, predict_transcript_outcome, transcript_cache_key_for

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRAME_CACHE_DIR = PROJECT_ROOT / "cache" / "frames"

UNCHANGED_REUSED_LEGACY = "UNCHANGED_REUSED_LEGACY_TRANSCRIPT"  # video, old transcript OK -> kept as-is
UNCHANGED_STILL_NO_TRANSCRIPT = "UNCHANGED_STILL_NO_TRANSCRIPT"  # deterministic fail, before and after
UNCHANGED_NOT_APPLICABLE = "UNCHANGED_NOT_APPLICABLE"  # image/carousel, no transcript concept
CHANGED_NEW_TRANSCRIPT_PREDICTED = "CHANGED_NEW_TRANSCRIPT_PREDICTED"  # was absent, now predicted OK
NO_PRIOR_RESULT = "NO_PRIOR_RESULT"  # nothing cached before for this (asset, provider) — nothing to migrate


def _legacy_vision_cache_key(asset_hash: str, provider: str, model: str, prompt_version: str, schema_version: str) -> str:
    """Reproduces the OLD (pre-2026-09-12) 5-component cache_key formula exactly, so we can
    find results that were cached under it before the key format changed."""
    import hashlib

    raw = f"{asset_hash}|{provider}|{model}|{prompt_version}|{schema_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class AssetMigrationPlan:
    blind_id: str
    asset_type: str
    provider: str
    category: str  # one of the module-level constants above
    old_transcript_status: str
    predicted_new_transcript_status: str
    detail: str
    asset_hash: str = ""
    frame_set_hash: str = ""
    new_transcript_status: str = ""
    new_transcript_hash: str = ""
    old_cache_path: Path | None = None
    legacy_transcript_text: str | None = None


@dataclass
class MigrationSummary:
    plans: list[AssetMigrationPlan] = field(default_factory=list)

    def counts_by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.plans:
            counts[p.category] = counts.get(p.category, 0) + 1
        return counts

    def reprocess_blind_ids(self, provider: str) -> list[str]:
        return sorted(
            {p.blind_id for p in self.plans if p.provider == provider and p.category == CHANGED_NEW_TRANSCRIPT_PREDICTED}
        )


def _asset_paths_for(row: MappingRow) -> list[Path]:
    path = Path(row.blind_path)
    return sorted(path.iterdir()) if path.is_dir() else [path]


def plan_migration(providers: list) -> MigrationSummary:
    """Read-only planning pass. Touches the filesystem only via extract_audio() (writes to
    cache/audio_staging/, never modifies source videos) and read-only cache lookups. No
    Whisper or vision-provider API call happens here."""
    cfg = get_model_config()
    prompt_version = cfg["prompt_version"]
    schema_version = cfg["schema_version"]
    whisper_model = cfg["transcript"]["model"]

    mapping_rows = load_mapping()
    summary = MigrationSummary()

    for row in mapping_rows:
        asset_paths = _asset_paths_for(row)
        asset_hash = hash_asset(asset_paths)

        for provider in providers:
            old_key = _legacy_vision_cache_key(asset_hash, provider.name, provider.model, prompt_version, schema_version)
            old_cache_path = ANALYSIS_CACHE_DIR / f"{old_key}.json"

            if not old_cache_path.exists():
                summary.plans.append(
                    AssetMigrationPlan(
                        blind_id=row.blind_id, asset_type=row.asset_type, provider=provider.name,
                        category=NO_PRIOR_RESULT, old_transcript_status="N/A",
                        predicted_new_transcript_status="N/A", detail="이전에 캐시된 결과 없음",
                        asset_hash=asset_hash,
                    )
                )
                continue

            if row.asset_type != "video":
                summary.plans.append(
                    AssetMigrationPlan(
                        blind_id=row.blind_id, asset_type=row.asset_type, provider=provider.name,
                        category=UNCHANGED_NOT_APPLICABLE, old_transcript_status="N/A",
                        predicted_new_transcript_status="N/A", detail="이미지/캐러셀 — transcript 해당 없음",
                        asset_hash=asset_hash, frame_set_hash=asset_hash,
                        new_transcript_status="N/A", new_transcript_hash="",
                        old_cache_path=old_cache_path,
                    )
                )
                continue

            # video: reconstruct old transcript condition from the legacy (pre-pipeline-version) key
            video_path = Path(row.blind_path)
            video_hash = hash_file(video_path)
            legacy_transcript_key = build_transcript_cache_key(video_hash, whisper_model)
            from src.cache import get_cached_transcript

            legacy_cached = get_cached_transcript(legacy_transcript_key)
            old_status = legacy_cached["status"] if legacy_cached else "ABSENT"
            legacy_text = legacy_cached.get("text") if legacy_cached else None

            frame_set_hash = hash_asset([f.path for f in extract_frames(video_path, FRAME_CACHE_DIR / row.blind_id)])

            if old_status == "OK" and legacy_text:
                summary.plans.append(
                    AssetMigrationPlan(
                        blind_id=row.blind_id, asset_type=row.asset_type, provider=provider.name,
                        category=UNCHANGED_REUSED_LEGACY, old_transcript_status=old_status,
                        predicted_new_transcript_status="OK (레거시 텍스트 재사용, Whisper 재호출 안 함)",
                        detail=f"기존 transcript {len(legacy_text)}자 그대로 이관",
                        asset_hash=asset_hash, frame_set_hash=frame_set_hash,
                        new_transcript_status="OK", new_transcript_hash=hash_text(legacy_text),
                        old_cache_path=old_cache_path, legacy_transcript_text=legacy_text,
                    )
                )
                continue

            predicted_status, detail = predict_transcript_outcome(video_path, video_hash)

            if predicted_status == "PREDICTED_OK":
                summary.plans.append(
                    AssetMigrationPlan(
                        blind_id=row.blind_id, asset_type=row.asset_type, provider=provider.name,
                        category=CHANGED_NEW_TRANSCRIPT_PREDICTED, old_transcript_status=old_status,
                        predicted_new_transcript_status=predicted_status, detail=detail,
                        asset_hash=asset_hash, frame_set_hash=frame_set_hash,
                        old_cache_path=old_cache_path,
                    )
                )
            else:
                summary.plans.append(
                    AssetMigrationPlan(
                        blind_id=row.blind_id, asset_type=row.asset_type, provider=provider.name,
                        category=UNCHANGED_STILL_NO_TRANSCRIPT, old_transcript_status=old_status,
                        predicted_new_transcript_status=predicted_status, detail=detail,
                        asset_hash=asset_hash, frame_set_hash=frame_set_hash,
                        new_transcript_status=predicted_status, new_transcript_hash="",
                        old_cache_path=old_cache_path,
                    )
                )

    return summary


def print_migration_report(summary: MigrationSummary) -> None:
    counts = summary.counts_by_category()
    print("=" * 70)
    print("Transcript 파이프라인 마이그레이션 — dry-run 계획 (API 호출 없음)")
    print("=" * 70)
    print(f"이전에 캐시된 결과 없음 (마이그레이션 대상 아님): {counts.get(NO_PRIOR_RESULT, 0)}건")
    print(f"이미지/캐러셀 — transcript 해당 없음, 그대로 이관: {counts.get(UNCHANGED_NOT_APPLICABLE, 0)}건")
    print(f"기존 transcript 성공 — 레거시 텍스트 재사용(재호출 없음), 그대로 이관: {counts.get(UNCHANGED_REUSED_LEGACY, 0)}건")
    print(f"기존에도 실패, 새 파이프라인에서도 실패 예상 — 그대로 이관: {counts.get(UNCHANGED_STILL_NO_TRANSCRIPT, 0)}건")
    print(f"기존엔 실패했으나 새 파이프라인에서 성공 예상 — 재분석 필요: {counts.get(CHANGED_NEW_TRANSCRIPT_PREDICTED, 0)}건")
    print()

    for provider_name in sorted({p.provider for p in summary.plans}):
        reprocess = summary.reprocess_blind_ids(provider_name)
        total_prior = sum(
            1 for p in summary.plans if p.provider == provider_name and p.category != NO_PRIOR_RESULT
        )
        reuse = total_prior - len(reprocess)
        print(f"[{provider_name}] 재분석 대상: {len(reprocess)}건 {reprocess} / 기존 결과 재사용: {reuse}건")

    print()
    print("재분석 예상 대상 상세 (신규 transcript 성공 예상):")
    for p in summary.plans:
        if p.category == CHANGED_NEW_TRANSCRIPT_PREDICTED:
            print(f"  {p.blind_id} ({p.provider}): {p.detail}")
    print("=" * 70)


def apply_migration(summary: MigrationSummary) -> dict[str, int]:
    """Performs the migration decided by plan_migration(): copies old-keyed vision cache
    entries forward to their new keys for every UNCHANGED_* category, and pre-populates the
    new-pipeline transcript cache for legacy-reused transcripts. Never touches entries in the
    CHANGED_NEW_TRANSCRIPT_PREDICTED category — those are left as genuine cache misses so the
    normal (approval-gated) benchmark run reprocesses them for real.
    """
    cfg = get_model_config()
    prompt_version = cfg["prompt_version"]
    schema_version = cfg["schema_version"]
    whisper_model = cfg["transcript"]["model"]

    migrated = 0
    skipped_changed = 0

    for p in summary.plans:
        if p.category == NO_PRIOR_RESULT:
            continue
        if p.category == CHANGED_NEW_TRANSCRIPT_PREDICTED:
            skipped_changed += 1
            continue

        with open(p.old_cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = CreativeAnalysisResult.model_validate(data)

        result = result.model_copy(
            update={
                "transcript_available": p.category == UNCHANGED_REUSED_LEGACY,
                "transcript_status": p.new_transcript_status,
                "transcript_char_count": len(p.legacy_transcript_text or ""),
                "transcript_source": whisper_model if p.category == UNCHANGED_REUSED_LEGACY else None,
                "transcript_hash": p.new_transcript_hash or None,
                "audio_extraction_status": "OK" if p.category == UNCHANGED_REUSED_LEGACY else (
                    "N/A" if p.asset_type != "video" else p.predicted_new_transcript_status
                ),
            }
        )

        # provider 객체 없이도 동일한 model 문자열을 result에서 그대로 가져와 새 키를 계산한다.
        new_key = build_cache_key(
            p.asset_hash, p.frame_set_hash, p.new_transcript_status, p.new_transcript_hash,
            p.provider, result.model, prompt_version, schema_version,
        )
        new_path = ANALYSIS_CACHE_DIR / f"{new_key}.json"
        with open(new_path, "w", encoding="utf-8") as f:
            f.write(result.model_dump_json(indent=2))

        if p.category == UNCHANGED_REUSED_LEGACY:
            new_transcript_key = transcript_cache_key_for(hash_file(Path(_find_video_path(p.blind_id))), whisper_model)
            save_cached_transcript(new_transcript_key, {
                "text": p.legacy_transcript_text, "status": "OK",
                "char_count": len(p.legacy_transcript_text or ""), "source": whisper_model,
                "transcript_hash": p.new_transcript_hash, "error_code": None,
                "audio_extraction_status": "OK",
            })

        migrated += 1

    return {"migrated": migrated, "left_for_reprocessing": skipped_changed}


def _find_video_path(blind_id: str) -> str:
    for row in load_mapping():
        if row.blind_id == blind_id:
            return row.blind_path
    raise KeyError(blind_id)
