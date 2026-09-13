"""Ground Truth vs 두 provider 예측 비교 (spec §9). Human review 컬럼은 빈 템플릿으로 남긴다."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook

from src.ground_truth import GroundTruthRow, load_ground_truth
from src.providers.base import CreativeAnalysisResult

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"
COMPARISON_PATH = RESULTS_DIR / "comparison" / "comparison_report.xlsx"

PROVIDERS = ["openai", "claude"]

DETAIL_COLUMNS = [
    "Blind_ID",
    "Observed_Performance",
    "OpenAI_Predicted_Response",
    "OpenAI_Confidence",
    "OpenAI_Direction_Status",
    "Claude_Predicted_Response",
    "Claude_Confidence",
    "Claude_Direction_Status",
    "OpenAI_Input_Tokens",
    "OpenAI_Output_Tokens",
    "OpenAI_Latency_Sec",
    "Claude_Input_Tokens",
    "Claude_Output_Tokens",
    "Claude_Latency_Sec",
    # Human review (spec §9) — 자동 채점 불가, 빈 템플릿
    "Visual_Observation_Accuracy_1to5",
    "Reason_Quality_1to5",
    "Hallucination_Yes_No",
    "Business_Usefulness_1to5",
    "Reviewer_Comment",
]


def _direction_status(observed: str | None, predicted: str | None) -> str:
    if not observed or not predicted:
        return "CHECK"
    if predicted == "MEDIUM":
        return "AI_NEUTRAL_OR_UNCERTAIN"
    if observed == "ABOVE_BENCHMARK" and predicted == "HIGH":
        return "PREDICTION_MATCH_HIGH"
    if observed == "BELOW_BENCHMARK" and predicted == "LOW":
        return "PREDICTION_MATCH_LOW"
    if observed == "BELOW_BENCHMARK" and predicted == "HIGH":
        return "AI_OVERPREDICTED"
    if observed == "ABOVE_BENCHMARK" and predicted == "LOW":
        return "AI_MISSED_WINNER"
    if observed == "AROUND_BENCHMARK":
        return "AI_NEUTRAL_OR_UNCERTAIN"
    return "CHECK"


def _load_provider_results(provider: str) -> dict[str, CreativeAnalysisResult]:
    results: dict[str, CreativeAnalysisResult] = {}
    provider_dir = RESULTS_DIR / provider
    if not provider_dir.exists():
        return results
    for path in provider_dir.glob("*.json"):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        results[data["blind_id"]] = CreativeAnalysisResult.model_validate(data)
    return results


@dataclass
class ComparisonSummary:
    provider: str
    n: int
    direction_hit_rate: float | None
    missed_winner_rate: float | None
    overestimate_rate: float | None


def build_comparison() -> tuple[list[dict], list[ComparisonSummary]]:
    ground_truth: list[GroundTruthRow] = load_ground_truth()  # raises if locked
    gt_by_id = {row.blind_id: row for row in ground_truth}

    openai_results = _load_provider_results("openai")
    claude_results = _load_provider_results("claude")

    detail_rows: list[dict] = []
    for blind_id, gt in sorted(gt_by_id.items()):
        openai_result = openai_results.get(blind_id)
        claude_result = claude_results.get(blind_id)

        detail_rows.append(
            {
                "Blind_ID": blind_id,
                "Observed_Performance": gt.observed_performance,
                "OpenAI_Predicted_Response": openai_result.ai_predicted_response if openai_result else None,
                "OpenAI_Confidence": openai_result.ai_confidence if openai_result else None,
                "OpenAI_Direction_Status": _direction_status(
                    gt.observed_performance, openai_result.ai_predicted_response if openai_result else None
                ),
                "Claude_Predicted_Response": claude_result.ai_predicted_response if claude_result else None,
                "Claude_Confidence": claude_result.ai_confidence if claude_result else None,
                "Claude_Direction_Status": _direction_status(
                    gt.observed_performance, claude_result.ai_predicted_response if claude_result else None
                ),
                "OpenAI_Input_Tokens": openai_result.input_tokens if openai_result else None,
                "OpenAI_Output_Tokens": openai_result.output_tokens if openai_result else None,
                "OpenAI_Latency_Sec": openai_result.latency_sec if openai_result else None,
                "Claude_Input_Tokens": claude_result.input_tokens if claude_result else None,
                "Claude_Output_Tokens": claude_result.output_tokens if claude_result else None,
                "Claude_Latency_Sec": claude_result.latency_sec if claude_result else None,
                "Visual_Observation_Accuracy_1to5": None,
                "Reason_Quality_1to5": None,
                "Hallucination_Yes_No": None,
                "Business_Usefulness_1to5": None,
                "Reviewer_Comment": None,
            }
        )

    summaries = [
        _summarize(detail_rows, provider, gt_by_id)
        for provider in ("OpenAI", "Claude")
    ]
    return detail_rows, summaries


def _summarize(detail_rows: list[dict], provider_label: str, gt_by_id: dict) -> ComparisonSummary:
    status_col = f"{provider_label}_Direction_Status"
    statuses = [r[status_col] for r in detail_rows if r[status_col] != "CHECK"]
    n = len(statuses)

    directional = [s for s in statuses if s in ("PREDICTION_MATCH_HIGH", "PREDICTION_MATCH_LOW", "AI_OVERPREDICTED", "AI_MISSED_WINNER")]
    hits = [s for s in directional if s in ("PREDICTION_MATCH_HIGH", "PREDICTION_MATCH_LOW")]

    above_count = sum(1 for r in detail_rows if r["Observed_Performance"] == "ABOVE_BENCHMARK")
    below_count = sum(1 for r in detail_rows if r["Observed_Performance"] == "BELOW_BENCHMARK")
    missed = sum(1 for r in detail_rows if r[status_col] == "AI_MISSED_WINNER")
    overestimated = sum(1 for r in detail_rows if r[status_col] == "AI_OVERPREDICTED")

    return ComparisonSummary(
        provider=provider_label,
        n=n,
        direction_hit_rate=(len(hits) / len(directional)) if directional else None,
        missed_winner_rate=(missed / above_count) if above_count else None,
        overestimate_rate=(overestimated / below_count) if below_count else None,
    )


def export_comparison_report() -> Path:
    detail_rows, summaries = build_comparison()

    wb = Workbook()
    ws_detail = wb.active
    ws_detail.title = "Detail"
    ws_detail.append(DETAIL_COLUMNS)
    for row in detail_rows:
        ws_detail.append([row[c] for c in DETAIL_COLUMNS])

    ws_summary = wb.create_sheet("Summary")
    ws_summary.append(["Provider", "N (direction 판정 가능)", "Direction_Hit_Rate", "Missed_Winner_Rate", "Overestimate_Rate"])
    for s in summaries:
        ws_summary.append([s.provider, s.n, s.direction_hit_rate, s.missed_winner_rate, s.overestimate_rate])

    COMPARISON_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(COMPARISON_PATH)
    logger.info("Comparison 리포트 생성: %s", COMPARISON_PATH)
    return COMPARISON_PATH
