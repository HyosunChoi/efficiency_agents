"""Winner 해석 레이어 (spec V2 §5) — Final_Classification과 분리된 2차 레이어 검증."""
from src.benchmark import compute_benchmarks
from src.evaluator import evaluate_all
from src.scale import compute_scale
from src.winner_interpretation import (
    BOTH,
    EFFICIENCY_LEADER,
    NONE_TYPE,
    SCALED_WINNER,
    compute_winner_interpretation,
)
from tests.factories import make_row


def _run(rows):
    benchmarks = compute_benchmarks(rows)
    scale = compute_scale(rows)
    evaluations = evaluate_all(rows, benchmarks, scale)
    winners = compute_winner_interpretation(evaluations)
    return {ev.creative_id: ev for ev in evaluations}, winners


def test_single_dominant_creative_is_both_and_auto_confirmed_primary_winner():
    # 한 소재만 BM 이상(WINNER)이고 나머지는 미달 -> 그 소재가 Efficiency Leader이자 Scaled Winner.
    rows = [
        make_row(2, "P", "전환", "M", "WINNER_ONE", 1000, 100, 1000, 10, 2000),  # ROAS 2.0, R3, scale 1.0
        make_row(3, "P", "전환", "M", "LOSER", 1000, 100, 1000, 5, 500),         # ROAS 0.5, R2, scale 1.0
    ]
    evals, winners = _run(rows)
    assert evals["M__WINNER_ONE"].final_classification == "WINNER"

    w = winners["M__WINNER_ONE"]
    assert w.winner_type == BOTH
    assert w.primary_winner == "Y"
    assert w.efficiency_rank == 1
    assert w.delivery_rank == 1

    loser = winners["M__LOSER"]
    assert loser.winner_type == NONE_TYPE
    assert loser.primary_winner == "N/A"


def test_efficiency_leader_and_scaled_winner_differ_yields_check_not_a_guess():
    # A: 적은 예산으로 최고 효율 (Hidden Gem, scale<0.8) -> Efficiency Leader
    # B: 큰 예산 소화하며 BM은 넘지만 A보다 효율 낮음, scale>=0.8(WINNER) -> Scaled Winner
    # C: BM 미만인 소재를 하나 더 넣어 그룹 BM(가중평균)이 A/B 둘 다보다 낮아지게 만든다
    #    (BM은 이 그룹 전체 Σ로 재계산되므로, 소재 2개만으로는 항상 하나는 BM 미만이 된다).
    rows = [
        make_row(2, "P", "전환", "M", "BIG_BUDGET", 1000, 100, 1800, 10, 2700),      # ROAS 1.5, 큰 비중
        make_row(3, "P", "전환", "M", "SMALL_HIGH_ROAS", 1000, 100, 200, 10, 800),   # ROAS 4.0, 작은 비중
        make_row(4, "P", "전환", "M", "DRAG_DOWN_BM", 1000, 100, 1000, 1, 100),      # ROAS 0.1, R0
    ]
    evals, winners = _run(rows)
    assert evals["M__BIG_BUDGET"].final_classification == "WINNER"
    assert evals["M__SMALL_HIGH_ROAS"].final_classification == "HIDDEN GEM"

    eff_leader = winners["M__SMALL_HIGH_ROAS"]
    scaled = winners["M__BIG_BUDGET"]

    assert eff_leader.winner_type == EFFICIENCY_LEADER
    assert scaled.winner_type == SCALED_WINNER

    # 서로 다른 소재 -> 고정 threshold 없이 자동확정 금지, 둘 다 CHECK + 근거 남김
    assert eff_leader.primary_winner == "CHECK"
    assert scaled.primary_winner == "CHECK"
    assert eff_leader.primary_winner_reason == scaled.primary_winner_reason
    assert "SMALL_HIGH_ROAS" in eff_leader.primary_winner_reason
    assert "BIG_BUDGET" in eff_leader.primary_winner_reason


def test_no_eligible_creative_in_group_is_all_none():
    rows = [
        make_row(2, "P", "전환", "M", "BAD_A", 1000, 100, 1000, 1, 100),  # ROAS 0.1, R0
        make_row(3, "P", "전환", "M", "BAD_B", 1000, 100, 1000, 1, 200),  # ROAS 0.2, R0
    ]
    _, winners = _run(rows)
    for w in winners.values():
        assert w.winner_type == NONE_TYPE
        assert w.primary_winner == "N/A"
        assert w.efficiency_rank is None
        assert w.delivery_rank is None


def test_traffic_objective_ranks_by_cpc_ascending():
    rows = [
        make_row(2, "P", "트래픽", "M", "BM_REF", 1000, 100, 100, 0, 0),   # CPC=1.0, CTR=10%
        make_row(3, "P", "트래픽", "M", "CHEAP", 1000, 200, 100, 0, 0),    # CPC=0.5, CTR=20% (더 효율적)
        make_row(4, "P", "트래픽", "M", "OK", 500, 100, 100, 0, 0),        # CPC=1.0, CTR=20%
    ]
    evals, winners = _run(rows)
    # BM_REF 자체는 그룹 벤치마크 구성원이라 TRAFFIC WINNER는 아닐 수 있음 — CHEAP이 가장 효율적인지만 확인
    assert winners["M__CHEAP"].efficiency_rank == 1


def test_allocation_context_defaults_to_unknown_when_not_provided():
    rows = [make_row(2, "P", "전환", "M", "X", 1000, 100, 1000, 10, 2000)]
    _, winners = _run(rows)
    assert winners["M__X"].allocation_context == "UNKNOWN"
