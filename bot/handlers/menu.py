"""Main menu handler — /start command and persistent keyboard."""

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["📸 Добавить чек", "📸 Добавить чеки (Пачкой)"],
        ["📋 История чеков", "💰 Бюджет на месяц"],
        ["⚙️ Настройки"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет! Я <b>ReceiptBot</b> — ваш помощник по учёту расходов.\n\n"
        "Используйте кнопки ниже:\n"
        "📸 <b>Добавить чек</b> — загрузить фото чека\n"
        "📋 <b>История чеков</b> — чеки за текущий месяц\n"
        "💰 <b>Бюджет на месяц</b> — установить/посмотреть бюджет\n"
        "⚙️ <b>Настройки</b> — указать канал для отправки отчётов",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )
