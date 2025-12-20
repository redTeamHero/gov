"""Checklist generator for solicitation risks and compliance requirements.

Example JSON output:
{
  "summary": "Checklist for RFQ SPE4A6-24-Q-1234 (NSN 1234-56-789-0123)",
  "risks": [
    "Packaging must follow MIL-STD-129 / ASTM D3951 / RP001."
  ],
  "checklist": [
    {
      "id": "abc123-risk-1",
      "question": "Is the team prepared to mitigate this risk: Packaging must follow MIL-STD-129 / ASTM D3951 / RP001.?",
      "category": "risk"
    },
    {
      "id": "abc123-compliance-1",
      "question": "Can we meet the Packaging requirement?",
      "category": "compliance"
    }
  ]
}
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

DEFAULT_NON_RISK = "No special risks detected beyond standard FAR/DFARS terms."

COMPLIANCE_LABELS = {
    "buy_american": "Buy American Act",
    "berry_amendment": "Berry Amendment",
    "domestic_sourcing": "Domestic sourcing",
    "additive_manufacturing_restriction": "Additive manufacturing restriction",
    "packaging": "Packaging",
    "cyber": "Cybersecurity (NIST/SPRS)",
    "hazardous": "Hazardous material handling",
    "fdt": "First Destination Transportation (FDT)",
}


def _normalize_risks(value: Any) -> List[str]:
    if isinstance(value, list):
        risks = [str(item).strip() for item in value if item]
    elif isinstance(value, dict):
        risks = [str(item).strip() for item in value.values() if item]
    else:
        risks = []
    return [risk for risk in risks if risk and risk != DEFAULT_NON_RISK]


def _normalize_authoritative_risks(value: Any) -> List[str]:
    if not isinstance(value, dict):
        return []
    risks = []
    for key, raw in value.items():
        if not raw or str(raw).strip() == "Not stated in RFQ":
            continue
        label = key.replace("_", " ").strip()
        risks.append(f"{label}: {raw}")
    return risks


def _extract_risks(analysis: Dict[str, Any]) -> List[str]:
    if "risks" in analysis:
        return _normalize_risks(analysis.get("risks"))
    if "bid_risk_and_compliance_exposure" in analysis:
        return _normalize_authoritative_risks(analysis.get("bid_risk_and_compliance_exposure"))
    return []


def _extract_compliance_requirements(compliance_flags: Dict[str, Any]) -> List[str]:
    requirements = []
    for key, label in COMPLIANCE_LABELS.items():
        if compliance_flags.get(key):
            requirements.append(label)
    return requirements


def _extract_summary(analysis: Dict[str, Any]) -> str:
    rfq_number = ""
    nsn = ""
    if isinstance(analysis.get("snapshot"), dict):
        snapshot = analysis["snapshot"]
        rfq_number = str(snapshot.get("rfq_number") or "").strip()
        nsn = str(snapshot.get("nsn") or "").strip()
    elif isinstance(analysis.get("key_facts"), dict):
        facts = analysis["key_facts"]
        rfq_number = str(facts.get("rfq_number") or "").strip()
        nsn = str(facts.get("nsn") or "").strip()

    summary = "Checklist for solicitation review"
    if rfq_number and rfq_number != "Not stated in RFQ":
        summary = f"Checklist for RFQ {rfq_number}"
    if nsn and nsn != "Not stated in RFQ":
        summary = f"{summary} (NSN {nsn})"
    return summary


def _build_items(
    risks: Iterable[str],
    requirements: Iterable[str],
    id_prefix: str,
) -> List[Dict[str, str]]:
    items = []
    risk_index = 1
    for risk in risks:
        items.append(
            {
                "id": f"{id_prefix}-risk-{risk_index}",
                "question": f"Is the team prepared to mitigate this risk: {risk}?",
                "category": "risk",
            }
        )
        risk_index += 1

    req_index = 1
    for requirement in requirements:
        items.append(
            {
                "id": f"{id_prefix}-compliance-{req_index}",
                "question": f"Can we meet the {requirement} requirement?",
                "category": "compliance",
            }
        )
        req_index += 1
    return items


def generate_checklist(analysis: Dict[str, Any], id_prefix: Optional[str] = None) -> Dict[str, Any]:
    """Generate checklist JSON from an analysis payload."""
    prefix = id_prefix or "check"
    risks = _extract_risks(analysis)
    compliance_flags = analysis.get("compliance_flags") if isinstance(analysis.get("compliance_flags"), dict) else {}
    requirements = _extract_compliance_requirements(compliance_flags)
    checklist = _build_items(risks, requirements, prefix)

    return {
        "summary": _extract_summary(analysis),
        "risks": risks,
        "checklist": checklist,
    }
