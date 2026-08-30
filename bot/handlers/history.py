"""History handler — show receipt list for the current month."""

from __future__ import annotations

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.db.database import get_month_receipts, get_receipt_by_id, delete_receipt
from bot.config import CURRENCY

# (rest is omitted for brevity, keeping functions below intact)

def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")

def _month_display(month: str) -> str:
    months_ru = [
        "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ]
    year, m = month.split("-")
    return f"{months_ru[int(m)]} {year}"

# ─── Receipt list ─────────────────────────────────────────────────────────────

RECEIPTS_PER_PAGE = 5

async def send_history_page(query_or_message, page: int, month: str):
    receipts = await get_month_receipts(month)
    if not receipts:
        text = f"📋 Нет чеков за {_month_display(month)}."
        if hasattr(query_or_message, "edit_message_text"):
            await query_or_message.edit_message_text(text)
        else:
            await query_or_message.reply_text(text)
        return

    total_month = sum(float(r[3] or 0) for r in receipts)
    total_pages = max(1, (len(receipts) + RECEIPTS_PER_PAGE - 1) // RECEIPTS_PER_PAGE)
    
    if page < 0: page = 0
    if page >= total_pages: page = total_pages - 1
    
    start_idx = page * RECEIPTS_PER_PAGE
    end_idx = start_idx + RECEIPTS_PER_PAGE
    page_receipts = receipts[start_idx:end_idx]
    
    buttons = []
    for row in page_receipts:
        rid, date, store, amount = row
        label = f"{date or '?'} — {store or 'Unknown'}: {float(amount or 0):.2f} {CURRENCY}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"receipt_detail:{rid}")])
        
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"history_page:{page-1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"history_page:{page+1}"))
        
    if nav_row:
        buttons.append(nav_row)
        
    text = (
        f"📋 <b>История чеков — {_month_display(month)}</b>\n\n"
        f"Всего чеков: <b>{len(receipts)}</b>\n"
        f"Итого потрачено: <b>{total_month:.2f} {CURRENCY}</b>\n"
        f"Страница: <b>{page+1} из {total_pages}</b>\n\n"
        "Нажмите на чек, чтобы посмотреть детали:"
    )
    
    if hasattr(query_or_message, "edit_message_text"):
        await query_or_message.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await query_or_message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_history_page(update.message, 0, _current_month())

async def history_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":")[1])
    await send_history_page(query, page, _current_month())

# ─── Receipt detail ───────────────────────────────────────────────────────────

async def show_receipt_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    receipt_id = int(query.data.split(":")[1])
    receipt, items, expenses = await get_receipt_by_id(receipt_id)

    if not receipt:
        await query.edit_message_text("❌ Чек не найден или уже удалён.")
        return

    _, date, store, total, photo_file_id, report_text, month, created_at, *_ = receipt

    if report_text:
        text = f"🧾 <b>Чек #{receipt_id}</b>\n\n{report_text}"
    else:
        text = (
            f"🧾 <b>Чек #{receipt_id}</b>\n"
            f"📅 Дата: {date or '—'}\n"
            f"🏪 Магазин: {store or 'Unknown'}\n"
            f"💸 Сумма: {float(total or 0):.2f} {CURRENCY}"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Удалить чек", callback_data=f"delete_receipt:{receipt_id}")]
    ])

    if photo_file_id:
        await context.bot.send_photo(
            chat_id    = query.message.chat_id,
            photo      = photo_file_id,
            caption    = text,
            parse_mode = "HTML",
            reply_markup=keyboard,
        )
    else:
        await context.bot.send_message(
            chat_id    = query.message.chat_id,
            text       = text,
            parse_mode = "HTML",
            reply_markup=keyboard,
        )

async def delete_receipt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    receipt_id = int(query.data.split(":")[1])
    await delete_receipt(receipt_id)
    
    if query.message.caption:
        await query.edit_message_caption("🗑 <b>Чек и отчёт удалены.</b>", parse_mode="HTML")
    else:
        await query.edit_message_text("🗑 <b>Чек и отчёт удалены.</b>", parse_mode="HTML")

# ─── Register callback handlers ───────────────────────────────────────────────

def get_history_callback_handlers() -> list:
    return [
        CallbackQueryHandler(show_receipt_detail, pattern=r"^receipt_detail:\d+$"),
        CallbackQueryHandler(delete_receipt_callback, pattern=r"^delete_receipt:\d+$"),
        CallbackQueryHandler(history_page_callback, pattern=r"^history_page:\d+$"),
    ]
