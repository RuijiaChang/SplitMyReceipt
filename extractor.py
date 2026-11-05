"""Receipt photo -> structured Receipt.

Two modes:
* AI mode: sends the image to OpenAI or Gemini (see ai_client.py) and asks for
  JSON that follows a fixed schema (structured output).
* Demo mode (MOCKED): for the bundled sample images, returns a pre-recorded
  extraction from samples/<name>.json, so reviewers can run the full workflow
  without an API key. Clearly labeled as mocked in the UI.
"""
from __future__ import annotations

import json
from pathlib import Path

from splitter import Item, Receipt, to_cents

SAMPLES_DIR = Path(__file__).parent / "samples"

PROMPT = """You are reading a photo of a restaurant or shop receipt.
Return JSON only, following the schema.

Rules:
- is_receipt: false if the image is not a receipt or bill (then leave items empty).
- items: one entry per purchased line. `price` is the LINE TOTAL in dollars
  (quantity already multiplied in). Include discounts/coupons as negative prices.
  Do NOT include subtotal, tax, tip, total, payment or change lines as items.
- subtotal, tax, tip, total: numbers as printed, or null if not printed.
  If there are several tax lines, add them together.
- Copy numbers exactly as printed. Never guess or invent a number; if a value is
  unreadable, use null and mention it in `notes`.
- notes: short description of anything unclear (blurry text, cut-off lines)."""


class ExtractionError(RuntimeError):
    pass


# ------------------------------------------------------------- parsing (pure)
def receipt_from_dict(data: dict) -> tuple[Receipt, str]:
    """Turn the model's (untrusted) JSON into a Receipt. Returns (receipt, notes)."""
    if not isinstance(data, dict):
        raise ExtractionError("The AI response was not a JSON object.")

    items = []
    for raw in data.get("items") or []:
        if not isinstance(raw, dict):
            continue
        cents = to_cents(raw.get("price"))
        if cents is None:
            continue  # unreadable line: validation will flag the mismatch
        qty = raw.get("quantity")
        name = str(raw.get("name") or "").strip()
        if isinstance(qty, (int, float)) and qty > 1 and name:
            name = f"{name} ×{int(qty)}"
        items.append(Item(name, cents))

    receipt = Receipt(
        items=items,
        tax_cents=to_cents(data.get("tax")) or 0,
        tip_cents=to_cents(data.get("tip")) or 0,
        subtotal_cents=to_cents(data.get("subtotal")),
        total_cents=to_cents(data.get("total")),
        merchant=str(data.get("merchant") or "").strip(),
        is_receipt=bool(data.get("is_receipt", True)),
    )
    return receipt, str(data.get("notes") or "")


# ------------------------------------------------------------- demo mode
def list_samples() -> list[Path]:
    return sorted(p for p in SAMPLES_DIR.glob("*.png") if p.with_suffix(".json").exists())


def extract_demo(image_name: str) -> tuple[Receipt, str]:
    """MOCKED extraction: pre-recorded JSON for a bundled sample image."""
    path = SAMPLES_DIR / (Path(image_name).stem + ".json")
    if not path.exists():
        raise ExtractionError(
            "Demo mode can only read the bundled sample receipts. "
            "To read your own photo, set OPENAI_API_KEY (or GEMINI_API_KEY) on the server (see README)."
        )
    return receipt_from_dict(json.loads(path.read_text()))


# ------------------------------------------------------------- AI mode
NUM_OR_NULL = {"type": ["number", "null"]}
RECEIPT_SCHEMA = {  # strict JSON Schema: same for OpenAI and Gemini
    "type": "object",
    "additionalProperties": False,
    "required": ["is_receipt", "merchant", "items", "subtotal", "tax", "tip", "total", "notes"],
    "properties": {
        "is_receipt": {"type": "boolean"},
        "merchant": {"type": "string"},
        "items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "quantity", "price"],
            "properties": {"name": {"type": "string"}, "quantity": NUM_OR_NULL, "price": {"type": "number"}},
        }},
        "subtotal": NUM_OR_NULL, "tax": NUM_OR_NULL, "tip": NUM_OR_NULL, "total": NUM_OR_NULL,
        "notes": {"type": "string"},
    },
}


def extract_ai(image_bytes: bytes, mime_type: str) -> tuple[Receipt, str]:
    from ai_client import AIError, generate_json

    try:
        data = generate_json(PROMPT, RECEIPT_SCHEMA, image=(image_bytes, mime_type))
    except AIError as e:
        raise ExtractionError(str(e)) from e
    return receipt_from_dict(data)
