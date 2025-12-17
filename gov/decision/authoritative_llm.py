from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

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

Output JSON only.
You MUST respond in valid JSON ONLY. Do not include explanations or markdown.
"""

AUTHORITATIVE_USER_PROMPT = """
Analyze the attached RFQ PDF.

Your tasks:
1. Extract key facts (quantity, FOB, FDT, packaging, cyber, delivery).
2. Assess bid risk and compliance exposure.
3. Decide one: BID, HOLD, or SKIP.
4. Explain your decision like a government contracts manager.
"""


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
        uploaded_file = client.files.create(file=pdf_file, purpose="assistants")

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
        return json.loads(content_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Authoritative LLM did not return valid JSON.") from exc
