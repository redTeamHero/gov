"""
Government Contracting Automation Agent for DLA / DIBBS simplified acquisitions.

This script ingests an RFQ PDF (or text file) and extracts key solicitation data,
performs price and compliance analysis, and emits a structured output aligned
with the required response format. Dependencies for PDF parsing are optional and
checked at runtime; if none are available, the tool will instruct the user to
install one (pypdf or pdfminer.six).
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from gov.decision import (
    build_decision_context,
    engine_result_from_analysis,
    merge_decision,
    run_authoritative_llm,
    run_llm_advisor,
)


# ------------------------ Data models ------------------------ #


@dataclass
class Snapshot:
    rfq_number: str = "Not stated in RFQ"
    rfq_id: str = "RFQ-UNKNOWN"
    rfq_id_confidence: str = "missing"
    nsn: str = "Not stated in RFQ"
    quantity: str = "Not stated in RFQ"
    delivery_requirement: str = "Not stated in RFQ"
    set_aside_status: str = "Not stated in RFQ"
    naics: str = "Not stated in RFQ"
    fob: str = "Not stated in RFQ"
    inspection_acceptance: str = "Not stated in RFQ"
    automated_award: str = "Not stated in RFQ"
    buyer_name: str = "Not stated in RFQ"
    buyer_email: str = "Not stated in RFQ"
    buyer_phone: str = "Not stated in RFQ"


@dataclass
class PriceIntelligence:
    historical_low: str = "Not stated in RFQ"
    historical_high: str = "Not stated in RFQ"
    most_recent_award: str = "Not stated in RFQ"
    recommended_bid_price: str = "Not enough data"
    history_prices: List[float] | None = None


@dataclass
class WinProbability:
    score: int
    rationale: str
    recommendation: str
    target_price_range: str


@dataclass
class ComplianceFlags:
    buy_american: bool = False
    berry_amendment: bool = False
    domestic_sourcing: bool = False
    additive_manufacturing_restriction: bool = False
    packaging: bool = False
    cyber: bool = False
    hazardous: bool = False
    fdt: bool = False


@dataclass
class AnalysisResult:
    snapshot: Snapshot
    compliance_flags: ComplianceFlags
    price_intelligence: PriceIntelligence
    win_probability: WinProbability
    required_actions: List[str]
    risks: List[str]
    templates: Dict[str, str]
    automation_fields: Dict[str, str]


# ------------------------ PDF/Text ingestion ------------------------ #


def extract_text_from_pdf(path: Path) -> str:
    """Extract text from a PDF using available optional dependencies."""
    try:
        import pypdf  # type: ignore

        reader = pypdf.PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ModuleNotFoundError:
        pass

    try:
        from pdfminer.high_level import extract_text  # type: ignore

        return extract_text(str(path))
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "No PDF parsing backend is available. Install either 'pypdf' or "
            "'pdfminer.six' (e.g., pip install pypdf) and retry."
        ) from exc


def read_input_text(source: Path) -> str:
    if source.suffix.lower() == ".pdf":
        return extract_text_from_pdf(source)
    return source.read_text(errors="ignore")


# ------------------------ Extraction helpers ------------------------ #


def _first_match(text: str, patterns: Sequence[str]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_request_number(text: str) -> Optional[str]:
    match = re.search(
        r"1\.?\s*REQUEST\s+NO\.?[:#\s]*([A-Z0-9-]+)",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip().strip(" .:-")
    return None


def _normalize_set_aside(raw_value: str, text: str) -> str:
    normalized = raw_value
    if re.search(r"cert\.?\s*for\s*nat\.?\s*def", text, re.IGNORECASE):
        normalized = "Full & Open (National Defense Priority)"
    elif re.search(r"full\s+and\s+open", text, re.IGNORECASE):
        normalized = "Full & Open"

    if re.search(r"HUBZone price (evaluation )?preference", text, re.IGNORECASE):
        suffix = " with HUBZone price preference"
        if normalized != "Not stated in RFQ" and suffix not in normalized:
            normalized = f"{normalized}{suffix}"
        elif normalized == "Not stated in RFQ":
            normalized = f"Full & Open{suffix}"

    return normalized


def _parse_clin_quantity(text: str) -> Optional[str]:
    def _scan_line_window() -> Optional[str]:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for idx, line in enumerate(lines):
            if re.search(r"\bCLIN\s+0*0*1\b", line, re.IGNORECASE) or re.search(
                r"\bPRLI\s+0*0*1\b", line, re.IGNORECASE
            ) or re.search(r"\bItem\s*0*0*1\b", line, re.IGNORECASE):
                window = " ".join(lines[idx : idx + 10])
                match = re.search(r"(?:QTY|QUANTITY)[:\s]+([0-9,]+)", window, re.IGNORECASE)
                if match:
                    return match.group(1)
        return None

    direct_match = _first_match(
        text,
        [
            r"CLIN\s+0*0*1[\s\S]{0,350}?(?:QTY|QUANTITY)[:\s]+([0-9,]+)",
            r"PRLI\s+0*0*1[\s\S]{0,350}?(?:QTY|QUANTITY)[:\s]+([0-9,]+)",
            r"Item\s*0001[\s\S]{0,350}?(?:QTY|QUANTITY)[:\s]+([0-9,]+)",
            r"\bQUANTITY[:\s]+([0-9,]+)\b",
        ],
    )

    return direct_match or _scan_line_window()


def _combine_delivery_fields(primary: str, need_ship: Optional[str], rdd: Optional[str]) -> str:
    parts = [primary] if primary != "Not stated in RFQ" else []
    if need_ship:
        parts.append(f"Need Ship Date: {need_ship}")
    if rdd:
        parts.append(f"Original RDD: {rdd}")
    return " | ".join(parts) if parts else "Not stated in RFQ"


def parse_snapshot(text: str) -> Snapshot:
    extracted_request_no = _extract_request_number(text)
    rfq_number = (
        extracted_request_no
        or _first_match(
            text,
            [
                r"(?:Solicitation|RFQ|Request for Quotation)[:#\s]+([A-Z0-9-]{5,})",
                r"\b(SPE\w+-\d{2}-[A-Z]-\d{4,})\b",
            ],
        )
        or "Not stated in RFQ"
    )
    if extracted_request_no:
        rfq_id_confidence = "extracted"
    elif rfq_number != "Not stated in RFQ":
        rfq_id_confidence = "inferred"
    else:
        rfq_id_confidence = "missing"
    rfq_id = rfq_number if rfq_number != "Not stated in RFQ" else "RFQ-UNKNOWN"

    nsn = _first_match(
        text,
        [
            r"\b(\d{4}-\d{2}-\d{3}-\d{4})\b",
            r"NSN[:#\s]+(\d{4}-\d{2}-\d{3}-\d{4})",
            r"\b(\d{13})\b",
        ],
    ) or "Not stated in RFQ"

    quantity = _parse_clin_quantity(text) or _first_match(
        text,
        [
            r"(?:Quantity|QTY)[:#\s]+([0-9,]+)\b",
            r"\bQTY\s+([0-9,]+)\s+(?:EA|Each|PG|KT|BX)\b",
        ],
    ) or "Not stated in RFQ"

    delivery_requirement_raw = _first_match(
        text,
        [
            r"Required Delivery(?: Date)?[:#\s]+([^\n]+)",
            r"Delivery\s+within\s+([^\n]+)",
            r"\b(\d{1,3}\s*days\s*(?:ARO|ADC|ADO))\b",
            r"Delivery\s+required[:\s]+(\d{1,3}\s*days\s*(?:ARO|ADC|ADO))",
        ],
    ) or "Not stated in RFQ"
    need_ship_date = _first_match(text, [r"Need Ship Date[:#\s]+([0-9/]{6,10})"])
    rdd = _first_match(text, [r"Original RDD[:#\s]+([0-9/]{6,10})"])
    delivery_requirement = _combine_delivery_fields(delivery_requirement_raw, need_ship_date, rdd)

    set_aside_status_raw = _first_match(
        text,
        [
            r"Set[- ]Aside[:#\s]+([^\n]+)",
            r"\b(Set ?Aside: ?(?:Small Business|Total SB|8\(a\)|SDVOSB|WOSB|HUBZone|Full and Open))",
        ],
    ) or "Not stated in RFQ"
    set_aside_status = _normalize_set_aside(set_aside_status_raw, text)

    naics = _first_match(text, [r"NAICS[:#\s]+(\d{5,6})"]) or "Not stated in RFQ"

    fob = (
        _first_match(text, [r"FOB[:#\s]+(Origin|Destination)", r"\bFOB\s+(Origin|Destination)\b"])
        or "Not stated in RFQ"
    )

    inspection_acceptance = _first_match(
        text,
        [
            r"Inspection/Acceptance[:#\s]+([^\n]+)",
            r"INSPECTION[:#\s]+([^\n]+)",
            r"INSP/ACCP[:#\s]+([^\n]+)",
        ],
    ) or "Not stated in RFQ"

    automated_award = (
        "Eligible" if re.search(r"automated award|auto[- ]award|fast pay", text, re.IGNORECASE) else "Not stated in RFQ"
    )

    buyer_email = _first_match(text, [r"([\w.-]+@[\w.-]+\.[A-Za-z]{2,})"]) or "Not stated in RFQ"
    buyer_phone = _first_match(
        text,
        [
            r"(\(?\d{3}\)?[-\s]\d{3}[-\s]\d{4})",
            r"(\d{3}[-\s]\d{4}\s+ext\.?\s*\d+)",
        ],
    ) or "Not stated in RFQ"

    buyer_name = _first_match(
        text,
        [
            r"Point of Contact[:#\s]+([^\n<]+)",
            r"Buyer[:#\s]+([^\n<]+)",
        ],
    ) or "Not stated in RFQ"

    return Snapshot(
        rfq_number=rfq_number,
        rfq_id=rfq_id,
        rfq_id_confidence=rfq_id_confidence,
        nsn=nsn,
        quantity=quantity,
        delivery_requirement=delivery_requirement,
        set_aside_status=set_aside_status,
        naics=naics,
        fob=fob,
        inspection_acceptance=inspection_acceptance,
        automated_award=automated_award,
        buyer_name=buyer_name,
        buyer_email=buyer_email,
        buyer_phone=buyer_phone,
    )


def parse_price_history(text: str, rfq_quantity: Optional[str] = None) -> PriceIntelligence:
    def _median(values: List[float]) -> float:
        sorted_vals = sorted(values)
        mid = len(sorted_vals) // 2
        if len(sorted_vals) % 2:
            return sorted_vals[mid]
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2

    def _extract_procurement_history(text_block: str) -> List[tuple[int, float]]:
        start = text_block.lower().find("procurement history")
        scoped = text_block[start : start + 3000] if start != -1 else text_block
        entries: List[tuple[int, float]] = []
        for line in scoped.splitlines():
            if not re.search(r"\d", line):
                continue
            for match in re.finditer(
                r"(?P<qty>\d{1,4})\s+[A-Z]*\s*\$?(?P<price>\d{1,3}\.\d{2})", line, flags=re.IGNORECASE
            ):
                qty = int(match.group("qty"))
                price = float(match.group("price"))
                if price <= 200:
                    entries.append((qty, price))
        return entries

    raw_prices: List[float] = []
    unit_price_candidates: List[float] = []
    structured_history = _extract_procurement_history(text)

    current_qty: Optional[int] = None
    try:
        if rfq_quantity:
            current_qty = int(rfq_quantity.replace(",", ""))
    except ValueError:
        current_qty = None

    if not structured_history:
        for match in re.finditer(
            r"(?P<qty>\d{1,4})\s*(?:EA|Each|PG|KT|BX)?[^\n]{0,25}?\$\s*(?P<amount>[0-9]{1,3}(?:\.\d{2})?)",
            text,
            flags=re.IGNORECASE,
        ):
            qty = int(match.group("qty"))
            amount = float(match.group("amount").replace(",", ""))
            if amount <= 200:
                raw_prices.append(amount)
                unit_price_candidates.append(amount)
            else:
                unit_estimate = amount / max(qty, 1)
                if unit_estimate <= 200:
                    unit_price_candidates.append(round(unit_estimate, 2))

        currency_only_matches = [
            float(p.replace(",", "")) for p in re.findall(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*\.\d{2})", text)
        ]
        for price in currency_only_matches:
            if price <= 200:
                raw_prices.append(price)
                unit_price_candidates.append(price)

        seen: set[float] = set()
        deduped_units: List[float] = []
        for price in unit_price_candidates:
            if price not in seen:
                deduped_units.append(price)
                seen.add(price)

        history = deduped_units or (raw_prices if raw_prices else None)
        history_quantities: Optional[List[tuple[int, float]]] = None
    else:
        history = [price for _, price in structured_history]
        history_quantities = structured_history

    historical_low = f"${min(history):,.2f}" if history else "Not stated in RFQ"
    historical_high = f"${max(history):,.2f}" if history else "Not stated in RFQ"
    most_recent_award = f"${history[-1]:,.2f}" if history else "Not stated in RFQ"

    recommended_bid_price = "Not enough data"
    if history:
        focus_prices: List[float]
        if history_quantities and current_qty is not None:
            sorted_by_proximity = sorted(history_quantities, key=lambda qp: abs(qp[0] - current_qty))
            focus = sorted_by_proximity[: max(3, min(5, len(sorted_by_proximity)))]
            focus_prices = [p for _, p in focus]
        else:
            focus_prices = history

        target = _median(focus_prices)
        band = 0.035
        low = round(target * (1 - band), 2)
        high = round(target * (1 + band), 2)
        recommended_bid_price = f"${low:,.2f} - ${high:,.2f}"
        if history:
            median_full = _median(history)
            if high > median_full * 1.25:
                recommended_bid_price += " (trimmed for historical alignment)"

    return PriceIntelligence(
        historical_low=historical_low,
        historical_high=historical_high,
        most_recent_award=most_recent_award,
        recommended_bid_price=recommended_bid_price,
        history_prices=history,
    )


def parse_compliance_flags(text: str) -> ComplianceFlags:
    return ComplianceFlags(
        buy_american=bool(re.search(r"Buy American|252\.225-700", text, re.IGNORECASE)),
        berry_amendment=bool(re.search(r"Berry Amendment|252\.225-7012|252\.225-7013", text, re.IGNORECASE)),
        domestic_sourcing=bool(re.search(r"domestic content|domestic source|US-made", text, re.IGNORECASE)),
        additive_manufacturing_restriction=bool(re.search(r"Additive Manufacturing|3D printing", text, re.IGNORECASE)),
        packaging=bool(re.search(r"MIL-STD-129|ASTM D3951|RP001", text, re.IGNORECASE)),
        cyber=bool(re.search(r"NIST SP 800-171|SPRS|252\.204-7012|252\.204-7020", text, re.IGNORECASE)),
        hazardous=bool(re.search(r"hazardous|MSDS|SDS", text, re.IGNORECASE)),
        fdt=bool(re.search(r"First Destination Transportation|FDT", text, re.IGNORECASE)),
    )


# ------------------------ Analysis logic ------------------------ #


def compute_viability(
    snapshot: Snapshot, price: PriceIntelligence, compliance: ComplianceFlags
) -> WinProbability:
    score = 60
    rationale_parts: List[str] = []

    if price.history_prices:
        spread = max(price.history_prices) - min(price.history_prices)
        if max(price.history_prices) > 0:
            volatility = spread / max(price.history_prices)
            if volatility < 0.2:
                score += 6
                rationale_parts.append("Stable historical pricing window.")
            elif volatility > 0.45:
                score -= 3
                rationale_parts.append("Pricing shows high volatility.")
        score += 4
        rationale_parts.append("Price history available for targeting.")
    else:
        rationale_parts.append("No price history found; more market research needed.")

    try:
        qty_value = int(snapshot.quantity.replace(",", ""))
        if qty_value <= 50:
            score += 4
            rationale_parts.append("Manageable quantity supports quick delivery.")
        elif qty_value >= 500:
            score -= 5
            rationale_parts.append("High quantity may stress supply chain.")
        else:
            score += 3
            rationale_parts.append("Known production lot size aligns with historical buys.")
    except ValueError:
        score -= 6
        rationale_parts.append("Quantity not explicit; probability reduced until parsed.")

    if compliance.cyber:
        score -= 7
        rationale_parts.append("Cyber clauses present; ensure SPRS/NIST readiness.")
    if compliance.buy_american or compliance.berry_amendment:
        score -= 5
        rationale_parts.append("Domestic sourcing requirements apply.")
    if compliance.packaging:
        score -= 3
        rationale_parts.append("Specific packaging standards called out.")
    if compliance.fdt:
        score -= 2
        rationale_parts.append("FDT applies; include transportation in price.")

    if snapshot.automated_award == "Eligible":
        score += 4
        rationale_parts.append("Eligible for automated award/fast pay.")

    score = max(0, min(100, score))

    if score >= 80:
        recommendation = "✅ Bid – High Confidence"
    elif score >= 65:
        recommendation = "✅ Bid – Moderate Competition"
    elif score >= 50:
        recommendation = "⚠️ Bid With Caution"
    else:
        recommendation = "❌ Skip"

    target_price_range = price.recommended_bid_price
    if target_price_range == "Not enough data" and price.history_prices:
        target = price.history_prices[-1]
        target_price_range = f"${target:,.2f} (match last known award)"

    rationale = " ".join(rationale_parts)
    return WinProbability(
        score=score,
        rationale=rationale,
        recommendation=recommendation,
        target_price_range=target_price_range,
    )


def build_required_actions(snapshot: Snapshot, compliance: ComplianceFlags) -> List[str]:
    actions = [
        "Confirm traceability to OEM or approved source if applicable.",
        "Verify ability to meet stated delivery requirement and update lead time assumptions.",
    ]
    if compliance.buy_american or compliance.berry_amendment or compliance.domestic_sourcing:
        actions.append("Confirm domestic content/Berry compliance with suppliers.")
    if compliance.packaging:
        actions.append("Validate packaging plan against MIL-STD-129 / ASTM D3951 / RP001 details.")
    if compliance.cyber:
        actions.append("Ensure current NIST SP 800-171 self-assessment is posted in SPRS.")
    if compliance.fdt:
        actions.append("Include FDT freight assumptions in pricing model.")
    if compliance.hazardous:
        actions.append("Collect and submit required SDS/MSDS documentation.")
    if snapshot.fob.lower() == "origin":
        actions.append("Confirm origin shipping point and estimate transportation costs.")
    return actions


def build_risks(compliance: ComplianceFlags) -> List[str]:
    risks = []
    if compliance.buy_american:
        risks.append("Buy American Act applies; foreign sourcing restricted.")
    if compliance.berry_amendment:
        risks.append("Berry Amendment triggers U.S. specialty metal/textile sourcing.")
    if compliance.additive_manufacturing_restriction:
        risks.append("Additive manufacturing prohibited or restricted.")
    if compliance.packaging:
        risks.append("Packaging must follow MIL-STD-129 / ASTM D3951 / RP001.")
    if compliance.cyber:
        risks.append("Cyber clauses (NIST SP 800-171 / SPRS) included.")
    if compliance.hazardous:
        risks.append("Hazardous material handling/SDS required.")
    if compliance.fdt:
        risks.append("First Destination Transportation impacts freight planning.")
    if not risks:
        risks.append("No special risks detected beyond standard FAR/DFARS terms.")
    return risks


def build_templates(snapshot: Snapshot) -> Dict[str, str]:
    rfq = snapshot.rfq_number
    buyer_name = snapshot.buyer_name if snapshot.buyer_name != "Not stated in RFQ" else "Buyer"

    buyer_question_email = (
        f"Subject: Clarification Request – RFQ {rfq}\n"
        f"Dear {buyer_name},\n\n"
        f"We are reviewing RFQ {rfq} and have a quick clarification request to ensure a responsive offer. "
        f"Could you please confirm: (1) Packaging standard and level (e.g., MIL-STD-129/ASTM D3951/RP001), "
        f"(2) Any approved sources or OEM part numbers tied to the NSN, and (3) Whether FDT applies to this buy? "
        f"We will incorporate your guidance and submit our quote promptly.\n\nThank you,\n[Your Name]\n[Company]"
    )

    traceability_request = (
        f"Hello Supplier,\n\nWe are preparing a quote for RFQ {rfq} and need full traceability. "
        f"Please provide current lead time, unit pricing (FOB as specified), and traceability to OEM/authorized distributor. "
        f"Include C of C details, shelf life (if applicable), and packaging compliance confirmation.\n\nThank you,\n[Your Name]"
    )

    post_award_checklist = (
        "Post-Award Readiness:\n"
        "- Confirm award quantity and delivery schedule.\n"
        "- Lock supplier PO with required domestic/traceability terms.\n"
        "- Validate packaging/labeling against MIL-STD-129 / ASTM D3951 / RP001.\n"
        "- Upload NIST SP 800-171 score to SPRS if required.\n"
        "- Align shipping plan with FOB/FDT instructions.\n"
        "- Prepare invoice and WAWF/iRAPT submission steps."
    )

    return {
        "buyer_question_email": buyer_question_email,
        "supplier_traceability_request": traceability_request,
        "post_award_readiness": post_award_checklist,
    }


# ------------------------ Formatting ------------------------ #


def format_output(result: AnalysisResult) -> str:
    snap = result.snapshot
    price = result.price_intelligence
    win = result.win_probability

    lines = [
        "🔹 RFQ Snapshot",
        f"RFQ Number: {snap.rfq_number}",
        f"NSN: {snap.nsn}",
        f"Quantity: {snap.quantity}",
        f"Delivery Requirement: {snap.delivery_requirement}",
        f"Set-Aside Status: {snap.set_aside_status}",
        f"NAICS: {snap.naics}",
        f"FOB: {snap.fob}",
        f"Inspection & Acceptance: {snap.inspection_acceptance}",
        f"Automated Award Eligibility: {snap.automated_award}",
        f"Buyer: {snap.buyer_name} | {snap.buyer_email} | {snap.buyer_phone}",
        "",
        "🔹 Price Intelligence",
        f"Historical Low: {price.historical_low}",
        f"Historical High: {price.historical_high}",
        f"Most Recent Award: {price.most_recent_award}",
        f"Recommended Bid Price: {price.recommended_bid_price}",
        "",
        "🔹 Win Probability",
        f"Score: {win.score}",
        f"Rationale: {win.rationale}",
        f"Recommendation: {win.recommendation}",
        f"Target Price Range: {win.target_price_range}",
        "",
        "🔹 Required Actions",
        *[f"- {action}" for action in result.required_actions],
        "",
        "🔹 Risks & Red Flags",
        *[f"- {risk}" for risk in result.risks],
        "",
        "🔹 Templates",
        "Buyer question email",
        result.templates["buyer_question_email"],
        "",
        "Supplier traceability request",
        result.templates["supplier_traceability_request"],
        "",
        "Post-award readiness checklist",
        result.templates["post_award_readiness"],
    ]

    return "\n".join(lines)


def format_advisor_output(advisor_result: Dict[str, Any]) -> str:
    merged_decision = advisor_result["final_decision"]
    llm_output = advisor_result["llm_output"]

    lines = [
        "🔹 LLM Advisor",
        f"Final Decision: {merged_decision['final_decision']}",
        f"Reason: {merged_decision.get('reason', 'No reason provided')}",
        "",
        "Advisor structured output (JSON):",
        json.dumps(llm_output, indent=2),
    ]

    return "\n".join(lines)


# ------------------------ Driver ------------------------ #


def analyze_text(text: str) -> AnalysisResult:
    snapshot = parse_snapshot(text)
    price_intel = parse_price_history(text, snapshot.quantity)
    compliance = parse_compliance_flags(text)
    win = compute_viability(snapshot, price_intel, compliance)
    actions = build_required_actions(snapshot, compliance)
    risks = build_risks(compliance)
    templates = build_templates(snapshot)

    automation_fields = {
        "rfq_number": snapshot.rfq_number,
        "nsn": snapshot.nsn,
        "quantity": snapshot.quantity,
        "delivery_requirement": snapshot.delivery_requirement,
        "set_aside_status": snapshot.set_aside_status,
        "naics": snapshot.naics,
        "buyer_email": snapshot.buyer_email,
        "target_price_range": win.target_price_range,
    }

    return AnalysisResult(
        snapshot=snapshot,
        compliance_flags=compliance,
        price_intelligence=price_intel,
        win_probability=win,
        required_actions=actions,
        risks=risks,
        templates=templates,
        automation_fields=automation_fields,
    )


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Analyze a DLA/DIBBS RFQ PDF and produce a bid roadmap.")
    parser.add_argument("file", type=Path, help="Path to the RFQ PDF or text file")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output JSON instead of formatted text")
    parser.add_argument(
        "--with-llm-advisor",
        dest="with_llm_advisor",
        action="store_true",
        help="Call the LLM advisor with the parsed decision context (requires OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--advisor-model",
        dest="advisor_model",
        default="gpt-4.1",
        help="Model name for the LLM advisor (default: gpt-4.1)",
    )
    parser.add_argument(
        "--authoritative-llm",
        dest="authoritative_llm",
        action="store_true",
        help="Route decision to authoritative LLM reading the raw PDF (requires OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--authoritative-model",
        dest="authoritative_model",
        default="gpt-4.1",
        help="Model name for the authoritative LLM (default: gpt-4.1)",
    )
    args = parser.parse_args(argv)

    if not args.file.exists():
        raise SystemExit(f"Input file not found: {args.file}")

    if args.authoritative_llm and args.with_llm_advisor:
        raise SystemExit("--authoritative-llm cannot be combined with --with-llm-advisor")

    if args.authoritative_llm:
        authoritative_result = run_authoritative_llm(args.file, model=args.authoritative_model)
        print(json.dumps(authoritative_result, indent=2))
        return

    text = read_input_text(args.file)
    result = analyze_text(text)

    advisor_payload: Optional[Dict[str, Any]] = None
    if args.with_llm_advisor:
        engine_result = engine_result_from_analysis(result)
        decision_context = build_decision_context(engine_result)
        llm_output = run_llm_advisor(decision_context, model=args.advisor_model)
        merged_decision = merge_decision(engine_result, llm_output)
        advisor_payload = {
            "decision_context": decision_context,
            "llm_output": llm_output,
            "final_decision": merged_decision,
        }

    if args.as_json:
        output = {
            "snapshot": asdict(result.snapshot),
            "compliance_flags": asdict(result.compliance_flags),
            "price_intelligence": asdict(result.price_intelligence),
            "win_probability": asdict(result.win_probability),
            "required_actions": result.required_actions,
            "risks": result.risks,
            "templates": result.templates,
            "automation_fields": result.automation_fields,
        }
        if advisor_payload:
            output["llm_advisor"] = advisor_payload
        print(json.dumps(output, indent=2))
    else:
        print(format_output(result))
        if advisor_payload:
            print()
            print(format_advisor_output(advisor_payload))


if __name__ == "__main__":
    main()
