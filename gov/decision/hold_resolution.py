from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _flatten_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)
    if isinstance(value, dict):
        return " ".join(str(item) for item in value.values() if item)
    if value is None:
        return ""
    return str(value)


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _append_unique(target: List[Dict[str, Any]], item: Dict[str, Any]) -> None:
    question = item.get("question")
    if not question:
        return
    if any(existing.get("question") == question for existing in target):
        return
    target.append(item)


def build_hold_resolution_checklist_for_authoritative(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    decision = str(result.get("decision", "")).upper()
    if decision != "HOLD":
        return []

    key_facts = result.get("key_facts") or {}
    risks = result.get("bid_risk_and_compliance_exposure") or {}

    cyber_text = " ".join(
        [
            _flatten_text(key_facts.get("cyber")),
            _flatten_text(risks.get("cybersecurity")),
        ]
    )
    cert_text = " ".join(
        [
            _flatten_text(risks.get("certifications")),
            _flatten_text(risks.get("other")),
        ]
    )
    packaging_text = " ".join(
        [
            _flatten_text(risks.get("packaging")),
            _flatten_text(key_facts.get("packaging")),
        ]
    )
    fdt_text = " ".join(
        [
            _flatten_text(risks.get("FOB_FDT")),
            _flatten_text(key_facts.get("FDT")),
            _flatten_text(key_facts.get("FOB")),
        ]
    )
    hazmat_text = _flatten_text(risks.get("hazmat"))

    checklist: List[Dict[str, Any]] = []

    if _contains_any(
        cyber_text,
        ["sprs", "800-171", "nist", "7019", "7020", "7012"],
    ) or _flatten_text(key_facts.get("cyber")):
        _append_unique(
            checklist,
            {
                "id": "sprs_score",
                "question": "Do you currently have a valid NIST SP 800-171 assessment posted in SPRS?",
                "blocking": True,
                "clause": "DFARS 252.204-7019 / 7020",
            },
        )

    if _contains_any(cyber_text, ["cmmc", "level 2", "level ii", "rd004", "rd 004"]):
        _append_unique(
            checklist,
            {
                "id": "cmmc_l2",
                "question": "Have you completed a CMMC Level 2 self-assessment?",
                "blocking": True,
                "clause": "CMMC Level 2 / RD004",
            },
        )

    if _contains_any(cert_text, ["jcp", "export", "itar", "ear", "usml", "dfars 252.204-7008"]):
        _append_unique(
            checklist,
            {
                "id": "jcp",
                "question": "Is your organization JCP certified for export-controlled technical data?",
                "blocking": True,
                "clause": "ITAR / Export Control",
            },
        )

    if _contains_any(packaging_text, ["mil-std-129", "astm d3951", "rp001", "packaging"]):
        _append_unique(
            checklist,
            {
                "id": "packaging",
                "question": "Can your supplier comply with MIL-STD-129 and DLA packaging requirements?",
                "blocking": False,
            },
        )

    if _contains_any(
        fdt_text,
        ["fdt", "first destination transportation", "fob origin", "origin"],
    ):
        _append_unique(
            checklist,
            {
                "id": "fdt",
                "question": "Do you understand and have experience with FOB Origin under FDT?",
                "blocking": False,
            },
        )

    if _contains_any(hazmat_text, ["hazard", "sds", "msds"]):
        _append_unique(
            checklist,
            {
                "id": "hazmat",
                "question": "Can you provide SDS/MSDS documentation for hazardous material handling?",
                "blocking": False,
            },
        )

    return checklist


def build_hold_resolution_checklist_for_engine(
    decision_label: str, compliance_flags: Dict[str, Any]
) -> List[Dict[str, Any]]:
    if decision_label.upper() != "HOLD":
        return []

    checklist: List[Dict[str, Any]] = []

    if compliance_flags.get("cyber"):
        _append_unique(
            checklist,
            {
                "id": "sprs_score",
                "question": "Do you currently have a valid NIST SP 800-171 assessment posted in SPRS?",
                "blocking": True,
                "clause": "DFARS 252.204-7019 / 7020",
            },
        )
        _append_unique(
            checklist,
            {
                "id": "cmmc_l2",
                "question": "Have you completed a CMMC Level 2 self-assessment?",
                "blocking": True,
                "clause": "CMMC Level 2 / RD004",
            },
        )

    if compliance_flags.get("packaging"):
        _append_unique(
            checklist,
            {
                "id": "packaging",
                "question": "Can your supplier comply with MIL-STD-129 and DLA packaging requirements?",
                "blocking": False,
            },
        )

    if compliance_flags.get("fdt"):
        _append_unique(
            checklist,
            {
                "id": "fdt",
                "question": "Do you understand and have experience with FOB Origin under FDT?",
                "blocking": False,
            },
        )

    if compliance_flags.get("hazardous"):
        _append_unique(
            checklist,
            {
                "id": "hazmat",
                "question": "Can you provide SDS/MSDS documentation for hazardous material handling?",
                "blocking": False,
            },
        )

    return checklist
