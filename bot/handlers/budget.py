"""Budget handler — view and set monthly budget."""

from __future__ import annotations

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.db.database import get_budget, get_month_spent, set_budget
from bot.handlers.menu import MAIN_KEYBOARD

SET_BUDGET_AMOUNT = 10


def _month_display(month: str) -> str:
    """Convert '2026-08' → 'Август 2026'."""
    months_ru = [
        "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ]
    year, m = month.split("-")
    return f"{months_ru[int(m)]} {year}"


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


# ─── Show budget ──────────────────────────────────────────────────────────────

async def show_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    month        = _current_month()
    budget       = await get_budget(month)
    spent        = await get_month_spent(month)
    remaining    = budget - spent

    month_label  = _month_display(month)

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✏️ Установить бюджет", callback_data="set_budget_start")]]
    )

    if budget == 0:
        text = (
            f"💰 <b>Бюджет на {month_label}</b>\n\n"
            f"⚠️ Бюджет не установлен.\n"
            f"Потрачено: <b>{spent:.2f} €</b>\n\n"
            f"Нажмите кнопку ниже, чтобы задать бюджет."
        )
    else:
        pct = (spent / budget * 100) if budget > 0 else 0
        text = (
            f"💰 <b>Бюджет на {month_label}</b>\n\n"
            f"Установлен: <b>{budget:.2f} €</b>\n"
            f"Потрачено:  <b>{spent:.2f} €</b> ({pct:.0f}%)\n"
            f"Осталось:   <b>{remaining:.2f} €</b>"
        )

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


# ─── Set budget conversation ──────────────────────────────────────────────────

async def set_budget_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✏️ Введите сумму бюджета на текущий месяц (в евро):\n"
        "Пример: <b>500</b> или <b>750.50</b>",
        parse_mode="HTML",
    )
    return SET_BUDGET_AMOUNT


async def receive_budget_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().replace(",", ".")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ Введите корректную сумму, например: <b>500</b>",
            parse_mode="HTML",
        )
        return SET_BUDGET_AMOUNT

    month = _current_month()
    await set_budget(month, amount)

    await update.message.reply_text(
        f"✅ Бюджет на {_month_display(month)} установлен: <b>{amount:.2f} €</b>",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )
    return ConversationHandler.END


async def cancel_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Отменено.", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


def build_budget_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(set_budget_start, pattern="^set_budget_start$"),
        ],
        states={
            SET_BUDGET_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_budget_amount)
            ],
        },
        fallbacks=[],
        allow_reentry=True,
    )
