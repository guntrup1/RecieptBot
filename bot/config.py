import os
from dotenv import load_dotenv

load_dotenv()

# Support both naming conventions (Railway uses short names)
BOT_TOKEN: str    = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY: str   = os.getenv("GROQ_API_KEY", "")
CHANNEL_ID: str     = os.getenv("TELEGRAM_CHANNEL_ID", "")
PERSON_1: str       = os.getenv("PERSON_1") or os.getenv("PERSON_1_NAME", "Жора")
PERSON_2: str       = os.getenv("PERSON_2") or os.getenv("PERSON_2_NAME", "Настя")
CURRENCY: str       = os.getenv("CURRENCY", "€")
GEMINI_MODEL: str   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
DATABASE_URL: str   = os.getenv("DATABASE_URL", "")

# SQLite path (used only when DATABASE_URL is not set)
DB_PATH: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "receipts.db")
