import pytest

from src.benchmark import aggregate_kpis, compute_benchmarks
from tests.factories import make_row


def test_bm_is_aggregated_sum_ratio_not_simple_average():
    # 두 소재의 CTR은 각각 10%, 1%지만 단순평균(5.5%)이 아니라 Σ재계산 값이어야 한다.
    rows = [
        make_row(2, "무글틴", "전환", "메타", "A", 1000, 100, 100, 5, 500),  # CTR 10%
        make_row(3, "무글틴", "전환", "메타", "B", 9000, 90, 900, 5, 500),  # CTR 1%
    ]
    benchmarks = compute_benchmarks(rows)
    group = benchmarks[("무글틴", "Conversion")]
    # ΣClicks=190, ΣImpressions=10000 -> CTR = 1.9%
    assert group.kpis.ctr == pytest.approx(190 / 10000)
    assert group.kpis.ctr != pytest.approx((0.10 + 0.01) / 2)


def test_zero_denominator_is_check_not_zero():
    rows = [make_row(2, "무글틴", "전환", "메타", "A", 0, 0, 0, 0, 0)]
    result = aggregate_kpis(rows)
    assert result.ctr is None
    assert result.kpi_status["ctr"] == "CHECK:ZERO_DENOMINATOR"


def test_objective_classification_conversion_vs_traffic():
    rows = [
        make_row(2, "무글틴", "전환 캠페인", "메타", "A", 100, 10, 100, 5, 500),
        make_row(3, "무글틴", "트래픽", "메타", "B", 100, 10, 100, 0, 0),
        make_row(4, "무글틴", "이상한값", "메타", "C", 100, 10, 100, 0, 0),
    ]
    benchmarks = compute_benchmarks(rows)
    assert ("무글틴", "Conversion") in benchmarks
    assert ("무글틴", "Traffic") in benchmarks
    unknown_group = benchmarks[("무글틴", "UNKNOWN")]
    assert unknown_group.objective_status == "CHECK"
