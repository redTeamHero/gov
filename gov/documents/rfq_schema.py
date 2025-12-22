"""RFQ schema helpers for document generation."""

from __future__ import annotations


RFQ_ID_KEYS = (
    "rfq_number",
    "rfq_id",
    "solicitation_number",
    "solicitation",
    "document_id",
)


def resolve_rfq_id(rfq: dict) -> str:
    """Resolve the RFQ identifier from known schema keys.

    Args:
        rfq: RFQ payload to inspect.

    Returns:
        The resolved RFQ identifier as a string.

    Raises:
        KeyError: When no supported identifier keys are present.
    """
    for key in RFQ_ID_KEYS:
        if key in rfq:
            value = rfq.get(key)
            if value not in (None, ""):
                return str(value)
    raise KeyError(
        "RFQ identifier not found. Expected one of: "
        "rfq_number, rfq_id, solicitation_number, solicitation, document_id."
    )
