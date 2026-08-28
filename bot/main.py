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


def get_bot_app():
    """Builds and configures the Telegram Bot application."""
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

    return app

async def health_check(request):
    """Dummy web server response to keep Render happy."""
    from aiohttp import web
    return web.Response(text="ReceiptBot is running!")

async def run_bot_and_server():
    from aiohttp import web
    app = get_bot_app()
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("🤖 ReceiptBot is running…")

    # Start dummy web server
    webapp = web.Application()
    webapp.add_routes([web.get('/', health_check)])
    runner = web.AppRunner(webapp)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Dummy web server listening on port {port}")

    # Run forever
    await asyncio.Event().wait()

if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(init_db())
    logger.info("✅ Database initialised")
    
    try:
        asyncio.run(run_bot_and_server())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
