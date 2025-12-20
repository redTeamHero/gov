"""Generate quote and traceability PDFs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from reportlab import rl_config
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

rl_config.invariant = 1


def _string_or_default(value: Any, default: str = "Not provided") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _get_rfq_value(rfq: Dict[str, Any], key: str, default: str = "Not provided") -> str:
    for section_key in ["snapshot", "key_facts", "requirements", "compliance"]:
        section = rfq.get(section_key)
        if isinstance(section, dict) and key in section:
            return _string_or_default(section.get(key), default)
    return _string_or_default(rfq.get(key), default)


def _get_pricing_value(pricing: Dict[str, Any], key: str, default: str = "Not provided") -> str:
    return _string_or_default(pricing.get(key), default)


def _compliance_statement(rfq: Dict[str, Any]) -> str:
    statements: List[str] = ["Supplier certifies conformance to RFQ requirements as stated."]
    if _string_or_default(_get_rfq_value(rfq, "qpl_required"), "").lower() in {"yes", "true", "required"}:
        statements.append("QPL/QML approval is required for award.")
    if _string_or_default(_get_rfq_value(rfq, "coqc_required"), "").lower() in {"yes", "true", "required"}:
        statements.append("COQC documentation will be provided upon shipment.")
    return " ".join(statements)


def _write_lines(pdf: canvas.Canvas, start_x: int, start_y: int, lines: List[str], leading: int = 14) -> int:
    current_y = start_y
    for line in lines:
        pdf.drawString(start_x, current_y, line)
        current_y -= leading
    return current_y


def generate_quote_pdf(
    rfq: Dict[str, Any],
    supplier: Dict[str, Any],
    pricing: Dict[str, Any],
    output_dir: Path | str = "/output/quotes",
) -> Path:
    """Generate a quote PDF and return the output path."""
    rfq_number = _get_rfq_value(rfq, "rfq_number", "RFQ")
    output_path = Path(output_dir) / f"{rfq_number}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=LETTER)
    pdf.setTitle(f"Quote {rfq_number}")
    pdf.setAuthor(_string_or_default(supplier.get("company_name"), "Supplier"))

    lines = [
        f"Quote for RFQ: {rfq_number}",
        f"NSN: {_get_rfq_value(rfq, 'nsn')}",
        f"Part Number: {_get_rfq_value(rfq, 'part_number')}",
        f"Item Name: {_get_rfq_value(rfq, 'item_name')}",
        f"Quantity: {_get_rfq_value(rfq, 'quantity')}",
        f"Unit Price: {_get_pricing_value(pricing, 'unit_price')}",
        f"Total Price: {_get_pricing_value(pricing, 'total_price')}",
        f"Delivery Terms: FOB {_get_pricing_value(pricing, 'fob')} / {_get_pricing_value(pricing, 'days_aro')} days ARO",
        f"Compliance: {_compliance_statement(rfq)}",
        "",
        "Company Information:",
        f"{_string_or_default(supplier.get('company_name'))}",
        f"CAGE: {_string_or_default(supplier.get('cage'))}",
        f"{_string_or_default(supplier.get('address'))}",
        f"Phone: {_string_or_default(supplier.get('phone'))}",
        f"Email: {_string_or_default(supplier.get('email'))}",
    ]

    pdf.setFont("Helvetica", 12)
    _write_lines(pdf, 50, 750, lines)
    pdf.showPage()
    pdf.save()

    return output_path


def generate_traceability_pdf(
    rfq: Dict[str, Any],
    supplier: Dict[str, Any],
    output_dir: Path | str = "/output/traceability",
) -> Path:
    """Generate a traceability letter PDF and return the output path."""
    rfq_number = _get_rfq_value(rfq, "rfq_number", "RFQ")
    output_path = Path(output_dir) / f"{rfq_number}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(output_path), pagesize=LETTER)
    pdf.setTitle(f"Traceability Letter {rfq_number}")
    pdf.setAuthor(_string_or_default(supplier.get("company_name"), "Supplier"))

    manufacturer = _string_or_default(supplier.get("manufacturer_name"))
    distributor = _string_or_default(supplier.get("distributor_name"), "Not applicable")

    lines = [
        f"Traceability Letter for RFQ: {rfq_number}",
        f"Manufacturer: {manufacturer}",
        f"Distributor: {distributor}",
        f"Supplier: {_string_or_default(supplier.get('company_name'))}",
        f"NSN: {_get_rfq_value(rfq, 'nsn')}",
        f"Part Number: {_get_rfq_value(rfq, 'part_number')}",
        "",
        "Chain-of-custody statement:",
        "Items will be sourced from the manufacturer listed above and traceability will be maintained",
        "through delivery to the Government.",
        "",
        "Signature: ________________________________",
        "Date: ________________________________",
    ]

    pdf.setFont("Helvetica", 12)
    _write_lines(pdf, 50, 750, lines)
    pdf.showPage()
    pdf.save()

    return output_path


def generate_documents(
    rfq: Dict[str, Any],
    supplier: Dict[str, Any],
    pricing: Dict[str, Any],
) -> Dict[str, str]:
    """Generate both quote and traceability PDFs and return their paths."""
    quote_path = generate_quote_pdf(rfq, supplier, pricing)
    traceability_path = generate_traceability_pdf(rfq, supplier)
    return {
        "quote_pdf": str(quote_path),
        "traceability_pdf": str(traceability_path),
    }
