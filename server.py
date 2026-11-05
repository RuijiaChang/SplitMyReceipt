"""SplitMyReceipt web server: JSON API + mobile web frontend.

Run:  uvicorn server:app --reload     (then open http://localhost:8000)

Bills are shared by link: everyone who opens /b/<id> sees the same bill and can
claim their own items. No accounts — a person is just a name on the bill.
Storage is one JSON file per bill in ./data (fine for a prototype; see README).
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

import assigner
from assigner import EVERYONE
import ai_client
from ai_client import AIError
from extractor import ExtractionError, extract_ai, extract_demo, list_samples
from splitter import Item, Receipt, compute_split, validate_receipt

ROOT = Path(__file__).parent

try:  # optional: read GEMINI_API_KEY etc. from a local .env file
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)
STATIC = ROOT / "static"
MAX_UPLOAD = 8 * 1024 * 1024
MAX_PIXELS = 50_000_000  # decoded pixels we'll hold in memory (~150 MB as RGB)
MAX_PEOPLE, MAX_ITEMS, MAX_NAME = 20, 60, 30
Image.MAX_IMAGE_PIXELS = None  # we enforce MAX_PIXELS ourselves, after letting JPEGs decode at reduced size

app = FastAPI(title="SplitMyReceipt")
_lock = threading.Lock()


# ------------------------------------------------------------------ helpers
def normalize_image(data: bytes) -> tuple[bytes, str]:
    """Any readable photo -> JPEG, longest side <= 2000px. Smaller uploads to the AI,
    and one format every provider accepts. Raises ExtractionError if unreadable."""
    try:
        img = Image.open(io.BytesIO(data))  # lazy: only the header is read here
        img.draft("RGB", (2000, 2000))  # JPEG: decode at 1/2, 1/4 or 1/8 size, so 200 MP phone photos are cheap
        if img.width * img.height > MAX_PIXELS:  # e.g. a tiny PNG that expands to gigabytes
            raise ExtractionError("That image is too large (too many pixels). Please use a normal photo.")
        img.load()
    except (UnidentifiedImageError, OSError):
        raise ExtractionError("That file isn't a readable image.")
    img = ImageOps.exif_transpose(img)  # phone photos are often stored sideways + an EXIF "rotate" tag
    img = img.convert("RGB")
    img.thumbnail((2000, 2000))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88)
    return out.getvalue(), "image/jpeg"


def clean_name(name: str) -> str:
    name = re.sub(r"[\x00-\x1f\x7f]", "", str(name or ""))  # control chars
    name = re.sub(r"\s+", " ", name).strip()[:MAX_NAME]
    if not name:
        raise HTTPException(400, "Please enter a name.")
    if name == EVERYONE:  # reserved: means "the whole table" on a claim
        raise HTTPException(400, "Please enter a real name.")
    return name


def receipt_json(r: Receipt) -> dict:
    return {"merchant": r.merchant, "is_receipt": r.is_receipt,
            "items": [{"name": i.name, "price_cents": i.price_cents} for i in r.items],
            "subtotal_cents": r.subtotal_cents, "tax_cents": r.tax_cents,
            "tip_cents": r.tip_cents, "total_cents": r.total_cents}


def issues_json(r: Receipt) -> list[dict]:
    return [{"level": i.level, "message": i.message} for i in validate_receipt(r)]


def bill_path(bill_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,20}", bill_id):
        raise HTTPException(404, "Bill not found.")
    return DATA / f"{bill_id}.json"


def load_bill(bill_id: str) -> dict:
    p = bill_path(bill_id)
    if not p.exists():
        raise HTTPException(404, "This bill doesn't exist (or the demo server was restarted).")
    return json.loads(p.read_text())


def save_bill(bill: dict) -> None:
    bill["version"] = bill.get("version", 0) + 1
    bill["updated"] = time.time()
    tmp = bill_path(bill["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(bill))
    tmp.replace(bill_path(bill["id"]))


def add_person(bill: dict, name: str) -> str:
    for p in bill["people"]:
        if p.lower() == name.lower():
            return p
    if len(bill["people"]) >= MAX_PEOPLE:
        raise HTTPException(400, f"A bill can have at most {MAX_PEOPLE} people.")
    bill["people"].append(name)
    return name


def bill_view(bill: dict) -> dict:
    """Bill + live split, as sent to every viewer."""
    r = Receipt(items=[Item(i["name"], i["price_cents"]) for i in bill["items"]],
                tax_cents=bill["tax_cents"], tip_cents=bill["tip_cents"], merchant=bill["merchant"])
    claims = [bill["people"] if EVERYONE in who else who for who in bill["claims"]]  # live "everyone"
    res = compute_split(r, claims, allow_unassigned=True, people=bill["people"])
    shares = []
    for s in res.shares:
        if s.name == bill["payer"]:
            paid_cents = s.total_cents  # the payer paid the restaurant
        else:
            paid_cents = bill["paid"].get(s.name)  # cents paid, or None
            if paid_cents is True:  # bills saved before amounts were recorded
                paid_cents = s.total_cents
        due = s.total_cents - (paid_cents or 0)
        shares.append({"name": s.name, "items": [{"name": n, "cents": c} for n, c in s.items],
                       "subtotal_cents": s.subtotal_cents, "tax_cents": s.tax_cents, "tip_cents": s.tip_cents,
                       "total_cents": s.total_cents, "paid_cents": paid_cents, "due_cents": due,
                       "paid": paid_cents is not None and due == 0})
    return {**{k: bill[k] for k in ("id", "merchant", "items", "tax_cents", "tip_cents", "people",
                                    "payer", "pay", "claims", "version")},
            "split": {"shares": shares, "unassigned": res.unassigned, "unassigned_cents": res.unassigned_cents,
                      "total_cents": res.total_cents, "subtotal_cents": res.subtotal_cents,
                      "complete": res.complete}}


# ------------------------------------------------------------------ receipt API
@app.get("/api/config")
def config():
    return {"ai": bool(ai_client.provider()), "provider": ai_client.label(),
            "samples": [p.name for p in list_samples()]}


@app.post("/api/extract")  # plain def: FastAPI runs it in a worker thread, so slow AI calls don't block polling
def extract(file: UploadFile | None = File(None), sample: str = Form(""), mode: str = Form("auto")):
    """Photo -> receipt JSON + validation issues. mode: auto | demo."""
    use_ai = mode != "demo" and ai_client.provider() is not None
    try:
        if file is not None:
            data = file.file.read(MAX_UPLOAD + 1)
            name, mime = file.filename or "upload", file.content_type or "image/jpeg"
        elif sample:
            match = [p for p in list_samples() if p.name == sample]
            if not match:
                raise ExtractionError("Unknown sample.")
            data, name, mime = match[0].read_bytes(), match[0].name, "image/png"
        else:
            raise ExtractionError("Please add a photo of the receipt.")
        if len(data) > MAX_UPLOAD:
            raise ExtractionError("That photo is larger than 8 MB. Please use a smaller one.")
        jpeg, jpeg_mime = normalize_image(data)
        if use_ai:
            receipt, notes = extract_ai(jpeg, jpeg_mime)
            used = ai_client.label()
        else:
            receipt, notes = extract_demo(name)
            used = "Demo"
    except ExtractionError as e:
        raise HTTPException(422, str(e))
    return {"receipt": receipt_json(receipt), "notes": notes, "mode": used, "issues": issues_json(receipt)}


class ItemIn(BaseModel):
    name: str = ""
    price_cents: int


class ReceiptIn(BaseModel):
    merchant: str = ""
    items: list[ItemIn] = Field(default_factory=list, max_length=MAX_ITEMS)
    subtotal_cents: int | None = None
    tax_cents: int = 0
    tip_cents: int = 0
    total_cents: int | None = None

    def to_receipt(self) -> Receipt:
        return Receipt(items=[Item(i.name.strip()[:60] or "(unnamed)", i.price_cents) for i in self.items],
                       tax_cents=self.tax_cents, tip_cents=self.tip_cents, subtotal_cents=self.subtotal_cents,
                       total_cents=self.total_cents, merchant=self.merchant.strip()[:60])


@app.post("/api/validate")
def validate(body: ReceiptIn):
    return {"issues": issues_json(body.to_receipt())}


# ------------------------------------------------------------------ bill API
class BillIn(BaseModel):
    receipt: ReceiptIn
    extra_tip_cents: int = 0  # tip added in the app when none was printed
    payer: str
    venmo: str = ""
    cashapp: str = ""


@app.post("/api/bills")
def create_bill(body: BillIn):
    r = body.receipt.to_receipt()
    errors = [i.message for i in validate_receipt(r) if i.level == "error"]
    if errors:
        raise HTTPException(400, errors[0])
    if body.extra_tip_cents < 0:
        raise HTTPException(400, "Tip cannot be negative.")
    payer = clean_name(body.payer)
    handle = lambda h: re.sub(r"[^A-Za-z0-9_\-]", "", h.lstrip("@$"))[:30]
    bill = {"id": secrets.token_urlsafe(6), "created": time.time(), "merchant": r.merchant,
            "items": [{"name": i.name, "price_cents": i.price_cents} for i in r.items],
            "tax_cents": r.tax_cents, "tip_cents": r.tip_cents + body.extra_tip_cents,
            "people": [payer], "payer": payer, "pay": {"venmo": handle(body.venmo), "cashapp": handle(body.cashapp)},
            "claims": [[] for _ in r.items], "paid": {}, "version": 0}
    with _lock:
        save_bill(bill)
    return {"id": bill["id"]}


@app.get("/api/bills/{bill_id}")
def get_bill(bill_id: str):
    return bill_view(load_bill(bill_id))


class PersonIn(BaseModel):
    name: str


@app.post("/api/bills/{bill_id}/people")
def join(bill_id: str, body: PersonIn):
    with _lock:
        bill = load_bill(bill_id)
        name = add_person(bill, clean_name(body.name))
        save_bill(bill)
    return {"name": name, "bill": bill_view(bill)}


class ClaimIn(BaseModel):
    item: int
    person: str
    on: bool


@app.post("/api/bills/{bill_id}/claim")
def claim(bill_id: str, body: ClaimIn):
    """Toggle one person on one item. Small atomic change, so two friends
    tapping at the same time never overwrite each other."""
    with _lock:
        bill = load_bill(bill_id)
        if not 0 <= body.item < len(bill["items"]):
            raise HTTPException(400, "No such item.")
        name = add_person(bill, clean_name(body.person))
        who = bill["claims"][body.item]
        if EVERYONE in who:
            if body.on:  # already included via "everyone"
                save_bill(bill)
                return bill_view(bill)
            who[:] = [p for p in bill["people"] if p != name]  # opt out: freeze everyone else
        elif body.on and name not in who:
            who.append(name)
        elif not body.on and name in who:
            who.remove(name)
        save_bill(bill)
    return bill_view(bill)


class SayIn(BaseModel):
    text: str = Field(max_length=600)
    speaker: str = ""


@app.post("/api/bills/{bill_id}/assign-text")
def assign_text(bill_id: str, body: SayIn):
    """Spoken/typed sentence -> PROPOSED assignments. Nothing is saved here."""
    bill = load_bill(bill_id)
    items = [i["name"] for i in bill["items"]]
    speaker = body.speaker.strip()[:MAX_NAME]
    if not body.text.strip():
        raise HTTPException(400, "Say or type who had what.")
    if ai_client.provider():
        try:
            prop, used = assigner.assign_ai(body.text, items, bill["people"], speaker), ai_client.label()
        except AIError as e:
            raise HTTPException(503, str(e))
    else:
        prop, used = assigner.assign_rules(body.text, items, bill["people"], speaker), "Demo"
    return {**prop.to_json(), "mode": used}


class AssignmentIn(BaseModel):
    item: int
    people: list[str]


class ApplyIn(BaseModel):
    assignments: list[AssignmentIn]


@app.post("/api/bills/{bill_id}/apply")
def apply(bill_id: str, body: ApplyIn):
    """Apply a confirmed proposal: each mentioned item gets exactly these people."""
    with _lock:
        bill = load_bill(bill_id)
        for a in body.assignments:
            if 0 <= a.item < len(bill["items"]):
                if EVERYONE in a.people:
                    bill["claims"][a.item] = [EVERYONE]
                else:
                    bill["claims"][a.item] = list(dict.fromkeys(add_person(bill, clean_name(p)) for p in a.people))
        save_bill(bill)
    return bill_view(bill)


class PaidIn(BaseModel):
    person: str
    paid: bool


@app.post("/api/bills/{bill_id}/paid")
def mark_paid(bill_id: str, body: PaidIn):
    with _lock:
        bill = load_bill(bill_id)
        if body.person not in bill["people"]:
            raise HTTPException(400, "That person isn't on this bill.")
        if body.paid:  # record the amount, so a later change to their share shows up as still due
            share = next(s for s in bill_view(bill)["split"]["shares"] if s["name"] == body.person)
            bill["paid"][body.person] = share["total_cents"]
        else:
            bill["paid"].pop(body.person, None)
        save_bill(bill)
    return bill_view(bill)


# ------------------------------------------------------------------ frontend
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/samples", StaticFiles(directory=ROOT / "samples"), name="samples")


@app.get("/")
@app.get("/b/{bill_id}")
def index(bill_id: str | None = None):
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
