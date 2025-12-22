"""Traceability PDF generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from gov.documents.base import create_canvas, ensure_output_dir, line_writer
from gov.documents.errors import PDFGenerationError
from gov.documents.rfq_normalize import normalize_rfq_for_docs
from gov.documents.rfq_schema import resolve_rfq_id


CHAIN_OF_CUSTODY_TEXT = (
    "Chain of Custody: Supplier certifies the items provided are sourced from "
    "authorized channels and handled in accordance with contractual requirements."
)


def generate_traceability_pdf(rfq: Dict[str, Any], supplier: Dict[str, Any]) -> str:
    """Generate a traceability PDF and return its file path."""
    try:
        rfq = normalize_rfq_for_docs(rfq)
        rfq_id = resolve_rfq_id(rfq)
        output_path = _traceability_output_path(rfq_id)

        pdf_canvas = create_canvas(output_path)
        write_line = line_writer(pdf_canvas)

        write_line("TRACEABILITY CERTIFICATION")
        write_line(f"RFQ NUMBER: {rfq_id}")
        write_line(f"NSN: {rfq.get('nsn', 'UNKNOWN')}")
        write_line(f"MANUFACTURER: {supplier.get('manufacturer_name', 'UNKNOWN')}")
        distributor_name = supplier.get("distributor_name") or supplier.get("distributor")
        if distributor_name:
            write_line(f"DISTRIBUTOR: {distributor_name}")
        write_line(f"SUPPLIER: {supplier.get('company_name', 'UNKNOWN')}")
        write_line(CHAIN_OF_CUSTODY_TEXT)
        write_line("SIGNATURE: ______________________________")

        pdf_canvas.showPage()
        pdf_canvas.save()
        return str(output_path)
    except (KeyError, OSError) as exc:
        raise PDFGenerationError(str(exc)) from exc


def _traceability_output_path(rfq_id: str) -> Path:
    output_dir = ensure_output_dir("traceability")
    return output_dir / f"{rfq_id}.pdf"
