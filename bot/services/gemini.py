"""
AI service — OCR receipts via Gemini, and analyse voice via Groq + Gemini.
"""

from __future__ import annotations

import asyncio
import json
import logging
import io
import re
from concurrent.futures import ThreadPoolExecutor

import google.generativeai as genai
import PIL.Image
from groq import Groq

from bot.config import GEMINI_API_KEY, GROQ_API_KEY, GEMINI_MODEL, PERSON_1, PERSON_2, CURRENCY

logger = logging.getLogger(__name__)

# Configure APIs once at import time
genai.configure(api_key=GEMINI_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

_executor = ThreadPoolExecutor(max_workers=4)

# ─── Prompts ──────────────────────────────────────────────────────────────────

RECEIPT_PROMPT = f"""
You are a receipt parser. Analyse the receipt image and extract ALL information.
Return ONLY valid JSON with no markdown, no code fences, no explanation.

Required format:
{{
  "date": "DD.MM.YYYY",
  "store": "store name",
  "items": [
    {{"name": "item name", "quantity": 1, "price": 0.00}}
  ],
  "total": 0.00,
  "receipt_hash": "A unique identifier for this receipt (e.g. Fiscal Number, Transaction ID, or a strict string like 'Date_Time_Store_Total' if no explicit ID exists). Must be perfectly unique for deduplication."
}}

Rules:
- date: extract from receipt. If missing use today's date format.
- store: exact name from receipt, or "Unknown" if unreadable.
- items: list every line item on the receipt.
- total: final amount paid (look for "TOTAL", "СУММА", "ПІДСУМОК", "SUMME", etc.)
- All prices in {CURRENCY}.
- If you cannot read a field, use null.
"""

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clean_json(text: str) -> str:
    """Strip markdown code fences and extract the JSON object/array."""
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("```").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group() if match else text

def _parse_json(text: str) -> dict:
    try:
        return json.loads(_clean_json(text))
    except json.JSONDecodeError:
        logger.warning("Failed to parse AI JSON response: %s", text[:300])
        return {}

import time

# ─── Sync AI calls (run inside executor) ──────────────────────────────────────

def _with_retries(func):
    """Decorator to retry Gemini API calls if rate limited (429 ResourceExhausted)."""
    def wrapper(*args, **kwargs):
        for attempt in range(5):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if "429" in str(e) or "exhausted" in str(e).lower() or "quota" in str(e).lower():
                    logger.warning("Rate limit hit, waiting 15s... (Attempt %s/5)", attempt + 1)
                    time.sleep(15)
                elif attempt == 4:
                    raise
                else:
                    logger.warning("Gemini error: %s. Retrying in 5s...", e)
                    time.sleep(5)
        raise RuntimeError("Max retries exceeded")
    return wrapper

@_with_retries
def _analyse_receipt_sync(image_bytes: bytes) -> dict:
    model = genai.GenerativeModel(GEMINI_MODEL)
    img = PIL.Image.open(io.BytesIO(image_bytes))
    response = model.generate_content([RECEIPT_PROMPT, img])
    data = _parse_json(response.text)
    return {
        "date": data.get("date"),
        "store": data.get("store", "Unknown"),
        "items": data.get("items", []),
        "total": float(data.get("total") or 0),
        "receipt_hash": data.get("receipt_hash", "unknown"),
    }

def _transcribe_voice_sync(audio_path: str) -> str:
    # Separated transcription so we don't call Groq 30 times for the same file in batch mode
    with open(audio_path, "rb") as audio_file:
        transcription_obj = groq_client.audio.transcriptions.create(
            file=("voice.ogg", audio_file.read()),
            model="whisper-large-v3",
            response_format="json",
        )
    return transcription_obj.text.strip()

@_with_retries
def _analyse_voice_sync(audio_path_or_transcription: str, receipt_data: dict, is_transcription: bool = False) -> dict:
    if is_transcription:
        transcription = audio_path_or_transcription
    else:
        transcription = _transcribe_voice_sync(audio_path_or_transcription)
        logger.info("Groq Transcription: %s", transcription)

    model = genai.GenerativeModel(GEMINI_MODEL)
    receipt_json = json.dumps(receipt_data, ensure_ascii=False)
    
    prompt = f"""
You are analysing a voice-note transcription about a shared grocery budget.
The two people sharing the budget are: {PERSON_1} and {PERSON_2}.

Receipt data (JSON):
{receipt_json}

Voice message transcription (General rules for multiple receipts, or specific to this one):
"{transcription}"

Task:
1. Read the transcription carefully.
2. Identify which items from THIS SPECIFIC receipt were PERSONAL purchases (not shared).
3. Determine who bought them ({PERSON_1} or {PERSON_2}) and how much they cost.

Return ONLY valid JSON format:
{{
  "personal_expenses": [
    {{"person": "{PERSON_1}", "item": "item name", "amount": 0.00}},
    {{"person": "{PERSON_2}", "item": "item name", "amount": 0.00}}
  ]
}}
If no personal purchases apply to this receipt, return: {{"personal_expenses": []}}
"""
    
    analyse_response = model.generate_content([prompt])
    result = _parse_json(analyse_response.text)

    return {
        "transcription": transcription,
        "personal_expenses": result.get("personal_expenses", []),
    }

# ─── Public async API ─────────────────────────────────────────────────────────

async def analyse_receipt(image_bytes: bytes) -> dict:
    """Analyse a receipt image and return structured data using Gemini."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _analyse_receipt_sync, image_bytes)

async def transcribe_voice(audio_path: str) -> str:
    """Only transcribe the voice note (Groq)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _transcribe_voice_sync, audio_path)

async def analyse_voice(audio_path_or_transcription: str, receipt_data: dict, is_transcription: bool = False) -> dict:
    """Extract personal expenses via Gemini (transcribes first if not already done)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _analyse_voice_sync, audio_path_or_transcription, receipt_data, is_transcription)
