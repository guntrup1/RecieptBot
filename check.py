import asyncio
import sys

# ── imports ──────────────────────────────────────────────────────────────────
try:
    from bot.config import BOT_TOKEN, GEMINI_API_KEY, PERSON_1, PERSON_2, CURRENCY, GEMINI_MODEL
    print("config.py          OK")
    print(f"  PERSON_1={PERSON_1}, PERSON_2={PERSON_2}, CURRENCY={CURRENCY}, MODEL={GEMINI_MODEL}")
    print(f"  BOT_TOKEN set: {bool(BOT_TOKEN)}   GEMINI_API_KEY set: {bool(GEMINI_API_KEY)}")
except Exception as e:
    print(f"config.py          FAIL: {e}")
    sys.exit(1)

try:
    from bot.db.database import init_db, save_receipt, get_budget, get_month_spent, set_budget
    print("db/database.py     OK")
except Exception as e:
    print(f"db/database.py     FAIL: {e}")
    sys.exit(1)

try:
    from bot.services.report import build_report
    sample = {
        "date": "28.08.2026", "store": "Lidl",
        "items": [{"name": "Молоко", "quantity": 2, "price": 1.89}],
        "total": 45.5,
    }
    txt = build_report(
        sample,
        [{"person": "Жора", "item": "чипсы", "amount": 2.75}],
        400.0,
        50.0,
    )
    print("services/report.py OK")
    print("  Preview:")
    for line in txt.splitlines()[:7]:
        print("   ", line)
except Exception as e:
    print(f"services/report.py FAIL: {e}")
    sys.exit(1)

try:
    from bot.services.gemini import analyse_receipt, analyse_voice
    print("services/gemini.py OK")
except Exception as e:
    print(f"services/gemini.py FAIL: {e}")
    sys.exit(1)

try:
    from bot.handlers.menu import start, MAIN_KEYBOARD
    from bot.handlers.receipt import build_receipt_conversation
    from bot.handlers.budget import build_budget_conversation, show_budget
    from bot.handlers.history import show_history, get_history_callback_handler
    print("handlers/*         OK")
except Exception as e:
    print(f"handlers/*         FAIL: {e}")
    sys.exit(1)


# ── SQLite DB ─────────────────────────────────────────────────────────────────
async def test_db():
    await init_db()
    await set_budget("2026-08", 500.0)
    b = await get_budget("2026-08")
    assert b == 500.0, f"Expected 500.0 got {b}"
    print(f"SQLite DB          OK  (budget=={b} EUR)")


asyncio.run(test_db())

print()
print("=" * 40)
print("All checks PASSED ✓")
