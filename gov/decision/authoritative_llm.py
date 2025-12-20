from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from gov.decision.hold_resolution import build_hold_resolution_checklist_for_authoritative
AUTHORITATIVE_SYSTEM_PROMPT = """
You are a senior U.S. government contracts analyst.

You are authorized to:
- Read and interpret raw RFQ PDFs
- Extract quantities, delivery terms, packaging, cyber clauses
- Assess bid viability
- Decide BID, HOLD, or SKIP

You must:
- Base decisions ONLY on the PDF content
- Cite page numbers when possible
- Flag uncertainty explicitly
- Be conservative with compliance risks

Strict JSON rules (no markdown, no truncation):
- Return JSON ONLY in the following structure, with every field populated or explicitly "Not stated in RFQ":
{
  "key_facts": {
    "rfq_number": "",
    "nsn": "",
    "item_description": "",
    "quantity": "",
    "unit_of_issue": "",
    "FOB": "",
    "FDT": "",
    "delivery": "",
    "need_ship_date": "",
    "inspection_acceptance": "",
    "packaging": {
      "hazardous": "",
      "non_hazardous": "",
      "marking": "",
      "palletization": "",
      "other": ""
    },
    "cyber": [],
    "domestic_sourcing": "",
    "additive_manufacturing": "",
    "priority_rating": "",
    "automated_award": "",
    "approved_sources": [],
    "destination_address": "",
    "set_aside": "",
    "NAICS": "",
    "close_date": ""
  },
  "bid_risk_and_compliance_exposure": {
    "cybersecurity": "",
    "packaging": "",
    "FOB_FDT": "",
    "inspection": "",
    "domestic_sourcing": "",
    "hazmat": "",
    "schedule": "",
    "certifications": "",
    "other": ""
  },
  "decision": "BID | HOLD | SKIP",
  "manager_explanation": ""
}

- For EVERY field above: provide the extracted value with page reference when possible OR "Not stated in RFQ".
- Never omit a field. Never leave a value blank. Never truncate values before the JSON is returned.
"""

AUTHORITATIVE_USER_PROMPT = """
Analyze the attached RFQ PDF and return only JSON.

Your tasks:
1. Extract key facts (quantity, FOB, FDT, packaging subfields, cyber, delivery, set-aside, NAICS, approved sources, automation eligibility, priority rating, destination address, close date).
2. Assess bid risk and compliance exposure (separate fields for cyber, packaging, FOB/FDT, inspection, domestic sourcing, hazmat, schedule, certifications, other).
3. Decide one: BID, HOLD, or SKIP.
4. Explain your decision like a government contracts manager in the manager_explanation field.

Reminder: If a value is not available, return "Not stated in RFQ". Do not truncate any JSON values.
"""

DEFAULT_PACKAGING = {
    "hazardous": "Not stated in RFQ",
    "non_hazardous": "Not stated in RFQ",
    "marking": "Not stated in RFQ",
    "palletization": "Not stated in RFQ",
    "other": "Not stated in RFQ",
}

DEFAULT_KEY_FACTS = {
    "rfq_number": "Not stated in RFQ",
    "nsn": "Not stated in RFQ",
    "item_description": "Not stated in RFQ",
    "quantity": "Not stated in RFQ",
    "unit_of_issue": "Not stated in RFQ",
    "FOB": "Not stated in RFQ",
    "FDT": "Not stated in RFQ",
    "delivery": "Not stated in RFQ",
    "need_ship_date": "Not stated in RFQ",
    "inspection_acceptance": "Not stated in RFQ",
    "packaging": DEFAULT_PACKAGING,
    "cyber": [],
    "domestic_sourcing": "Not stated in RFQ",
    "additive_manufacturing": "Not stated in RFQ",
    "priority_rating": "Not stated in RFQ",
    "automated_award": "Not stated in RFQ",
    "approved_sources": [],
    "destination_address": "Not stated in RFQ",
    "set_aside": "Not stated in RFQ",
    "NAICS": "Not stated in RFQ",
    "close_date": "Not stated in RFQ",
}

