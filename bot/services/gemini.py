"""
AI service — 100% Groq based. No Gemini required.
- Receipt OCR: Groq Llama 4 Vision (llama-4-scout-17b-16e-instruct)
- Voice transcription: Groq Whisper
- Voice analysis: Groq Llama 4 text
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

from groq import Groq

from bot.config import GROQ_API_KEY, PERSON_1, PERSON_2, CURRENCY

logger = logging.getLogger(__name__)

groq_client = Groq(api_key=GROQ_API_KEY)

_executor = ThreadPoolExecutor(max_workers=4)

# Vision model for receipt OCR
VISION_MODEL  = "meta-llama/llama-4-scout-17b-16e-instruct"
# Text model for voice analysis
TEXT_MODEL    = "llama3-70b-8192"
# Whisper model for transcription
WHISPER_MODEL = "whisper-large-v3"

# ─── Prompts ──────────────────────────────────────────────────────────────────

RECEIPT_PROMPT = f"""You are a receipt parser. Analyse the receipt image and extract ALL information.
Return ONLY valid JSON with no markdown, no code fences, no explanation.

Required format:
{{
  "date": "DD.MM.YYYY",
  "store": "store name",
  "items": [
    {{"name": "item name", "quantity": 1, "price": 0.00}}
  ],
  "total": 0.00,
  "receipt_hash": "unique id: use fiscal number, transaction ID, or 'Date_Time_Store_Total' if none available"
}}

Rules:
- date: extract from receipt. If missing use today's date.
- store: exact name from receipt, or "Unknown" if unreadable.
- items: list every line item on the receipt.
- total: final amount paid.
- All prices in {CURRENCY}.
- If you cannot read a field, use null."""

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clean_json(text: str) -> str:
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("```").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group() if match else text

def _parse_json(text: str) -> dict:
    try:
        return json.loads(_clean_json(text))
    except json.JSONDecodeError:
        logger.warning("Failed to parse AI JSON response: %s", text[:300])
        return {}

def _with_retries(func):
    """Retry on rate limit (429) errors with exponential backoff."""
    def wrapper(*args, **kwargs):
        for attempt in range(5):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                err = str(e).lower()
                if "429" in err or "rate_limit" in err or "quota" in err:
                    wait = 15 * (attempt + 1)
                    logger.warning("Rate limit hit, waiting %ss... (Attempt %s/5)", wait, attempt + 1)
                    time.sleep(wait)
                elif attempt == 4:
                    raise
                else:
                    logger.warning("Groq error: %s. Retrying in 5s...", e)
                    time.sleep(5)
        raise RuntimeError("Max retries exceeded")
    return wrapper

# ─── Sync AI calls (run inside executor) ──────────────────────────────────────

@_with_retries
def _analyse_receipt_sync(image_bytes: bytes) -> dict:
    """Use Groq Llama 4 Vision to parse a receipt image."""
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = groq_client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": RECEIPT_PROMPT,
                    },
                ],
            }
        ],
        max_tokens=2048,
    )

    text = response.choices[0].message.content or ""
    data = _parse_json(text)

    return {
        "date":         data.get("date"),
        "store":        data.get("store", "Unknown"),
        "items":        data.get("items", []),
        "total":        float(data.get("total") or 0),
        "receipt_hash": data.get("receipt_hash", "unknown"),
    }


def _transcribe_voice_sync(audio_path: str) -> str:
    """Transcribe a voice message using Groq Whisper."""
    with open(audio_path, "rb") as audio_file:
        result = groq_client.audio.transcriptions.create(
            file=("voice.ogg", audio_file.read()),
            model=WHISPER_MODEL,
            response_format="json",
        )
    return result.text.strip()


@_with_retries
def _analyse_voice_sync(
    audio_path_or_transcription: str,
    receipt_data: dict,
    is_transcription: bool = False,
) -> dict:
    """Analyse a voice note or its transcription to extract personal expenses."""
    if is_transcription:
        transcription = audio_path_or_transcription
    else:
        transcription = _transcribe_voice_sync(audio_path_or_transcription)
        logger.info("Groq Whisper transcription: %s", transcription)

    receipt_json = json.dumps(receipt_data, ensure_ascii=False)

    prompt = f"""You are analysing a voice-note transcription about a shared grocery budget.
The two people sharing the budget are: {PERSON_1} and {PERSON_2}.

Receipt data (JSON):
{receipt_json}

Voice message transcription:
"{transcription}"

Task:
1. Read the transcription carefully.
2. Identify which items from THIS receipt were PERSONAL purchases (not shared).
3. Determine who bought them ({PERSON_1} or {PERSON_2}) and how much they cost.

Return ONLY valid JSON:
{{
  "personal_expenses": [
    {{"person": "{PERSON_1}", "item": "item name", "amount": 0.00}}
  ]
}}
If no personal purchases apply, return: {{"personal_expenses": []}}"""

    response = groq_client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
    )
    text = response.choices[0].message.content or ""
    result = _parse_json(text)

    return {
        "transcription":      transcription,
        "personal_expenses":  result.get("personal_expenses", []),
    }

# ─── Public async API ─────────────────────────────────────────────────────────

async def analyse_receipt(image_bytes: bytes) -> dict:
    """Analyse a receipt image using Groq Vision."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _analyse_receipt_sync, image_bytes)

async def transcribe_voice(audio_path: str) -> str:
    """Transcribe voice using Groq Whisper."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _transcribe_voice_sync, audio_path)

async def analyse_voice(
    audio_path_or_transcription: str,
    receipt_data: dict,
    is_transcription: bool = False,
) -> dict:
    """Analyse voice note for personal expenses using Groq."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor,
        _analyse_voice_sync,
        audio_path_or_transcription,
        receipt_data,
        is_transcription,
    )
