"""
Receipt conversation handler.

Flow:
  User presses "📸 Добавить чек"
    → WAIT_PHOTO  : bot waits for a photo
    → photo received → OCR analysis
    → WAIT_VOICE_OR_SKIP : bot asks for voice note or skip
    → voice received → transcribe + analyse personal expenses
      OR user presses "Пропустить"
    → build report → save to DB → send to channel → show to user
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.db.database import (
    get_budget,
    get_month_spent,
    save_personal_expenses,
    save_receipt,
    save_receipt_items,
    get_setting,
)
from bot.handlers.menu import MAIN_KEYBOARD
from bot.services.gemini import analyse_receipt, analyse_voice
from bot.services.report import build_report

logger = logging.getLogger(__name__)

# ─── Conversation states ──────────────────────────────────────────────────────

WAIT_PHOTO, WAIT_VOICE_OR_SKIP = range(2)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Пропустить", callback_data="skip_voice")]])

# ─── Entry point ─────────────────────────────────────────────────────────────

async def add_receipt_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📸 Пришлите фото чека:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel_receipt")]]),
    )
    return WAIT_PHOTO

# ─── Step 1: receive photo ────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = await update.message.reply_text("⏳ Анализирую чек, подождите...")

    # Download the highest-resolution photo
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await tg_file.download_as_bytearray())

    try:
        receipt_data = await analyse_receipt(image_bytes)
    except Exception as exc:
        logger.exception("Receipt OCR failed")
        await msg.edit_text(f"❌ Не удалось распознать чек: {exc}\n\nПопробуйте ещё раз.")
        return ConversationHandler.END

    # Store for next step
    context.user_data["receipt_data"] = receipt_data
    context.user_data["photo_file_id"] = photo.file_id

    store   = receipt_data.get("store", "Unknown")
    total   = receipt_data.get("total", 0)
    date_s  = receipt_data.get("date") or "не распознана"
    n_items = len(receipt_data.get("items", []))

    await msg.edit_text(
        f"✅ <b>Чек распознан!</b>\n\n"
        f"🏪 Магазин: <b>{store}</b>\n"
        f"📅 Дата: <b>{date_s}</b>\n"
        f"💸 Сумма: <b>{total:.2f} €</b>\n"
        f"🛒 Позиций: <b>{n_items}</b>\n\n"
        f"🎤 Пришлите <b>голосовое сообщение</b> с деталями —\n"
        f"кто что купил из общего бюджета лично.\n\n"
        f"Или нажмите <b>Пропустить</b>, если деталей нет.",
        parse_mode="HTML",
        reply_markup=_skip_keyboard(),
    )
    return WAIT_VOICE_OR_SKIP

# ─── Step 2a: receive voice ───────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = await update.message.reply_text("🎤 Обрабатываю голосовое сообщение...")

    receipt_data  = context.user_data.get("receipt_data", {})
    photo_file_id = context.user_data.get("photo_file_id")

    # Download voice file (.ogg)
    voice_tg_file = await context.bot.get_file(update.message.voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await voice_tg_file.download_to_drive(tmp_path)

    try:
        voice_result   = await analyse_voice(tmp_path, receipt_data)
        personal_exps  = voice_result.get("personal_expenses", [])
        transcription  = voice_result.get("transcription", "")
        logger.info("Personal expenses extracted: %s", personal_exps)
    except Exception as exc:
        logger.exception("Voice analysis failed")
        await msg.edit_text(f"⚠️ Не удалось обработать голосовое: {exc}\nОтчёт будет без деталей.")
        personal_exps = []
        transcription = ""
    finally:
        os.unlink(tmp_path)

    await msg.edit_text("📊 Формирую отчёт...")
    await _finalise(update, context, receipt_data, photo_file_id, personal_exps)
    return ConversationHandler.END

# ─── Step 2b: skip voice ─────────────────────────────────────────────────────

async def skip_voice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📊 Формирую отчёт...")

    receipt_data  = context.user_data.get("receipt_data", {})
    photo_file_id = context.user_data.get("photo_file_id")

    await _finalise(query, context, receipt_data, photo_file_id, [])
    return ConversationHandler.END

# ─── Cancel ───────────────────────────────────────────────────────────────────

async def cancel_receipt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Добавление чека отменено.")
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Отменено.", reply_markup=MAIN_KEYBOARD)
    context.user_data.clear()
    return ConversationHandler.END

# ─── Finalise: build report, save DB, send to channel ────────────────────────

async def _finalise(
    update_or_query,
    context: ContextTypes.DEFAULT_TYPE,
    receipt_data: dict,
    photo_file_id: str,
    personal_expenses: list[dict],
    batch_mode: bool = False,
) -> None:
    month = _current_month()

    budget        = await get_budget(month)
    spent_before  = await get_month_spent(month)
    report_text   = build_report(receipt_data, personal_expenses, budget, spent_before)

    # Persist to DB
    receipt_id = await save_receipt(
        date          = receipt_data.get("date"),
        store         = receipt_data.get("store"),
        total_amount  = float(receipt_data.get("total") or 0),
        photo_file_id = photo_file_id,
        report_text   = report_text,
        month         = month,
        receipt_hash  = receipt_data.get("receipt_hash", ""),
    )
    await save_receipt_items(receipt_id, receipt_data.get("items", []))
    if personal_expenses:
        await save_personal_expenses(receipt_id, personal_expenses, month)

    # Send to Telegram channel
    channel_id = await get_setting("channel_id")
    if channel_id:
        try:
            await context.bot.send_photo(
                chat_id    = channel_id,
                photo      = photo_file_id,
                caption    = report_text,
                parse_mode = "HTML",
            )
        except Exception as exc:
            logger.error("Failed to post to channel %s: %s", channel_id, exc)

    # Determine chat_id for reply
    if hasattr(update_or_query, "effective_chat") and update_or_query.effective_chat:
        chat_id = update_or_query.effective_chat.id
    elif hasattr(update_or_query, "message") and update_or_query.message:
        chat_id = update_or_query.message.chat_id
    else:
        chat_id = update_or_query.from_user.id

    # In batch mode: no main keyboard spam after each receipt, just send the report photo
    await context.bot.send_photo(
        chat_id      = chat_id,
        photo        = photo_file_id,
        caption      = f"✅ <b>Отчёт сформирован!</b>\n\n{report_text}",
        parse_mode   = "HTML",
        reply_markup = None if batch_mode else MAIN_KEYBOARD,
    )

    # Only clear user data in single-receipt mode
    if not batch_mode:
        context.user_data.clear()

# ─── ConversationHandler factory ─────────────────────────────────────────────

def build_receipt_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^📸 Добавить чек$"), add_receipt_entry),
        ],
        states={
            WAIT_PHOTO: [
                MessageHandler(filters.PHOTO, handle_photo),
                CallbackQueryHandler(cancel_receipt_callback, pattern="^cancel_receipt$"),
            ],
            WAIT_VOICE_OR_SKIP: [
                MessageHandler(filters.VOICE, handle_voice),
                CallbackQueryHandler(skip_voice_callback, pattern="^skip_voice$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CallbackQueryHandler(cancel_receipt_callback, pattern="^cancel_receipt$"),
        ],
        allow_reentry=True,
    )
