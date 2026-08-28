"""Settings handler — configure channel for reports."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.db.database import get_setting, set_setting
from bot.handlers.menu import MAIN_KEYBOARD

WAIT_CHANNEL = 1

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    channel_id = await get_setting("channel_id")
    
    text = (
        "⚙️ <b>Настройки бота</b>\n\n"
        f"Текущий канал для отчётов: <b>{channel_id or 'Не установлен'}</b>\n\n"
        "<i>Для работы с каналом не забудьте добавить бота в канал в качестве администратора!</i>"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Установить канал", callback_data="set_channel")]
    ])
    
    if update.message:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

async def ask_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📢 Пришлите ID канала (например, <code>-100123456789</code>) или его @username (например, <code>@my_budget_channel</code>):\n\n"
        "Чтобы узнать ID приватного канала, можете переслать сообщение оттуда боту @userinfobot.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_settings")]
        ])
    )
    return WAIT_CHANNEL

async def receive_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    channel = update.message.text.strip()
    await set_setting("channel_id", channel)
    
    await update.message.reply_text(
        f"✅ Канал успешно установлен: <b>{channel}</b>\n"
        "Теперь все новые чеки будут отправляться туда.",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD
    )
    return ConversationHandler.END

async def cancel_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Настройка отменена.")
    return ConversationHandler.END

def build_settings_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_channel, pattern="^set_channel$")],
        states={
            WAIT_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_channel)],
        },
        fallbacks=[CallbackQueryHandler(cancel_settings, pattern="^cancel_settings$")],
        allow_reentry=True,
    )
