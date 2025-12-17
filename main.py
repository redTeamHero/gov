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
from typing import Dict, List, Optional, Sequence


# ------------------------ Data models ------------------------ #


@dataclass
class Snapshot:
    rfq_number: str = "Not stated in RFQ"
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


def parse_snapshot(text: str) -> Snapshot:
    rfq_number = _first_match(
        text,
        [
            r"(?:Solicitation|RFQ|Request for Quotation)[:#\s]+([A-Z0-9-]{5,})",
            r"\b(SPE\w+-\d{2}-[A-Z]-\d{4,})\b",
        ],
    ) or "Not stated in RFQ"

    nsn = _first_match(
        text,
        [
            r"\b(\d{4}-\d{2}-\d{3}-\d{4})\b",
            r"NSN[:#\s]+(\d{4}-\d{2}-\d{3}-\d{4})",
            r"\b(\d{13})\b",
        ],
    ) or "Not stated in RFQ"

    quantity = _first_match(
        text,
        [
            r"(?:Quantity|QTY)[:#\s]+([0-9,]+)\b",
            r"\bQTY\s+([0-9,]+)\s+(?:EA|Each|PG|KT|BX)\b",
        ],
    ) or "Not stated in RFQ"

    delivery_requirement = _first_match(
        text,
        [
            r"Required Delivery(?: Date)?[:#\s]+([^\n]+)",
            r"Delivery\s+within\s+([^\n]+)",
            r"\b(\d{1,3}\s*days\s*(?:ARO|ADC|ADO))\b",
        ],
    ) or "Not stated in RFQ"

    set_aside_status = _first_match(
        text,
        [
            r"Set[- ]Aside[:#\s]+([^\n]+)",
            r"\b(Set ?Aside: ?(?:Small Business|Total SB|8\(a\)|SDVOSB|WOSB|HUBZone|Full and Open))",
        ],
    ) or "Not stated in RFQ"

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


def parse_price_history(text: str) -> PriceIntelligence:
    price_matches = re.findall(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.\d{2})?)", text)
    prices = [float(p.replace(",", "")) for p in price_matches]

    historical_low: str = "Not stated in RFQ"
    historical_high: str = "Not stated in RFQ"
    most_recent_award: str = "Not stated in RFQ"

    if prices:
        historical_low = f"${min(prices):,.2f}"
        historical_high = f"${max(prices):,.2f}"
        most_recent_award = f"${prices[-1]:,.2f}"

    recommended_bid_price = "Not enough data"
    if prices:
        target = prices[-1]
        low = round(target * 0.97, 2)
        high = round(target * 1.01, 2)
        recommended_bid_price = f"${low:,.2f} - ${high:,.2f}"

    return PriceIntelligence(
        historical_low=historical_low,
        historical_high=historical_high,
        most_recent_award=most_recent_award,
        recommended_bid_price=recommended_bid_price,
        history_prices=prices or None,
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
            if volatility < 0.15:
                score += 8
                rationale_parts.append("Stable historical pricing window.")
            elif volatility > 0.35:
                score -= 5
                rationale_parts.append("Pricing shows high volatility.")
        score += 5
        rationale_parts.append("Price history available for targeting.")
    else:
        rationale_parts.append("No price history found; more market research needed.")

    try:
        qty_value = int(snapshot.quantity.replace(",", ""))
        if qty_value <= 50:
            score += 5
            rationale_parts.append("Manageable quantity supports quick delivery.")
        elif qty_value >= 500:
            score -= 5
            rationale_parts.append("High quantity may stress supply chain.")
    except ValueError:
        rationale_parts.append("Quantity not explicit.")

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
        score += 5
        rationale_parts.append("Eligible for automated award/fast pay.")

    score = max(0, min(100, score))

    if score >= 75:
        recommendation = "✅ Bid"
    elif score >= 55:
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


# ------------------------ Driver ------------------------ #


def analyze_text(text: str) -> AnalysisResult:
    snapshot = parse_snapshot(text)
    price_intel = parse_price_history(text)
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
    args = parser.parse_args(argv)

    if not args.file.exists():
        raise SystemExit(f"Input file not found: {args.file}")

    text = read_input_text(args.file)
    result = analyze_text(text)

    if args.as_json:
        output = {
            "snapshot": asdict(result.snapshot),
            "price_intelligence": asdict(result.price_intelligence),
            "win_probability": asdict(result.win_probability),
            "required_actions": result.required_actions,
            "risks": result.risks,
            "templates": result.templates,
            "automation_fields": result.automation_fields,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_output(result))


if __name__ == "__main__":
    main()
