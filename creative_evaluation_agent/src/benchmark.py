"""Engine 01 KPI 계산 — 반드시 Σ분자/Σ분모 재계산 (spec §5). 단순 평균 절대 금지.

이 모듈의 KPI 공식은 Benchmark(제품x Objective) 집계와 Performance(제품x Objective x소재명)
집계 양쪽에서 재사용된다 (evaluator.py가 창의 단위 재계산에 동일 함수를 사용).
분모가 0이면 그 KPI는 계산하지 않고 CHECK로 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.loader import AdRow
from src.validator import classify_objective

NUMERIC_FIELDS = ["Impressions", "Clicks", "Spend", "Conversions", "Revenue"]


@dataclass
class KpiResult:
    sum_impressions: float = 0.0
    sum_clicks: float = 0.0
    sum_spend: float = 0.0
    sum_conversions: float = 0.0
    sum_revenue: float = 0.0
    row_count: int = 0
    excluded_row_count: int = 0

    ctr: float | None = None
    cpc: float | None = None
    cpm: float | None = None
    cvr: float | None = None
    cpa: float | None = None
    roas: float | None = None
    kpi_status: dict = field(default_factory=dict)  # kpi name -> "CHECK:ZERO_DENOMINATOR"

    def finalize(self) -> None:
        self.ctr = self._safe_div(self.sum_clicks, self.sum_impressions, "ctr")
        self.cpc = self._safe_div(self.sum_spend, self.sum_clicks, "cpc")
        self.cpm = self._safe_div(self.sum_spend, self.sum_impressions, "cpm")
        if self.cpm is not None:
            self.cpm *= 1000
        self.cvr = self._safe_div(self.sum_conversions, self.sum_clicks, "cvr")
        self.cpa = self._safe_div(self.sum_spend, self.sum_conversions, "cpa")
        self.roas = self._safe_div(self.sum_revenue, self.sum_spend, "roas")

    def _safe_div(self, numerator: float, denominator: float, kpi_name: str) -> float | None:
        if denominator == 0:
            self.kpi_status[kpi_name] = "CHECK:ZERO_DENOMINATOR"
            return None
        return numerator / denominator


def _row_has_numeric_issue(row: AdRow) -> bool:
    return any(
        status.startswith("CHECK:")
        and any(status.endswith(f"{f}_EMPTY") or status.endswith(f"{f}_NOT_NUMERIC") for f in NUMERIC_FIELDS)
        for status in row.Row_Status
    )


def aggregate_kpis(rows: list[AdRow]) -> KpiResult:
    result = KpiResult()
    for row in rows:
        if _row_has_numeric_issue(row):
            result.excluded_row_count += 1
            continue
        result.sum_impressions += row.Impressions or 0
        result.sum_clicks += row.Clicks or 0
        result.sum_spend += row.Spend or 0
        result.sum_conversions += row.Conversions or 0
        result.sum_revenue += row.Revenue or 0
        result.row_count += 1
    result.finalize()
    return result


@dataclass
class BenchmarkGroup:
    product: str
    objective: str
    objective_status: str | None  # None if cleanly classified, else e.g. "CHECK"
    kpis: KpiResult


def compute_benchmarks(rows: list[AdRow]) -> dict[tuple[str, str], BenchmarkGroup]:
    """제품 x Objective 그룹별 Benchmark KPI. Objective는 classify_objective()로 분류."""
    rows_by_key: dict[tuple[str, str], list[AdRow]] = {}
    objective_status_by_key: dict[tuple[str, str], str | None] = {}

    for row in rows:
        objective, objective_status = classify_objective(row.Objective_Raw)
        key = (row.Product, objective)
        rows_by_key.setdefault(key, []).append(row)
        objective_status_by_key[key] = objective_status

    return {
        key: BenchmarkGroup(
            product=key[0],
            objective=key[1],
            objective_status=objective_status_by_key[key],
            kpis=aggregate_kpis(group_rows),
        )
        for key, group_rows in rows_by_key.items()
    }
