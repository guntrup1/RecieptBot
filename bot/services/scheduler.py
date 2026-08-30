"""Background scheduler for automated tasks."""

import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from bot.db.database import cleanup_old_data, get_debts_for_month
from bot.config import CHANNEL_ID, CURRENCY

logger = logging.getLogger(__name__)

async def run_cleanup():
    logger.info("Running daily DB cleanup...")
    try:
        deleted = await cleanup_old_data()
        logger.info(f"Cleanup finished. Deleted {deleted} old receipt(s).")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

async def send_monthly_summary(bot):
    if not CHANNEL_ID:
        logger.warning("No CHANNEL_ID set. Skipping monthly summary.")
        return
        
    month = datetime.now().strftime("%Y-%m")
    try:
        debts = await get_debts_for_month(month)
        
        if not debts:
            text = f"📊 <b>Итоги месяца ({month})</b>\n\nВ этом месяце долгов не зафиксировано."
        else:
            text = f"📊 <b>Итоги месяца ({month})</b>\n\nТекущие долги перед общим бюджетом:\n"
            total = 0.0
            for person, amt in debts.items():
                text += f"👤 {person}: <b>{amt:.2f} {CURRENCY}</b>\n"
                total += amt
            text += f"\n<i>Итого к пополнению: {total:.2f} {CURRENCY}</i>"
            
        await bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML")
        logger.info(f"Monthly summary sent to {CHANNEL_ID}")
    except Exception as e:
        logger.error(f"Failed to send monthly summary: {e}")

def start_scheduler(bot):
    # Defaulting to Moscow time (UTC+3)
    tz = pytz.timezone("Europe/Moscow")
    scheduler = AsyncIOScheduler(timezone=tz)
    
    # Monthly summary on the last day of the month at 17:00
    scheduler.add_job(send_monthly_summary, CronTrigger(day="last", hour=17, minute=0, timezone=tz), args=[bot])
    
    scheduler.start()
    logger.info("📅 APScheduler started.")