DEFAULT_RISK_EXPOSURE = {
    "cybersecurity": "Not stated in RFQ",
    "packaging": "Not stated in RFQ",
    "FOB_FDT": "Not stated in RFQ",
    "inspection": "Not stated in RFQ",
    "domestic_sourcing": "Not stated in RFQ",
    "hazmat": "Not stated in RFQ",
    "schedule": "Not stated in RFQ",
    "certifications": "Not stated in RFQ",
    "other": "Not stated in RFQ",
}


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    output: List[Any] | None = getattr(response, "output", None)
    if output:
        for item in output:
            content_items: List[Any] | None = getattr(item, "content", None)
            if not content_items:
                continue
            for content in content_items:
                text_value = getattr(content, "text", None)
                if text_value:
                    return text_value

    raise RuntimeError("Authoritative LLM returned no content to parse.")


def _normalize_packaging(packaging: Any) -> Dict[str, str]:
    merged = DEFAULT_PACKAGING.copy()
    if isinstance(packaging, dict):
        for key in merged:
            value = packaging.get(key)
            merged[key] = str(value) if value else merged[key]
    elif packaging:
        merged["other"] = str(packaging)
    return merged


def _ensure_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def _apply_schema_defaults(raw: Dict[str, Any]) -> Dict[str, Any]:
    key_facts_raw = raw.get("key_facts") if isinstance(raw.get("key_facts"), dict) else {}
    key_facts: Dict[str, Any] = {}
    for field, default in DEFAULT_KEY_FACTS.items():
        if field == "packaging":
            key_facts[field] = _normalize_packaging(key_facts_raw.get(field))
        elif field in ("cyber", "approved_sources"):
            key_facts[field] = _ensure_list(key_facts_raw.get(field))
        else:
            value = key_facts_raw.get(field) if isinstance(key_facts_raw, dict) else None
            key_facts[field] = str(value) if value else default

    risk_raw = raw.get("bid_risk_and_compliance_exposure") if isinstance(
        raw.get("bid_risk_and_compliance_exposure"), dict
    ) else {}
    risks: Dict[str, Any] = {}
    for field, default in DEFAULT_RISK_EXPOSURE.items():
        value = risk_raw.get(field) if isinstance(risk_raw, dict) else None
        risks[field] = str(value) if value else default

    normalized = {
        "key_facts": key_facts,
        "bid_risk_and_compliance_exposure": risks,
        "decision": str(raw.get("decision")) if raw.get("decision") else "Not stated in RFQ",
        "manager_explanation": str(raw.get("manager_explanation"))
        if raw.get("manager_explanation")
        else "Not stated in RFQ",
    }
    return normalized


def _upload_with_retry(client: Any, pdf_file: Any, retries: int = 3, backoff: int = 2) -> Any:
    from openai import InternalServerError

    for attempt in range(retries):
        try:
            pdf_file.seek(0)
            return client.files.create(file=pdf_file, purpose="assistants")
        except InternalServerError:
            if attempt == retries - 1:
                raise
            time.sleep(backoff**attempt)


def run_authoritative_llm(pdf_path: Path, model: str = "gpt-4.1") -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required to run the authoritative LLM mode.")

    if not pdf_path.exists():
        raise FileNotFoundError(f"Input file not found: {pdf_path}")

    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError("Authoritative mode requires a PDF input.")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    with pdf_path.open("rb") as pdf_file:
        uploaded_file = _upload_with_retry(client, pdf_file)

    response = client.responses.create(
        model=model,
        temperature=0,
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": AUTHORITATIVE_SYSTEM_PROMPT.strip()}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": AUTHORITATIVE_USER_PROMPT.strip()},
                    {"type": "input_file", "file_id": uploaded_file.id},
                ],
            },
        ],
    )

    content_text = _extract_response_text(response)
    try:
        parsed = json.loads(content_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Authoritative LLM did not return valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError("Authoritative LLM did not return a JSON object.")

    normalized = _apply_schema_defaults(parsed)
    checklist = build_hold_resolution_checklist_for_authoritative(normalized)
    if checklist:
        normalized["hold_resolution_checklist"] = checklist
        normalized["hold_resolution_rule"] = (
            "Answer YES to all blocking items to upgrade HOLD to BID (Conditional)."
        )
    return normalized
