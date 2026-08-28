"""
ReceiptBot entry point.

Run with:
    python -m bot.main
or:
    python bot/main.py
"""

from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.config import BOT_TOKEN
from bot.db.database import init_db
from bot.handlers.budget import build_budget_conversation, show_budget
from bot.handlers.history import get_history_callback_handlers, show_history
from bot.handlers.menu import start
from bot.handlers.receipt import build_receipt_conversation
from bot.handlers.settings import show_settings, build_settings_conversation
from bot.handlers.batch import build_batch_conversation

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _post_init(app: Application) -> None:
    await init_db()
    logger.info("✅ Database initialised")


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    # ── Commands ──
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", lambda u, c: None))  # fallback cancel

    # ── Receipt conversations (highest priority) ──
    app.add_handler(build_receipt_conversation(), group=0)
    app.add_handler(build_batch_conversation(), group=0)

    # ── Budget conversation ──
    app.add_handler(build_budget_conversation(), group=1)

    # ── Simple menu button handlers ──
    app.add_handler(
        MessageHandler(filters.Regex(r"^💰 Бюджет на месяц$"), show_budget),
        group=2,
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^📋 История чеков$"), show_history),
        group=2,
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^⚙️ Настройки$"), show_settings),
        group=2,
    )

    # ── Settings conversation ──
    app.add_handler(build_settings_conversation(), group=3)

    # ── Inline callback: receipt detail & delete ──
    for handler in get_history_callback_handlers():
        app.add_handler(handler, group=4)

    logger.info("🤖 ReceiptBot is running…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
