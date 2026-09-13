"""Cross-cutting validation: objective classification + row-level issue reporting.

Ambiguity always becomes an explicit status (UNKNOWN/CHECK), never a guess (spec §5/§12).
"""
from __future__ import annotations

from dataclasses import dataclass

from src.config_loader import get_evaluation_rules
from src.loader import AdRow

UNKNOWN_OBJECTIVE = "UNKNOWN_OBJECTIVE"


def classify_objective(raw_objective: str) -> tuple[str, str | None]:
    """Returns (classified_objective, status). status is None when classification succeeded."""
    rules = get_evaluation_rules()["objective_classification"]
    value = (raw_objective or "").strip().lower()

    for kw in rules.get("conversion_keywords", []):
        if kw.lower() in value:
            return "Conversion", None
    for kw in rules.get("traffic_keywords", []):
        if kw.lower() in value:
            return "Traffic", None

    return rules.get("unclassified_label", "UNKNOWN"), rules.get(
        "unclassified_status", "CHECK"
    )


@dataclass
class ValidationIssue:
    row_number: int
    creative_id: str
    codes: list[str]


def validate_rows(rows: list[AdRow]) -> list[ValidationIssue]:
    """Collects all non-fatal, row-level issues for the audit trail. Never raises."""
    issues: list[ValidationIssue] = []
    for row in rows:
        codes = list(row.Row_Status)
        _, objective_status = classify_objective(row.Objective_Raw)
        if objective_status:
            codes.append(f"{objective_status}:{UNKNOWN_OBJECTIVE}")
        if codes:
            issues.append(
                ValidationIssue(row_number=row.row_number, creative_id=row.Creative_ID, codes=codes)
            )
    return issues
