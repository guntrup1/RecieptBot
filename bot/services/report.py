"""
Report formatter — builds the structured text report for a receipt.
"""

from __future__ import annotations

from bot.config import CURRENCY


def build_report(
    receipt_data: dict,
    personal_expenses: list[dict],
    budget: float,
    spent_before: float,
) -> str:
    """
    Build the full HTML-formatted report string.

    Args:
        receipt_data:      Parsed receipt dict from Gemini OCR.
        personal_expenses: List of {person, item, amount} dicts.
        budget:            Monthly budget total (0 if not set).
        spent_before:      Amount already spent this month BEFORE this receipt.
    """
    date_str   = receipt_data.get("date") or "—"
    store      = receipt_data.get("store") or "Unknown"
    total      = float(receipt_data.get("total") or 0)
    items      = receipt_data.get("items") or []

    remaining  = budget - (spent_before + total) if budget > 0 else None

    lines: list[str] = [
        f"📅 <b>Дата:</b> {date_str}",
        f"🏪 <b>Магазин:</b> {store}",
        f"💸 <b>В сумме потрачено:</b> {total:.2f} {CURRENCY}",
    ]

    if remaining is not None:
        lines.append(f"💰 <b>Осталось:</b> {remaining:.2f} {CURRENCY}")
    else:
        lines.append("💰 <b>Осталось:</b> бюджет не установлен")

    lines.append("")
    lines.append("📝 <b>Детали (Вернуть):</b>")

    if personal_expenses:
        for exp in personal_expenses:
            person = exp.get("person", "")
            item_name = exp.get("item", "")
            amount = float(exp.get("amount") or 0)
            lines.append(f"  — {person}: {amount:.2f} {CURRENCY} (за {item_name})")
    else:
        lines.append("  Всё куплено в общий бюджет (личных трат нет).")

    return "\n".join(lines)
