import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List
from uuid import uuid4

import discord
from discord import ui
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

client = discord.Client(intents=intents)

user_sessions: Dict[int, Dict[str, Any]] = {}


def _pick_first(source: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key not in source:
            continue
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _derive_decision(data: Dict[str, Any]) -> str:
    decision = _pick_first(
        data,
        [
            "decision",
            "final_decision",
            "bid_decision",
            "recommendation",
        ],
    ) or ""
    if isinstance(decision, dict):
        decision = _pick_first(decision, decision.keys()) or ""
    return str(decision).upper() or "UNKNOWN"


def _derive_rationale(data: Dict[str, Any]) -> str:
    rationale = _pick_first(
        data,
        [
            "manager_explanation",
            "decision_rationale",
            "reason",
            "rationale",
            "explanation",
        ],
    )
    return str(rationale) if rationale else "No rationale returned from the engine."


def _derive_key_facts(data: Dict[str, Any]) -> Dict[str, str]:
    facts = data.get("key_facts") or {}
    snapshot = data.get("snapshot") or {}
    compliance_flags = data.get("compliance_flags") or {}

    quantity = _pick_first(facts, ["quantity", "qty"]) or snapshot.get("quantity")
    delivery = _pick_first(facts, ["delivery", "delivery_terms", "delivery_requirement"]) or snapshot.get(
        "delivery_requirement"
    )
    fob = _pick_first(facts, ["fob", "FOB", "fdt", "FDT"]) or snapshot.get("fob")

    packaging_required = facts.get("packaging") or facts.get("packaging_requirements")
    if not packaging_required and isinstance(compliance_flags, dict) and compliance_flags.get("packaging"):
        packaging_required = "Packaging compliance required"

    cyber_required = facts.get("cyber") or facts.get("cybersecurity")
    if not cyber_required and isinstance(compliance_flags, dict) and compliance_flags.get("cyber"):
        cyber_required = "Cyber clause present"

    return {
        "quantity": str(quantity) if quantity else "Not provided",
        "delivery": str(delivery) if delivery else "Not provided",
        "fob": str(fob) if fob else "Not provided",
        "packaging": str(packaging_required) if packaging_required else "Not flagged",
        "cyber": str(cyber_required) if cyber_required else "Not flagged",
    }


def _derive_risks(data: Dict[str, Any]) -> List[str]:
    raw_risks: Any = data.get("bid_risk_and_compliance_exposure") or data.get("risks") or data.get("compliance_risks")
    if isinstance(raw_risks, dict):
        return [str(item) for item in raw_risks.values() if item]
    if isinstance(raw_risks, list):
        return [str(item) for item in raw_risks if item]
    return []


def _derive_hold_resolution_checklist(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    checklist = data.get("hold_resolution_checklist")
    if isinstance(checklist, list):
        return [item for item in checklist if isinstance(item, dict)]
    return []


def _normalize_hold_checklist(checklist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = []
    for item in checklist:
        question = item.get("question")
        if not question:
            continue
        blocking = item.get("blocking")
        if blocking is None:
            blocking = item.get("blocks_bid_if_no")
        normalized.append(
            {
                "id": str(item.get("id") or question).lower().replace(" ", "_"),
                "question": str(question),
                "blocking": bool(blocking),
            }
        )
    return normalized


def _extract_rfq_id(data: Dict[str, Any]) -> str:
    key_facts = data.get("key_facts") or {}
    return str(key_facts.get("rfq_number") or data.get("rfq_number") or "Unknown RFQ")


class HoldResolutionView(ui.View):
    def __init__(self, user_id: int, timeout: int = 900) -> None:
        super().__init__(timeout=timeout)
        self.user_id = user_id

    async def _handle_answer(self, interaction: discord.Interaction, answer: bool) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This checklist belongs to another user.", ephemeral=True
            )
            return

        session = user_sessions.get(self.user_id)
        if not session:
            await interaction.response.send_message(
                "This HOLD resolution session has expired.", ephemeral=True
            )
            return

        idx = session["current_index"]
        checklist = session["checklist"]
        if idx >= len(checklist):
            await interaction.response.send_message("No more checklist items.", ephemeral=True)
            return

        question = checklist[idx]
        session["answers"][question["id"]] = answer
        session["current_index"] += 1

        if session["current_index"] < len(checklist):
            next_question = checklist[session["current_index"]]
            await interaction.response.send_message(
                _format_hold_question_message(session, next_question),
                view=HoldResolutionView(self.user_id),
            )
            return

        blocking_failures = [
            item
            for item in checklist
            if item["blocking"] and session["answers"].get(item["id"]) is False
        ]

        if not blocking_failures:
            lines = [
                "🔥 DECISION UPGRADED: BID (CONDITIONAL)",
                "",
                "You meet all blocking compliance requirements:",
            ]
            for item in checklist:
                if item["blocking"]:
                    lines.append(f"• {item['question']} ✔️")
            lines.append("")
            lines.append("Proceed to pricing and supplier validation.")
            await interaction.response.send_message("\n".join(lines))
        else:
            lines = [
                "⛔ DECISION REMAINS: HOLD",
                "",
                "Blocking compliance gaps detected:",
            ]
            for item in blocking_failures:
                lines.append(f"• {item['question']}")
            lines.append("")
            lines.append("Resolve these items before bidding.")
            await interaction.response.send_message("\n".join(lines))

        user_sessions.pop(self.user_id, None)

    @ui.button(label="✅ Yes", style=discord.ButtonStyle.success, custom_id="hold_yes")
    async def yes_button(self, interaction: discord.Interaction, button: ui.Button) -> None:
        await self._handle_answer(interaction, True)

    @ui.button(label="❌ No", style=discord.ButtonStyle.danger, custom_id="hold_no")
    async def no_button(self, interaction: discord.Interaction, button: ui.Button) -> None:
        await self._handle_answer(interaction, False)


def _format_hold_question_message(session: Dict[str, Any], item: Dict[str, Any]) -> str:
    current = session["current_index"] + 1
    total = len(session["checklist"])
    return (
        f"🔁 HOLD Resolution Question {current}/{total}\n\n"
        f"{item['question']}"
    )


def format_decision_embed(data: Dict[str, Any], filename: str) -> discord.Embed:
    decision = _derive_decision(data)
    rationale = _derive_rationale(data)
    facts = _derive_key_facts(data)
    risks = _derive_risks(data)

    color = {
        "BID": 0x2ECC71,
        "HOLD": 0xF1C40F,
        "SKIP": 0xE74C3C,
    }.get(decision, 0x95A5A6)

    embed = discord.Embed(
        title=f"📑 RFQ Analysis: {filename}",
        description=f"**Decision:** `{decision}`",
        color=color,
    )

    embed.add_field(
        name="🧠 Rationale",
        value=rationale[:1024],
        inline=False,
    )

    embed.add_field(name="📦 Quantity", value=facts["quantity"], inline=True)
    embed.add_field(name="🚚 Delivery", value=facts["delivery"], inline=True)
    embed.add_field(name="📍 FOB / FDT", value=facts["fob"], inline=False)
    embed.add_field(name="🧾 Packaging", value=facts["packaging"], inline=True)
    embed.add_field(name="🔒 Cyber", value=facts["cyber"], inline=True)

    if risks:
        embed.add_field(
            name="⚠️ Compliance Risks",
            value="\n".join(f"• {risk}" for risk in risks[:3]),
            inline=False,
        )
    else:
        embed.add_field(name="⚠️ Compliance Risks", value="No risks reported.", inline=False)

    embed.set_footer(text="Gov Contracting Decision Engine")
    return embed


def run_analysis(pdf_path: Path) -> Dict[str, Any]:
    cmd = [
        "python3",
        "main.py",
        str(pdf_path),
        "--authoritative-llm",
    ]

    completed = subprocess.run(
        cmd,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=180,
        env=os.environ.copy(),
    )

    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "Decision engine returned an error.")

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Engine returned non-JSON output: {completed.stdout[:500]}") from exc


@client.event
async def on_ready():
    print(f"🤖 Logged in as {client.user}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if not message.attachments:
        return

    pdf_attachments = [attachment for attachment in message.attachments if attachment.filename.lower().endswith(".pdf")]
    if not pdf_attachments:
        await message.channel.send("❌ Please upload a PDF RFQ.")
        return

    attachment = pdf_attachments[0]
    await message.channel.send("📄 RFQ received. Analyzing…")

    pdf_path = Path("/tmp") / f"{uuid4()}_{attachment.filename}"
    await attachment.save(pdf_path)

    try:
        data = await asyncio.to_thread(run_analysis, pdf_path)
        await message.channel.send(embed=format_decision_embed(data, attachment.filename))
        checklist = _normalize_hold_checklist(_derive_hold_resolution_checklist(data))
        if _derive_decision(data) == "HOLD" and checklist:
            user_sessions[message.author.id] = {
                "rfq_id": _extract_rfq_id(data),
                "checklist": checklist,
                "current_index": 0,
                "answers": {},
            }
            first_question = checklist[0]
            await message.channel.send(
                _format_hold_question_message(user_sessions[message.author.id], first_question),
                view=HoldResolutionView(message.author.id),
            )
    except subprocess.TimeoutExpired:
        await message.channel.send("❌ Analysis timed out. Please try again with a smaller file.")
    except Exception as exc:  # pylint: disable=broad-except
        await message.channel.send(f"❌ Error processing RFQ:\n```{exc}```")
    finally:
        if pdf_path.exists():
            pdf_path.unlink(missing_ok=True)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is not set. Add it to your .env file.")

    client.run(TOKEN)
