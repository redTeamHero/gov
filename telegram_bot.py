import asyncio
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from gov.checklist import generate_checklist

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


@dataclass
class ChecklistSession:
    solicitation_id: str
    summary: str
    risks: List[str]
    checklist: List[Dict[str, str]]
    responses: Dict[str, str] = field(default_factory=dict)


CHECKLIST_SESSIONS: Dict[str, ChecklistSession] = {}
CHECKLIST_INDEX: Dict[str, str] = {}


def _register_session(session: ChecklistSession) -> None:
    CHECKLIST_SESSIONS[session.solicitation_id] = session
    for item in session.checklist:
        CHECKLIST_INDEX[item["id"]] = session.solicitation_id


def _cleanup_session(session_id: str) -> None:
    session = CHECKLIST_SESSIONS.pop(session_id, None)
    if not session:
        return
    for item in session.checklist:
        CHECKLIST_INDEX.pop(item["id"], None)


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


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.document:
        return

    document = update.message.document
    if not document.file_name or not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("❌ Please upload a PDF RFQ.")
        return

    await update.message.reply_text("📄 RFQ received. Analyzing…")
    session_id = uuid4().hex[:8]
    pdf_path = Path("/tmp") / f"{session_id}_{document.file_name}"
    file = await document.get_file()
    await file.download_to_drive(custom_path=str(pdf_path))

    try:
        data = await asyncio.to_thread(run_analysis, pdf_path)
        checklist_payload = generate_checklist(data, id_prefix=session_id)
        session = ChecklistSession(
            solicitation_id=session_id,
            summary=checklist_payload["summary"],
            risks=checklist_payload["risks"],
            checklist=checklist_payload["checklist"],
        )
        _register_session(session)

        await update.message.reply_text(session.summary)
        if session.risks:
            await update.message.reply_text("⚠️ Risks:\n" + "\n".join(f"• {risk}" for risk in session.risks))
        else:
            await update.message.reply_text("⚠️ Risks: None reported.")

        # Pause here and wait for human input on each checklist item before proceeding.
        for item in session.checklist:
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("YES", callback_data=f"{item['id']}:yes"),
                        InlineKeyboardButton("NO", callback_data=f"{item['id']}:no"),
                    ]
                ]
            )
            await update.message.reply_text(item["question"], reply_markup=keyboard)
    except subprocess.TimeoutExpired:
        await update.message.reply_text("❌ Analysis timed out. Please try again with a smaller file.")
    except Exception as exc:  # pylint: disable=broad-except
        await update.message.reply_text(f"❌ Error processing RFQ:\n```{exc}```")
    finally:
        if pdf_path.exists():
            pdf_path.unlink(missing_ok=True)


def _build_consolidated_response(session: ChecklistSession) -> Dict[str, Any]:
    return {
        "solicitation_id": session.solicitation_id,
        "summary": session.summary,
        "risks": session.risks,
        "checklist_responses": session.responses,
    }


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return

    query = update.callback_query
    await query.answer()

    if not query.data or ":" not in query.data:
        await query.edit_message_text("⚠️ Invalid checklist response received.")
        return

    checklist_id, answer = query.data.rsplit(":", 1)
    if answer not in ("yes", "no"):
        await query.edit_message_text("⚠️ Invalid checklist response received.")
        return

    session_id = CHECKLIST_INDEX.get(checklist_id)
    if not session_id:
        await query.edit_message_text("⚠️ Checklist session expired or unknown.")
        return

    session = CHECKLIST_SESSIONS.get(session_id)
    if not session:
        await query.edit_message_text("⚠️ Checklist session expired or unknown.")
        return

    session.responses[checklist_id] = answer
    await query.edit_message_reply_markup(reply_markup=None)
    await query.edit_message_text(f"{query.message.text}\n\n✅ Recorded: {answer.upper()}")

    # Fail safely if checklist input is incomplete by waiting for all responses.
    if len(session.responses) < len(session.checklist):
        return

    consolidated = _build_consolidated_response(session)
    await context.bot.send_message(chat_id=query.message.chat_id, text=json.dumps(consolidated, indent=2))
    _cleanup_session(session_id)


def main() -> None:
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to your .env file.")

    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.run_polling()


if __name__ == "__main__":
    main()
