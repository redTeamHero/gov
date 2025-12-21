from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_BASE = PROJECT_ROOT / "output"


def _ensure_dirs():
    (OUTPUT_BASE / "quotes").mkdir(parents=True, exist_ok=True)
    (OUTPUT_BASE / "traceability").mkdir(parents=True, exist_ok=True)


def _resolve_rfq_id(rfq):
    """
    Deterministically resolve RFQ identifier from parsed RFQ payload.
    Raises KeyError if not found (auditable failure).
    """
    for key in (
        "rfq_number",
        "rfq_id",
        "solicitation_number",
        "solicitation",
        "document_id",
    ):
        if key in rfq and rfq[key]:
            return str(rfq[key])

    raise KeyError(
        "RFQ identifier not found. Expected one of: "
        "rfq_number, rfq_id, solicitation_number, solicitation, document_id"
    )


def _parse_money(value, default=0.0):
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


def generate_documents(rfq, supplier, pricing):
    pricing_payload = {
        "quantity": pricing.get("quantity", rfq.get("quantity", 1)),
        "unit_price": _parse_money(pricing.get("unit_price")),
        "total_price": _parse_money(pricing.get("total_price")),
        "delivery_days": pricing.get("delivery_days", pricing.get("days_aro", 0)),
    }

    return {
        "quote_pdf": generate_quote_pdf(rfq, supplier, pricing_payload),
        "traceability_pdf": generate_traceability_pdf(rfq, supplier),
    }


def generate_quote_pdf(rfq, supplier, pricing):
    _ensure_dirs()

    rfq_id = _resolve_rfq_id(rfq)
    output_path = OUTPUT_BASE / "quotes" / f"{rfq_id}.pdf"

    c = canvas.Canvas(str(output_path), pagesize=LETTER)
    width, height = LETTER
    y = height - 40

    def line(text):
        nonlocal y
        c.drawString(40, y, text)
        y -= 14

    line(f"RFQ NUMBER: {rfq_id}")
    line(f"NSN: {rfq['nsn']}")
    line(f"QUANTITY: {pricing['quantity']}")
    line(f"UNIT PRICE: ${pricing['unit_price']:.2f}")
    line(f"TOTAL PRICE: ${pricing['total_price']:.2f}")
    line(f"DELIVERY: {pricing['delivery_days']} days ARO")
    line(f"SUPPLIER: {supplier['company_name']}")

    c.showPage()
    c.save()
    return str(output_path)


def generate_traceability_pdf(rfq, supplier):
    _ensure_dirs()

    rfq_id = _resolve_rfq_id(rfq)
    output_path = OUTPUT_BASE / "traceability" / f"{rfq_id}.pdf"

    c = canvas.Canvas(str(output_path), pagesize=LETTER)
    width, height = LETTER
    y = height - 40

    def line(text):
        nonlocal y
        c.drawString(40, y, text)
        y -= 14

    line("TRACEABILITY CERTIFICATION")
    line(f"RFQ NUMBER: {rfq_id}")
    line(f"NSN: {rfq['nsn']}")
    line(f"MANUFACTURER: {supplier.get('manufacturer_name', 'UNKNOWN')}")
    line(f"SUPPLIER: {supplier['company_name']}")

    c.showPage()
    c.save()
    return str(output_path)
