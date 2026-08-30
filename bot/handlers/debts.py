"""Debt management handlers."""

from __future__ import annotations

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.db.database import (
    get_debts_for_month,
    get_debt_history,
    add_debt_repayment,
    delete_ledger_entry,
)
from bot.config import CURRENCY, PERSON_1, PERSON_2
from bot.handlers.menu import MAIN_KEYBOARD

# Conversation states
REPAY_PERSON, REPAY_AMOUNT = range(2)

def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")

async def show_debts_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point when '💸 Долги' is clicked."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Текущие долги", callback_data="debts:current")],
        [InlineKeyboardButton("💳 Погасить долг", callback_data="debts:repay_start")],
        [InlineKeyboardButton("🗓 История записей", callback_data="debts:history:0")],
    ])
    await update.message.reply_text(
        "💸 <b>Управление долгами</b>\n\nЗдесь вы можете посмотреть, кто сколько должен внести в бюджет, и погасить долг.",
        parse_mode="HTML",
        reply_markup=keyboard
    )

async def debts_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle simple inline callbacks for debts."""
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")
    action = data[1]

    month = _current_month()

    if action == "current":
        debts = await get_debts_for_month(month)
        text = f"📊 <b>Долги перед бюджетом ({month})</b>\n\n"
        total = 0.0
        
        # Ensure both persons are shown even if 0
        for person in [PERSON_1, PERSON_2]:
            amt = debts.get(person, 0.0)
            total += amt
            text += f"👤 {person}: <b>{amt:.2f} {CURRENCY}</b>\n"
            
        text += f"\n<i>Итого к возврату в бюджет: {total:.2f} {CURRENCY}</i>"
        
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="debts:menu")]])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif action == "menu":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Текущие долги", callback_data="debts:current")],
            [InlineKeyboardButton("💳 Погасить долг", callback_data="debts:repay_start")],
            [InlineKeyboardButton("🗓 История записей", callback_data="debts:history:0")],
        ])
        await query.edit_message_text(
            "💸 <b>Управление долгами</b>\n\nЗдесь вы можете посмотреть, кто сколько должен внести в бюджет, и погасить долг.",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif action == "history":
        page = int(data[2]) if len(data) > 2 else 0
        items_per_page = 5
        
        history = await get_debt_history(month, limit=50) # Fetch up to 50 recent
        
        if not history:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="debts:menu")]])
            await query.edit_message_text("🗓 История операций пуста.", reply_markup=keyboard)
            return

        total_pages = max(1, (len(history) + items_per_page - 1) // items_per_page)
        if page < 0: page = 0
        if page >= total_pages: page = total_pages - 1
        
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        page_items = history[start_idx:end_idx]
        
        text = f"🗓 <b>История операций ({month})</b>\nСтр. {page+1} из {total_pages}\n\n"
        
        buttons = []
        for row in page_items:
            rid, person, amount, t_type, desc, created_at = row
            # Format time
            try:
                dt = datetime.fromisoformat(str(created_at))
                dt_str = dt.strftime("%d.%m %H:%M")
            except:
                dt_str = str(created_at)[:16]
                
            sign = "+" if amount > 0 else ""
            icon = "🔴" if amount > 0 else "🟢"
            text += f"{icon} {dt_str} | <b>{person}</b>: {sign}{amount:.2f} {CURRENCY}\n"
            text += f"<i>{desc or 'Без описания'}</i>\n\n"
            
            buttons.append([InlineKeyboardButton(f"❌ Удалить запись {sign}{amount} ({person})", callback_data=f"debts:delete:{rid}")])
            
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"debts:history:{page-1}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"debts:history:{page+1}"))
            
        if nav_row:
            buttons.append(nav_row)
            
        buttons.append([InlineKeyboardButton("⬅️ Вернуться в меню", callback_data="debts:menu")])
        
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        
    elif action == "delete":
        entry_id = int(data[2])
        await delete_ledger_entry(entry_id)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ В историю", callback_data="debts:history:0")]])
        await query.edit_message_text("✅ Запись удалена! Баланс обновлен.", reply_markup=keyboard)

# ─── Repay Conversation ───────────────────────────────────────────────────────

async def repay_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    keyboard = ReplyKeyboardMarkup([[PERSON_1, PERSON_2], ["Отмена"]], resize_keyboard=True, one_time_keyboard=True)
    
    # We must send a new message because we are changing the standard keyboard
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="💳 <b>Погашение долга</b>\n\nКто вносит деньги в бюджет?",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    return REPAY_PERSON

async def repay_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    person = update.message.text
    if person not in (PERSON_1, PERSON_2):
        await update.message.reply_text("Пожалуйста, выберите человека из кнопок ниже.")
        return REPAY_PERSON
        
    context.user_data["repay_person"] = person
    
    await update.message.reply_text(
        f"Укажите сумму, которую <b>{person}</b> вносит в бюджет (например, 15.50):",
        parse_mode="HTML"
    )
    return REPAY_AMOUNT

async def repay_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amount_str = update.message.text.replace(",", ".")
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное положительное число (например: 15.50)")
        return REPAY_AMOUNT
        
    person = context.user_data.get("repay_person")
    month = _current_month()
    
    await add_debt_repayment(person, amount, month)
    
    # Clear user data
    context.user_data.pop("repay_person", None)
    
    await update.message.reply_text(
        f"✅ <b>Отлично!</b>\nСумма {amount:.2f} {CURRENCY} зачтена как возврат в бюджет от {person}.",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD
    )
    return ConversationHandler.END

async def cancel_repay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("repay_person", None)
    await update.message.reply_text("Действие отменено.", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END

def build_repay_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(repay_start, pattern=r"^debts:repay_start$")],
        states={
            REPAY_PERSON: [
                MessageHandler(filters.Regex(f"^({PERSON_1}|{PERSON_2})$"), repay_person)
            ],
            REPAY_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^Отмена$"), repay_amount)
            ],
        },
        fallbacks=[
            MessageHandler(filters.Regex("^Отмена$"), cancel_repay),
            CommandHandler("cancel", cancel_repay)
        ],
    )

def get_debts_callback_handlers() -> list:
    return [
        CallbackQueryHandler(debts_callback_handler, pattern=r"^debts:(?!repay_start)"),
    ]
