from __future__ import annotations

import dataclasses
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from main import AnalysisResult


def _normalize_recommendation(label: str) -> str:
    simplified = label.lower()
    if "skip" in simplified:
        return "SKIP"
    if "hold" in simplified:
        return "HOLD"
    return "BID"


def engine_result_from_analysis(result: "AnalysisResult") -> Dict[str, Any]:
    """Build a compact engine result dictionary for LLM consumption.

    The LLM is advisory-only. The deterministic engine remains the source of truth.
    """

    recommendation = _normalize_recommendation(result.win_probability.recommendation)
    compliance_flags = dataclasses.asdict(result.compliance_flags)

    return {
        "rfq_number": result.snapshot.rfq_number,
        "nsn": result.snapshot.nsn,
        "quantity": result.snapshot.quantity,
        "fdt": result.compliance_flags.fdt,
        "packaging_required": result.compliance_flags.packaging,
        "cyber_required": result.compliance_flags.cyber,
        "sprs_required": result.compliance_flags.cyber,
        "historical_prices": result.price_intelligence.history_prices,
        "score": result.win_probability.score,
        "recommendation": recommendation,
        "flags": compliance_flags,
        "company_capability": result.win_probability.rationale,
        "automation_fields": result.automation_fields,
        "compliance_blocker": False,
    }


def build_decision_context(engine_result: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare the decision context payload expected by the LLM advisor."""

    return {
        "rfq_number": engine_result.get("rfq_number"),
        "nsn": engine_result.get("nsn"),
        "quantity": engine_result.get("quantity"),
        "fdt": engine_result.get("fdt"),
        "packaging_required": engine_result.get("packaging_required"),
        "cyber_required": engine_result.get("cyber_required"),
        "sprs_required": engine_result.get("sprs_required"),
        "historical_prices": engine_result.get("historical_prices"),
        "engine_score": engine_result.get("score"),
        "engine_recommendation": engine_result.get("recommendation"),
        "flags": engine_result.get("flags"),
        "company_capability": engine_result.get("company_capability"),
        "automation_fields": engine_result.get("automation_fields"),
    }

