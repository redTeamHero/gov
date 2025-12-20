"""Unit-test stubs for quote generation."""

from gov.documents.quote_generator import generate_documents


def test_generate_documents_stub(tmp_path) -> None:
    """Stub test to illustrate document generation entry point."""
    rfq = {"rfq_number": "RFQ-TEST", "nsn": "0000-00-000-0000"}
    supplier = {"company_name": "Example Supplier"}
    pricing = {"unit_price": "$1.00", "total_price": "$1.00", "fob": "Origin", "days_aro": 1}

    output = generate_documents(rfq, supplier, pricing)
    assert "quote_pdf" in output
    assert "traceability_pdf" in output
