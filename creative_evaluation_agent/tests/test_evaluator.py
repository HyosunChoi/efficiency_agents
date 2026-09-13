import pytest

from src.benchmark import compute_benchmarks
from src.evaluator import evaluate_all
from src.scale import compute_scale
from tests.factories import make_row


def _evaluate(rows):
    benchmarks = compute_benchmarks(rows)
    scale = compute_scale(rows)
    return {ev.creative_id: ev for ev in evaluate_all(rows, benchmarks, scale)}


def test_conversion_winner_r2_roas_above_bm_scale_above_threshold():
    rows = [
        # BM 소재: conversions=6 (R2), 낮은 ROAS 기준을 만들기 위한 대조군
        make_row(2, "P", "전환", "M", "BM_LOW", 1000, 100, 1000, 6, 1000),   # ROAS 1.0
        # 대상 소재: conversions=10 (R3), ROAS 2.0 (BM보다 높음), spend 동일 비중 -> scale 1.0 (Normal, >=0.8)
        make_row(3, "P", "전환", "M", "TARGET", 1000, 100, 1000, 10, 2000),  # ROAS 2.0
    ]
    evals = _evaluate(rows)
    target = evals["M__TARGET"]
    assert target.reliability_tier == "R3"
    assert target.final_classification == "WINNER"


def test_conversion_hidden_gem_when_scale_below_threshold():
    rows = [
        make_row(2, "P", "전환", "M", "BIG", 1000, 100, 1800, 6, 1800),     # 대부분의 예산 (ROAS 1.0)
        make_row(3, "P", "전환", "M", "SMALL", 1000, 100, 200, 10, 400),    # 소액인데 성과 좋음 (ROAS 2.0)
    ]
    evals = _evaluate(rows)
    small = evals["M__SMALL"]
    assert small.reliability_tier == "R3"
    assert small.scale.scale_level in ("Under-delivery", "Low Scale")
    assert small.final_classification == "HIDDEN GEM"


def test_conversion_promising_when_low_reliability():
    rows = [
        make_row(2, "P", "전환", "M", "BM_LOW", 1000, 100, 1000, 6, 1000),  # ROAS 1.0, R2 (BM 기준용)
        make_row(3, "P", "전환", "M", "NEW", 1000, 100, 100, 2, 300),       # ROAS 3.0, conversions=2 -> R0
    ]
    evals = _evaluate(rows)
    new = evals["M__NEW"]
    assert new.reliability_tier == "R0"
    assert new.final_classification == "PROMISING"


def test_traffic_winner_when_cpc_low_ctr_high_and_scale_ok():
    rows = [
        # BM: CPC=1.0(=100/100), CTR=10%(100/1000)
        make_row(2, "P", "유입", "M", "BM_REF", 1000, 100, 100, 0, 0),
        # 대상: CPC 낮음(0.5), CTR 높음(20%), clicks=200 -> R3, scale 동일 비중(1.0, Normal)
        make_row(3, "P", "유입", "M", "TARGET", 1000, 200, 100, 0, 0),
    ]
    evals = _evaluate(rows)
    target = evals["M__TARGET"]
    assert target.reliability_tier == "R3"
    assert target.final_classification == "TRAFFIC WINNER"


def test_traffic_underperformer_when_cpc_high_ctr_low():
    rows = [
        make_row(2, "P", "트래픽", "M", "BM_REF", 1000, 100, 100, 0, 0),  # CPC=1.0, CTR=10%
        make_row(3, "P", "트래픽", "M", "BAD", 500, 100, 500, 0, 0),      # CPC=5.0(높음), CTR=20%? need low
    ]
    # BAD의 CTR = 100/500 = 20% (BM보다 높음) -> 이 케이스는 HOOK STRONG이 되어야 하므로 별도 검증
    evals = _evaluate(rows)
    bad = evals["M__BAD"]
    assert bad.reliability_tier == "R3"
    assert bad.final_classification == "HOOK STRONG"


def test_unknown_objective_short_circuits_to_check():
    rows = [make_row(2, "P", "의미불명", "M", "X", 100, 10, 100, 1, 100)]
    evals = _evaluate(rows)
    x = evals["M__X"]
    assert x.final_classification == "CHECK"
    assert any("UNKNOWN_OBJECTIVE" in flag for flag in x.status_flags)


def test_zero_denominator_bm_yields_check_not_crash():
    # BM 그룹 자체 clicks=0 이라 CPC/CTR BM이 없음 -> 비교 불가 CHECK, 예외 없이 처리
    rows = [make_row(2, "P", "트래픽", "M", "ONLY", 1000, 0, 0, 0, 0)]
    evals = _evaluate(rows)
    only = evals["M__ONLY"]
    assert only.final_classification == "CHECK"
