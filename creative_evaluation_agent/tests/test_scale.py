import pytest

from src.scale import compute_scale, meets_scale_threshold, scale_level_for_index
from tests.factories import make_row


@pytest.mark.parametrize(
    "index,expected",
    [(0.1, "Under-delivery"), (0.49, "Under-delivery"), (0.5, "Low Scale"), (0.79, "Low Scale"),
     (0.8, "Normal"), (1.2, "Normal"), (1.21, "High"), (1.5, "High"), (1.51, "Strong")],
)
def test_scale_band_boundaries(index, expected):
    assert scale_level_for_index(index) == expected


def test_meets_scale_threshold():
    assert meets_scale_threshold(0.8) is True
    assert meets_scale_threshold(0.79) is False


def test_equal_share_and_scale_index_for_three_equal_creatives():
    # 제품 하나에 소재 3개, 동일 비중으로 지출 -> Equal Share = 33.33%, Scale Index = 1.0 (Normal)
    rows = [
        make_row(2, "무글틴", "전환", "메타", "A", 100, 10, 100, 1, 100),
        make_row(3, "무글틴", "전환", "메타", "B", 100, 10, 100, 1, 100),
        make_row(4, "무글틴", "전환", "메타", "C", 100, 10, 100, 1, 100),
    ]
    scale = compute_scale(rows)
    for creative_id in ("메타__A", "메타__B", "메타__C"):
        result = scale[creative_id]
        assert result.equal_share == pytest.approx(1 / 3)
        assert result.scale_index == pytest.approx(1.0)
        assert result.scale_level == "Normal"


def test_under_delivery_creative():
    # 소재 A는 지출 10%만 차지, 소재 B가 나머지 90% -> A의 Scale Index < 0.5
    rows = [
        make_row(2, "무글틴", "전환", "메타", "A", 100, 10, 100, 1, 100),
        make_row(3, "무글틴", "전환", "메타", "B", 100, 10, 900, 1, 100),
    ]
    scale = compute_scale(rows)
    a = scale["메타__A"]
    assert a.spend_share == pytest.approx(0.1)
    assert a.equal_share == pytest.approx(0.5)
    assert a.scale_index == pytest.approx(0.2)
    assert a.scale_level == "Under-delivery"


def test_zero_spend_creative_is_invalid_and_excluded_from_scale_index():
    rows = [
        make_row(2, "무글틴", "전환", "메타", "A", 100, 10, 100, 1, 100),
        make_row(3, "무글틴", "전환", "메타", "B", 100, 0, 0, 0, 0),
    ]
    scale = compute_scale(rows)
    b = scale["메타__B"]
    assert b.is_valid_creative is False
    assert b.scale_index is None
    assert "CHECK:INVALID_CREATIVE_ZERO_SPEND" in b.status
