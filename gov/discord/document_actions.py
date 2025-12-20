from __future__ import annotations

from pathlib import Path

import discord

from gov.discord.checklist_state import CHECKLIST_STATE
from gov.documents.quote_generator import generate_quote_pdf, generate_traceability_pdf
from gov.supply_chain.qpl_validator import validate_supplier_qpl


async def run_document_generation(interaction: discord.Interaction, rfq_id: str) -> None:
    state = CHECKLIST_STATE.get(rfq_id, {})

    if not state:
        await interaction.response.send_message(
            "❌ No checklist items selected.",
            ephemeral=True,
        )
        return

    cache = getattr(interaction.client, "cache", {})
    rfq = cache.get("rfqs", {}).get(rfq_id)
    supplier = cache.get("supplier")
    pricing = cache.get("pricing")

    if not rfq:
        await interaction.response.send_message(
            "❌ RFQ data is no longer available for document generation.",
            ephemeral=True,
        )
        return

    rfq_payload = rfq or {}
    supplier_payload = supplier or {}
    pricing_payload = pricing or {}

    validation = validate_supplier_qpl(rfq_payload, supplier_payload)
    if validation["status"] == "FAIL":
        reasons = "\n".join(validation.get("reasons", [])) or "QPL/QML validation failed."
        await interaction.response.send_message(
            f"❌ Document generation blocked:\n{reasons}",
            ephemeral=True,
        )
        return

    base_output_dir = Path("/tmp/gov_documents")
    files = []

    if state.get("quote"):
        files.append(
            generate_quote_pdf(
                rfq_payload,
                supplier_payload,
                pricing_payload,
                output_dir=base_output_dir / "quotes",
            )
        )

    if state.get("traceability"):
        files.append(
            generate_traceability_pdf(
                rfq_payload,
                supplier_payload,
                output_dir=base_output_dir / "traceability",
            )
        )

    await interaction.response.send_message(
        content="📄 Documents generated:",
        files=[discord.File(file_path) for file_path in files],
    )

    CHECKLIST_STATE.pop(rfq_id, None)
