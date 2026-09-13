"""Engine 01 최종 분류 — Performance 그룹(제품 x Objective x 소재명) 단위 (spec §5).

01의 실제 성과 판정은 이 모듈에서 확정되며, 이후 어떤 AI 판단(Engine 02)도 이를 뒤집지 않는다
(spec §1/§10 Integration 원칙). 판정마다 근거값(Basis 1/2/3, Action, Final Comment)을 함께 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.benchmark import BenchmarkGroup, KpiResult, aggregate_kpis
from src.config_loader import get_evaluation_rules
from src.loader import AdRow
from src.reliability import conversion_reliability, is_low_reliability, traffic_reliability
from src.scale import CreativeScale, meets_scale_threshold
from src.validator import classify_objective

CHECK = "CHECK"


@dataclass
class CreativeEvaluation:
    product: str
    objective: str
    objective_status: str | None
    media_normalized: str
    creative_name_normalized: str
    creative_id: str

    kpis: KpiResult
    bm_kpis: KpiResult | None
    reliability_tier: str | None
    reliability_metric_name: str | None
    reliability_metric_value: float | None
    scale: CreativeScale | None
    allocation_context: str

    final_classification: str
    basis_1: str
    basis_2: str
    basis_3: str
    action: str
    final_comment: str
    status_flags: list[str] = field(default_factory=list)


def _classify_conversion(
    roas_actual: float | None,
    roas_bm: float | None,
    reliability_tier: str,
    scale_meets: bool | None,
) -> str:
    if roas_actual is None or roas_bm is None:
        return CHECK

    high_reliability = not is_low_reliability(reliability_tier)
    roas_ge_bm = roas_actual >= roas_bm

    if not high_reliability:
        return "PROMISING" if roas_ge_bm else "UNRESOLVED"

    if scale_meets is None:
        return CHECK

    if roas_ge_bm and scale_meets:
        return "WINNER"
    if roas_ge_bm and not scale_meets:
        return "HIDDEN GEM"
    if not roas_ge_bm and scale_meets:
        return "BUDGET DRAINER"
    return "UNDERPERFORMER"


def _classify_traffic(
    cpc_actual: float | None,
    cpc_bm: float | None,
    ctr_actual: float | None,
    ctr_bm: float | None,
    reliability_tier: str,
    scale_meets: bool | None,
    promising_operator: str,
) -> str:
    if cpc_actual is None or cpc_bm is None or ctr_actual is None or ctr_bm is None:
        return CHECK

    high_reliability = not is_low_reliability(reliability_tier)
    cpc_good = cpc_actual <= cpc_bm
    ctr_good = ctr_actual >= ctr_bm

    if not high_reliability:
        favorable = (cpc_good or ctr_good) if promising_operator == "OR" else (cpc_good and ctr_good)
        return "PROMISING" if favorable else "UNRESOLVED"

    if cpc_good and ctr_good:
        if scale_meets is None:
            return CHECK
        return "TRAFFIC WINNER" if scale_meets else "TRAFFIC HIDDEN GEM"
    if cpc_good and not ctr_good:
        return "COST EFFICIENT"
    if not cpc_good and ctr_good:
        return "HOOK STRONG"
    return "UNDERPERFORMER"


def _resolve_allocation_context(group_rows: list[AdRow]) -> str:
    """spec V2 §5: Allocation_Context는 아는 경우에만 채운다. 여러 행 중 하나라도 AUTO/MANUAL을
    밝히면 그 값을 쓰고(첫 값 우선), 전부 모르면 UNKNOWN — 임의 추정하지 않는다."""
    for row in group_rows:
        if row.Allocation_Context != "UNKNOWN":
            return row.Allocation_Context
    return "UNKNOWN"


def _fmt(value) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def evaluate_all(
    rows: list[AdRow],
    benchmarks: dict[tuple[str, str], BenchmarkGroup],
    scale_by_creative: dict[str, CreativeScale],
) -> list[CreativeEvaluation]:
    rules = get_evaluation_rules()
    promising_operator = rules.get("traffic_promising_interpretation", {}).get("operator", "OR")
    action_templates = rules.get("action_templates", {})

    rows_by_group: dict[tuple[str, str, str], list[AdRow]] = {}
    meta_by_group: dict[tuple[str, str, str], dict] = {}

    for row in rows:
        objective, objective_status = classify_objective(row.Objective_Raw)
        key = (row.Product, objective, row.Creative_ID)
        rows_by_group.setdefault(key, []).append(row)
        meta_by_group[key] = {
            "objective_status": objective_status,
            "media_normalized": row.Media_Normalized,
            "creative_name_normalized": row.Creative_Name_Normalized,
        }

    evaluations: list[CreativeEvaluation] = []

    for (product, objective, creative_id), group_rows in rows_by_group.items():
        meta = meta_by_group[(product, objective, creative_id)]
        status_flags: list[str] = []

        kpis = aggregate_kpis(group_rows)
        bm_group = benchmarks.get((product, objective))
        bm_kpis = bm_group.kpis if bm_group else None
        scale = scale_by_creative.get(creative_id)
        allocation_context = _resolve_allocation_context(group_rows)

        if meta["objective_status"]:
            status_flags.append(f"UNKNOWN_OBJECTIVE:{meta['objective_status']}")
            evaluations.append(
                CreativeEvaluation(
                    product=product,
                    objective=objective,
                    objective_status=meta["objective_status"],
                    media_normalized=meta["media_normalized"],
                    creative_name_normalized=meta["creative_name_normalized"],
                    creative_id=creative_id,
                    kpis=kpis,
                    bm_kpis=bm_kpis,
                    reliability_tier=None,
                    reliability_metric_name=None,
                    reliability_metric_value=None,
                    scale=scale,
                    allocation_context=allocation_context,
                    final_classification=CHECK,
                    basis_1="Objective를 Conversion/Traffic으로 분류할 수 없음",
                    basis_2="-",
                    basis_3="-",
                    action=action_templates.get(CHECK, ""),
                    final_comment="Objective 분류 불가로 성과 판정을 진행하지 않음. 원본 데이터의 Objective 표기를 확인하세요.",
                    status_flags=status_flags,
                )
            )
            continue

        scale_meets = meets_scale_threshold(scale.scale_index) if scale and scale.scale_index is not None else None
        if scale is None or scale.scale_index is None:
            status_flags.append("CHECK:SCALE_UNAVAILABLE")

        if objective == "Conversion":
            reliability_metric_name = "Conversions"
            reliability_metric_value = kpis.sum_conversions
            reliability_tier = conversion_reliability(reliability_metric_value)

            final_classification = _classify_conversion(
                kpis.roas, bm_kpis.roas if bm_kpis else None, reliability_tier, scale_meets
            )

            basis_1 = f"Reliability {reliability_tier} (Conversions={reliability_metric_value:.0f})"
            basis_2 = f"ROAS actual={_fmt(kpis.roas)} vs BM={_fmt(bm_kpis.roas if bm_kpis else None)}"
            basis_3 = (
                f"Scale Index={_fmt(scale.scale_index if scale else None)} "
                f"({scale.scale_level if scale and scale.scale_level else 'N/A'})"
            )
        else:  # Traffic
            reliability_metric_name = "Clicks"
            reliability_metric_value = kpis.sum_clicks
            reliability_tier = traffic_reliability(reliability_metric_value)

            final_classification = _classify_traffic(
                kpis.cpc,
                bm_kpis.cpc if bm_kpis else None,
                kpis.ctr,
                bm_kpis.ctr if bm_kpis else None,
                reliability_tier,
                scale_meets,
                promising_operator,
            )

            basis_1 = f"Reliability {reliability_tier} (Clicks={reliability_metric_value:.0f})"
            basis_2 = (
                f"CPC actual={_fmt(kpis.cpc)} vs BM={_fmt(bm_kpis.cpc if bm_kpis else None)}; "
                f"CTR actual={_fmt(kpis.ctr)} vs BM={_fmt(bm_kpis.ctr if bm_kpis else None)} "
                f"(CPM actual={_fmt(kpis.cpm)}, 진단용)"
            )
            basis_3 = (
                f"Scale Index={_fmt(scale.scale_index if scale else None)} "
                f"({scale.scale_level if scale and scale.scale_level else 'N/A'})"
            )

        if final_classification == CHECK:
            status_flags.append("CHECK:CLASSIFICATION_INCOMPLETE_DATA")

        action = action_templates.get(final_classification, "")
        final_comment = f"{final_classification} — {basis_1}; {basis_2}; {basis_3}"

        evaluations.append(
            CreativeEvaluation(
                product=product,
                objective=objective,
                objective_status=None,
                media_normalized=meta["media_normalized"],
                creative_name_normalized=meta["creative_name_normalized"],
                creative_id=creative_id,
                kpis=kpis,
                bm_kpis=bm_kpis,
                reliability_tier=reliability_tier,
                reliability_metric_name=reliability_metric_name,
                reliability_metric_value=reliability_metric_value,
                scale=scale,
                allocation_context=allocation_context,
                final_classification=final_classification,
                basis_1=basis_1,
                basis_2=basis_2,
                basis_3=basis_3,
                action=action,
                final_comment=final_comment,
                status_flags=status_flags,
            )
        )

    return evaluations
