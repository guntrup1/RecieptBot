import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
CHANNEL_ID: str = os.getenv("TELEGRAM_CHANNEL_ID", "")
PERSON_1: str = os.getenv("PERSON_1_NAME", "Жора")
PERSON_2: str = os.getenv("PERSON_2_NAME", "Настя")
CURRENCY: str = os.getenv("CURRENCY", "€")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

DB_PATH: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "receipts.db")
