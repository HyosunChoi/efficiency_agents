import pytest

from src.reliability import conversion_reliability, is_low_reliability, traffic_reliability


@pytest.mark.parametrize(
    "conversions,expected",
    [(0, "R0"), (2, "R0"), (3, "R1"), (4, "R1"), (5, "R2"), (9, "R2"), (10, "R3"), (1000, "R3")],
)
def test_conversion_reliability_boundaries(conversions, expected):
    assert conversion_reliability(conversions) == expected


@pytest.mark.parametrize(
    "clicks,expected",
    [(0, "R0"), (29, "R0"), (30, "R1"), (49, "R1"), (50, "R2"), (99, "R2"), (100, "R3"), (5000, "R3")],
)
def test_traffic_reliability_boundaries(clicks, expected):
    assert traffic_reliability(clicks) == expected


def test_low_reliability_flag():
    assert is_low_reliability("R0") is True
    assert is_low_reliability("R1") is True
    assert is_low_reliability("R2") is False
    assert is_low_reliability("R3") is False
