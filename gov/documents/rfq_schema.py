"""RFQ schema helpers for document generation."""

from __future__ import annotations

import logging


RFQ_ID_KEYS = (
    "rfq_id",
    "rfq_number",
    "solicitation_number",
    "solicitation",
    "document_id",
)

_LOGGER = logging.getLogger(__name__)


def resolve_rfq_id(rfq: dict) -> str:
    """Resolve the RFQ identifier from known schema keys.

    Args:
        rfq: RFQ payload to inspect.

    Returns:
        The resolved RFQ identifier as a string.
    """
    for key in RFQ_ID_KEYS:
        if key in rfq:
            value = rfq.get(key)
            if value not in (None, ""):
                return str(value)
    _LOGGER.warning(
        "RFQ identifier not found in payload. Falling back to RFQ-UNKNOWN.",
        extra={"rfq_keys": sorted(rfq.keys())},
    )
    return "RFQ-UNKNOWN"
