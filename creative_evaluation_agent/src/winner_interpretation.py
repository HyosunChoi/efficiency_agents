"""Winner 해석 레이어 (Build Spec V2 §5).

기본 Final_Classification(WINNER/HIDDEN GEM/BUDGET DRAINER/UNDERPERFORMER/PROMISING/UNRESOLVED)
과는 분리된 2차 해석 레이어다 (spec §15: "기본 성과 Classification과 대표 위너 선정 레이어를 분리").
이 모듈은 evaluator.py가 이미 계산한 결과만 재사용하고 새로운 KPI를 계산하지 않는다.

Primary_Winner는 Efficiency Leader와 Scaled Winner가 동일 소재일 때만 규칙엔진이 자동 확정한다.
두 후보가 다르면 spec V2가 명시적으로 금지한 임의 threshold(예: "ROAS 차이 몇% 이내면 Scale 우선")를
만들지 않고 CHECK로 남겨 Human_Override/Primary_Winner_Reason으로 사람이 확정하게 한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.config_loader import get_evaluation_rules
from src.evaluator import CreativeEvaluation

EFFICIENCY_LEADER = "EFFICIENCY_LEADER"
SCALED_WINNER = "SCALED_WINNER"
BOTH = "BOTH"
NONE_TYPE = "NONE"


@dataclass
class WinnerInterpretation:
    creative_id: str
    efficiency_rank: int | None
    delivery_rank: int | None
    allocation_context: str
    winner_type: str
    primary_winner: str  # "Y" | "N" | "N/A" | "CHECK"
    primary_winner_reason: str


def _efficiency_sort_key(ev: CreativeEvaluation):
    if ev.objective == "Conversion":
        return (-(ev.kpis.roas or 0),)
    # Traffic: CPC 낮을수록 좋음(1차), CTR 높을수록 좋음(2차, tie-break)
    cpc = ev.kpis.cpc if ev.kpis.cpc is not None else float("inf")
    return (cpc, -(ev.kpis.ctr or 0))


def _delivery_sort_key(ev: CreativeEvaluation):
    return -(ev.scale.creative_spend if ev.scale else 0)


def compute_winner_interpretation(
    evaluations: list[CreativeEvaluation],
) -> dict[str, WinnerInterpretation]:
    """Returns {creative_id: WinnerInterpretation}, one entry per evaluation (group unaware)."""
    rules = get_evaluation_rules()["winner_interpretation"]
    results: dict[str, WinnerInterpretation] = {}

    groups: dict[tuple[str, str], list[CreativeEvaluation]] = {}
    for ev in evaluations:
        groups.setdefault((ev.product, ev.objective), []).append(ev)

    for (product, objective), group in groups.items():
        eligible_labels = set(rules["eligible_final_classifications"].get(objective, []))
        scaled_labels = set(rules["scaled_winner_final_classifications"].get(objective, []))

        eligible_ids = {ev.creative_id for ev in group if ev.final_classification in eligible_labels}
        eligible = [ev for ev in group if ev.creative_id in eligible_ids]

        eff_sorted = sorted(eligible, key=_efficiency_sort_key)
        delivery_sorted = sorted(eligible, key=_delivery_sort_key)
        efficiency_rank = {ev.creative_id: i + 1 for i, ev in enumerate(eff_sorted)}
        delivery_rank = {ev.creative_id: i + 1 for i, ev in enumerate(delivery_sorted)}

        efficiency_leader = eff_sorted[0] if eff_sorted else None

        scaled_candidates = [ev for ev in eligible if ev.final_classification in scaled_labels]
        scaled_candidates_by_delivery = sorted(scaled_candidates, key=_delivery_sort_key)
        scaled_winner = scaled_candidates_by_delivery[0] if scaled_candidates_by_delivery else None

        for ev in group:
            if ev.creative_id not in eligible_ids:
                results[ev.creative_id] = WinnerInterpretation(
                    creative_id=ev.creative_id,
                    efficiency_rank=None,
                    delivery_rank=None,
                    allocation_context=ev.allocation_context,
                    winner_type=NONE_TYPE,
                    primary_winner="N/A",
                    primary_winner_reason="Benchmark 이상 효율 조건 미충족 (Final_Classification 기준)",
                )
                continue

            is_eff_leader = efficiency_leader is not None and ev.creative_id == efficiency_leader.creative_id
            is_scaled_winner = scaled_winner is not None and ev.creative_id == scaled_winner.creative_id

            if is_eff_leader and is_scaled_winner:
                winner_type = BOTH
            elif is_eff_leader:
                winner_type = EFFICIENCY_LEADER
            elif is_scaled_winner:
                winner_type = SCALED_WINNER
            else:
                winner_type = NONE_TYPE

            results[ev.creative_id] = WinnerInterpretation(
                creative_id=ev.creative_id,
                efficiency_rank=efficiency_rank.get(ev.creative_id),
                delivery_rank=delivery_rank.get(ev.creative_id),
                allocation_context=ev.allocation_context,
                winner_type=winner_type,
                primary_winner="",  # _assign_primary_winner가 채움
                primary_winner_reason="",
            )

        _assign_primary_winner(group, eligible_ids, efficiency_leader, scaled_winner, results)

    return results


def _assign_primary_winner(
    group: list[CreativeEvaluation],
    eligible_ids: set[str],
    efficiency_leader: CreativeEvaluation | None,
    scaled_winner: CreativeEvaluation | None,
    results: dict[str, WinnerInterpretation],
) -> None:
    if not eligible_ids:
        for ev in group:
            results[ev.creative_id].primary_winner = "N/A"
            results[ev.creative_id].primary_winner_reason = "해당 그룹에 Benchmark 이상 효율 소재 없음"
        return

    if (
        efficiency_leader is not None
        and scaled_winner is not None
        and efficiency_leader.creative_id == scaled_winner.creative_id
    ):
        winner_id = efficiency_leader.creative_id
        reason = (
            f"Efficiency Leader와 Scaled Winner가 동일 소재({winner_id}) — 자동 확정 "
            "(효율 1위이면서 Scale 조건도 충족)"
        )
        for ev in group:
            r = results[ev.creative_id]
            if ev.creative_id == winner_id:
                r.primary_winner = "Y"
            elif ev.creative_id in eligible_ids:
                r.primary_winner = "N"
            else:
                r.primary_winner = "N/A"
            r.primary_winner_reason = reason
        return

    eff_desc = f"{efficiency_leader.creative_id}(효율 1위)" if efficiency_leader else "없음"
    scaled_desc = f"{scaled_winner.creative_id}(Scale 충족+Delivery 1위)" if scaled_winner else "없음"
    reason = (
        f"Efficiency Leader={eff_desc}, Scaled Winner={scaled_desc} — 서로 다른 소재라 고정 "
        "threshold 없이는 자동 확정 불가 (spec V2: Human_Override/Primary_Winner_Reason으로 "
        "최종 확정, Backtest 후 threshold 정교화 예정)"
    )
    for ev in group:
        r = results[ev.creative_id]
        r.primary_winner = "CHECK" if ev.creative_id in eligible_ids else "N/A"
        r.primary_winner_reason = reason
