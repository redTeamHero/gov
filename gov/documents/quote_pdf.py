"""Quote PDF generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from gov.documents.base import create_canvas, ensure_output_dir, line_writer
from gov.documents.errors import PDFGenerationError
from gov.documents.rfq_normalize import normalize_rfq_for_docs
from gov.documents.rfq_schema import resolve_rfq_id


def _parse_money(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                return default
    return default


def _build_pricing_payload(rfq: Dict[str, Any], pricing: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "quantity": pricing.get("quantity", rfq.get("quantity", 1)),
        "unit_price": _parse_money(pricing.get("unit_price")),
        "total_price": _parse_money(pricing.get("total_price")),
        "delivery_days": pricing.get("delivery_days", pricing.get("days_aro", 0)),
    }


def generate_quote_pdf(rfq: Dict[str, Any], supplier: Dict[str, Any], pricing: Dict[str, Any]) -> str:
    """Generate a quote PDF and return its file path."""
    try:
        rfq = normalize_rfq_for_docs(rfq)
        rfq_id = resolve_rfq_id(rfq)
        output_path = _quote_output_path(rfq_id)
        pricing_payload = _build_pricing_payload(rfq, pricing)

        pdf_canvas = create_canvas(output_path)
        write_line = line_writer(pdf_canvas)

        write_line(f"RFQ NUMBER: {rfq_id}")
        write_line(f"NSN: {rfq.get('nsn', 'UNKNOWN')}")
        write_line(f"QUANTITY: {pricing_payload['quantity']}")
        write_line(f"UNIT PRICE: ${pricing_payload['unit_price']:.2f}")
        write_line(f"TOTAL PRICE: ${pricing_payload['total_price']:.2f}")
        write_line(f"DELIVERY: {pricing_payload['delivery_days']} days ARO")
        write_line(f"SUPPLIER: {supplier.get('company_name', 'UNKNOWN')}")

        pdf_canvas.showPage()
        pdf_canvas.save()
        return str(output_path)
    except (KeyError, OSError) as exc:
        raise PDFGenerationError(str(exc)) from exc


def _quote_output_path(rfq_id: str) -> Path:
    output_dir = ensure_output_dir("quotes")
    return output_dir / f"{rfq_id}.pdf"
