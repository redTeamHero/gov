from gov.documents.quote_pdf import generate_quote_pdf as _generate_quote_pdf
from gov.documents.rfq_schema import resolve_rfq_id
from gov.documents.traceability_pdf import (
    generate_traceability_pdf as _generate_traceability_pdf,
)


def generate_documents(rfq, supplier, pricing):
    return {
        "quote_pdf": _generate_quote_pdf(rfq, supplier, pricing),
        "traceability_pdf": _generate_traceability_pdf(rfq, supplier),
    }


def generate_quote_pdf(rfq, supplier, pricing):
    return _generate_quote_pdf(rfq, supplier, pricing)

def generate_traceability_pdf(rfq, supplier):
    return _generate_traceability_pdf(rfq, supplier)


def _resolve_rfq_id(rfq):
    return resolve_rfq_id(rfq)
