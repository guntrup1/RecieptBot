"""
Batch receipts conversation handler.
Accepts multiple photos, then one voice note, and processes them chronologically.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.db.database import receipt_exists
from bot.handlers.menu import MAIN_KEYBOARD
from bot.handlers.receipt import _finalise
from bot.services.gemini import analyse_receipt, transcribe_voice, analyse_voice

logger = logging.getLogger(__name__)

WAIT_BATCH_PHOTOS, WAIT_BATCH_VOICE = range(2)

def _done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Готово (Обработать)", callback_data="batch_done")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_batch")],
    ])

async def add_batch_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["batch_photos"] = []
    await update.message.reply_text(
        "📸 <b>Пакетная загрузка чеков</b>\n\n"
        "Отправляйте фото чеков по одному или сразу группой (альбомом).\n"
        "Когда загрузите все чеки, нажмите <b>Готово</b>.",
        parse_mode="HTML",
        reply_markup=_done_keyboard(),
    )
    return WAIT_BATCH_PHOTOS

async def handle_batch_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if "batch_photos" not in context.user_data:
        context.user_data["batch_photos"] = []
    
    photo_file_id = update.message.photo[-1].file_id
    context.user_data["batch_photos"].append(photo_file_id)
    
    count = len(context.user_data["batch_photos"])
    await update.message.reply_text(
        f"✅ Принято чеков: <b>{count}</b>. Присылайте ещё или нажмите Готово.",
        parse_mode="HTML",
        reply_markup=_done_keyboard(),
    )
    return WAIT_BATCH_PHOTOS

async def batch_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    photos = context.user_data.get("batch_photos", [])
    if not photos:
        await query.edit_message_text("Вы не загрузили ни одного чека. Отмена.")
        context.user_data.clear()
        return ConversationHandler.END

    await query.edit_message_text(
        f"📦 Вы загрузили <b>{len(photos)}</b> чеков.\n\n"
        "🎤 Теперь запишите <b>одно голосовое сообщение</b> с общими правилами (например: «Жора брал пиво, а Настя овощи и йогурты»).\n\n"
        "<i>Или нажмите Пропустить, если всё идёт в общий бюджет.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Пропустить", callback_data="skip_batch_voice")]]),
    )
    return WAIT_BATCH_VOICE

async def handle_batch_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = await update.message.reply_text("⏳ Расшифровываю правила из голосового...")
    
    voice_tg_file = await context.bot.get_file(update.message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await voice_tg_file.download_to_drive(tmp_path)
    
    try:
        transcription = await transcribe_voice(tmp_path)
    except Exception as exc:
        logger.exception("Batch Voice transcription failed")
        await msg.edit_text(f"⚠️ Не удалось распознать голосовое: {exc}\nПродолжаю без правил.")
        transcription = ""
    finally:
        os.unlink(tmp_path)
        
    await process_batch(update, context, msg, transcription)
    return ConversationHandler.END

async def skip_batch_voice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    msg = await query.edit_message_text("⏳ Начинаю обработку чеков...")
    await process_batch(update, context, msg, "")
    return ConversationHandler.END

async def safe_edit(msg, text: str):
    try:
        await msg.edit_text(text, parse_mode="HTML")
    except Exception:
        pass # Ignore telegram edit flood warnings

async def process_batch(update_or_query, context, status_msg, transcription: str):
    photos = context.user_data.get("batch_photos", [])
    total = len(photos)
    
    valid_receipts = []
    
    # 1. OCR all photos and deduplicate
    for i, photo_id in enumerate(photos, 1):
        await safe_edit(status_msg, f"🔍 Распознаю чек <b>{i} из {total}</b>...")
        
        try:
            tg_file = await context.bot.get_file(photo_id)
            image_bytes = bytes(await tg_file.download_as_bytearray())
            receipt_data = await analyse_receipt(image_bytes)
            rh = receipt_data.get("receipt_hash", "unknown")
            
            # Deduplication Check
            if await receipt_exists(rh):
                logger.info(f"Duplicate receipt hash skipped: {rh}")
                await context.bot.send_message(
                    chat_id=update_or_query.effective_chat.id,
                    text=f"⚠️ Чек {i} уже есть в базе (пропущен как дубликат)."
                )
                continue
                
            valid_receipts.append({
                "photo_id": photo_id,
                "data": receipt_data,
                "_sort_date": receipt_data.get("date") or "00.00.0000" 
            })
        except Exception as exc:
            logger.error("Failed to parse batch receipt %s: %s", i, exc)
            await context.bot.send_message(
                chat_id=update_or_query.effective_chat.id,
                text=f"❌ Ошибка распознавания чека {i}: {exc}"
            )

    if not valid_receipts:
        await safe_edit(status_msg, "🤷‍♂️ Ни один чек не был успешно распознан (или все пропущены как дубликаты).")
        context.user_data.clear()
        return

    # 2. Sort chronologically by date
    def parse_dt(r):
        d = r["_sort_date"]
        try:
            return datetime.strptime(d, "%d.%m.%Y")
        except:
            return datetime.min

    valid_receipts.sort(key=parse_dt)
    total_valid = len(valid_receipts)
    
    # 3. Analyze each and publish
    for i, vr in enumerate(valid_receipts, 1):
        try:
            await safe_edit(status_msg, f"🧠 Анализирую траты чека <b>{i} из {total_valid}</b>...")
            
            personal_exps = []
            if transcription:
                voice_result = await analyse_voice(transcription, vr["data"], is_transcription=True)
                personal_exps = voice_result.get("personal_expenses", [])
            
            await _finalise(
                update_or_query,
                context,
                receipt_data=vr["data"],
                photo_file_id=vr["photo_id"],
                personal_expenses=personal_exps,
                batch_mode=True,
            )
        except Exception as exc:
            logger.error("Error generating report for batch receipt %s: %s", i, exc)
            await context.bot.send_message(
                chat_id=update_or_query.effective_chat.id,
                text=f"❌ Ошибка формирования отчёта для чека {i}: {exc}"
            )
        
    await safe_edit(status_msg, f"✅ <b>Пакетная обработка завершена!</b>\nОбраработано чеков: {total_valid}")
    context.user_data.clear()

async def cancel_batch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Добавление чеков отменено.")
    context.user_data.clear()
    return ConversationHandler.END

def build_batch_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^📸 Добавить чеки \(Пачкой\)$"), add_batch_entry)],
        states={
            WAIT_BATCH_PHOTOS: [
                MessageHandler(filters.PHOTO, handle_batch_photo),
                CallbackQueryHandler(batch_done_callback, pattern="^batch_done$"),
                CallbackQueryHandler(cancel_batch_callback, pattern="^cancel_batch$"),
            ],
            WAIT_BATCH_VOICE: [
                MessageHandler(filters.VOICE, handle_batch_voice),
                CallbackQueryHandler(skip_batch_voice_callback, pattern="^skip_batch_voice$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_batch_callback, pattern="^cancel_batch$")],
        allow_reentry=True,
    )
