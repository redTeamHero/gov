"""Normalize RFQ payloads for document generation."""

from __future__ import annotations

from typing import Any, Dict


def normalize_rfq_for_docs(rfq: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(rfq)
    kf = rfq.get("key_facts") or {}

    out["rfq_number"] = rfq.get("rfq_number") or kf.get("rfq_number") or kf.get("request_no") or "RFQ-UNKNOWN"
    out["rfq_id"] = rfq.get("rfq_id") or out["rfq_number"]

    out["nsn"] = rfq.get("nsn") or kf.get("nsn") or "UNKNOWN"
    out["quantity"] = rfq.get("quantity") or kf.get("quantity") or 1
    out["delivery"] = rfq.get("delivery") or kf.get("delivery") or "0 days ARO"

    return out
