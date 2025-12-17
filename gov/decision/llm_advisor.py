from __future__ import annotations

import json
import os
from typing import Any, Dict

SYSTEM_PROMPT = """
You are a government contracting analyst assisting a deterministic pricing engine.

Rules you must follow:
- You do NOT invent facts.
- You do NOT guess quantities or prices.
- You do NOT override compliance blockers.
- You do NOT change pricing calculations.
- If required information is missing but historical clustering exists, recommend HOLD.
- You explain decisions using DLA / DIBBS / FAR logic.
- Output JSON ONLY. No prose outside JSON.
- You never parse PDFs. You only reason over provided structured context.
"""

USER_PROMPT_TEMPLATE = """
Analyze the following RFQ decision context.

Your task:
1. Determine whether the correct state is BID, SKIP, or HOLD.
2. If HOLD, explain why and what data is required.
3. Normalize win probability if data is missing but historical clustering exists.
4. Produce a contractor-ready recommendation summary.

Decision Context:
{context}
"""


def run_llm_advisor(decision_context: Dict[str, Any], model: str = "gpt-4.1") -> Dict[str, Any]:
    """Call the OpenAI Chat Completions API with strict guardrails and JSON response."""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required to run the LLM advisor.")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
                    context=json.dumps(decision_context, indent=2)
                ),
            },
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM advisor returned an empty response.")

    return json.loads(content)

