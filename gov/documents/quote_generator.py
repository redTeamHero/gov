from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_BASE = PROJECT_ROOT / "output"


def _ensure_dirs():
    (OUTPUT_BASE / "quotes").mkdir(parents=True, exist_ok=True)
    (OUTPUT_BASE / "traceability").mkdir(parents=True, exist_ok=True)


def generate_quote_pdf(rfq, supplier, pricing):
    _ensure_dirs()

    rfq_id = rfq["rfq_number"]
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

    rfq_id = rfq["rfq_number"]
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


def generate_documents(rfq, supplier, pricing):
    quote_path = generate_quote_pdf(rfq, supplier, pricing)
    traceability_path = generate_traceability_pdf(rfq, supplier)
    return {
        "quote_pdf": quote_path,
        "traceability_pdf": traceability_path,
    }


__all__ = ["generate_quote_pdf", "generate_traceability_pdf", "generate_documents"]
