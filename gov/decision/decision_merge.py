from __future__ import annotations

from typing import Any, Dict


def merge_decision(engine_result: Dict[str, Any], llm_result: Dict[str, Any]) -> Dict[str, Any]:
    """Combine deterministic engine output with advisory LLM guidance."""

    if engine_result.get("compliance_blocker"):
        return {
            "final_decision": "SKIP",
            "reason": "Compliance blocker detected",
        }

    engine_recommendation = engine_result.get("recommendation")
    if engine_recommendation == "SKIP" and llm_result.get("final_decision") == "HOLD":
        return llm_result

    return {
        "final_decision": engine_recommendation,
        "reason": "Engine-determined outcome",
    }

