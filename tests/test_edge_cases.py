"""Regression tests for edge cases found in review."""
import io
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
for _k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "AI_PROVIDER"):
    os.environ.pop(_k, None)

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

import server  # noqa: E402
from splitter import Item, Receipt, compute_split, validate_receipt  # noqa: E402

c = TestClient(server.app)
RECEIPT = {"items": [{"name": "Fries", "price_cents": 900}, {"name": "Soup", "price_cents": 600}], "tax_cents": 100}


def new_bill(receipt=RECEIPT):
    return c.post("/api/bills", json={"receipt": receipt, "payer": "Amy"}).json()["id"]


def shares(view):
    return {s["name"]: s for s in view["split"]["shares"]}


# ---------------------------------------------------------------- 1. reserved names
def test_star_is_not_a_valid_person_name():
    bid = new_bill()
    assert c.post(f"/api/bills/{bid}/people", json={"name": "*"}).status_code == 400
    assert c.post(f"/api/bills/{bid}/claim", json={"item": 1, "person": " * ", "on": True}).status_code == 400
    assert c.post(f"/api/bills/{bid}/apply", json={"assignments": [{"item": 0, "people": ["Ben", "*"]}]}).json()[
        "claims"][0] == ["*"]  # "*" inside a proposal still means everyone


def test_control_characters_are_stripped_from_names():
    bid = new_bill()
    r = c.post(f"/api/bills/{bid}/people", json={"name": "\x00unclaimed"}).json()
    assert r["name"] == "unclaimed"
    v = c.post(f"/api/bills/{bid}/claim", json={"item": 0, "person": "\x00unclaimed", "on": True}).json()
    assert shares(v)["unclaimed"]["subtotal_cents"] == 900


# ---------------------------------------------------------------- 2. paid, then the amount changes
def test_paid_flag_resets_when_share_changes():
    bid = new_bill()
    c.post(f"/api/bills/{bid}/claim", json={"item": 0, "person": "Ben", "on": True})
    v = c.post(f"/api/bills/{bid}/paid", json={"person": "Ben", "paid": True}).json()
    paid_amount = shares(v)["Ben"]["total_cents"]
    assert shares(v)["Ben"]["paid"] and shares(v)["Ben"]["due_cents"] == 0

    v = c.post(f"/api/bills/{bid}/claim", json={"item": 1, "person": "Ben", "on": True}).json()
    ben = shares(v)["Ben"]
    assert not ben["paid"]
    assert ben["paid_cents"] == paid_amount
    assert ben["due_cents"] == ben["total_cents"] - paid_amount > 0

    v = c.post(f"/api/bills/{bid}/paid", json={"person": "Ben", "paid": True}).json()
    assert shares(v)["Ben"]["paid"] and shares(v)["Ben"]["due_cents"] == 0


def test_payer_is_always_paid():
    bid = new_bill()
    v = c.post(f"/api/bills/{bid}/claim", json={"item": 0, "person": "Amy", "on": True}).json()
    assert shares(v)["Amy"]["paid"] and shares(v)["Amy"]["due_cents"] == 0


# ---------------------------------------------------------------- 3. discounts never make a share negative
def test_claimed_discount_bigger_than_own_items_spills_to_table():
    r = Receipt([Item("Pasta", 2000), Item("Salad", 500), Item("Coupon", -1500)], tax_cents=200)
    res = compute_split(r, [["Amy"], ["Ben"], ["Ben"]])
    by = {s.name: s for s in res.shares}
    assert by["Ben"].subtotal_cents == 0 and by["Ben"].total_cents == 0
    assert by["Amy"].subtotal_cents == 1000
    assert sum(s.total_cents for s in res.shares) == 2000 + 500 - 1500 + 200
    assert sum(c for _, c in by["Ben"].items) == by["Ben"].subtotal_cents  # item lines still add up


def test_unclaimed_discount_is_shared_and_not_blocking():
    r = Receipt([Item("Pasta", 2000), Item("Salad", 1000), Item("Coupon", -600)])
    res = compute_split(r, [["Amy"], ["Ben"], []])  # strict mode: must not raise
    by = {s.name: s for s in res.shares}
    assert res.complete and res.unassigned == []
    assert by["Amy"].subtotal_cents == 1600 and by["Ben"].subtotal_cents == 800


def test_live_view_has_no_negative_totals():
    bid = new_bill({"items": [{"name": "Pasta", "price_cents": 2000}, {"name": "Coupon", "price_cents": -1500}],
                    "tax_cents": 200})
    c.post(f"/api/bills/{bid}/claim", json={"item": 0, "person": "Amy", "on": True})
    v = c.post(f"/api/bills/{bid}/claim", json={"item": 1, "person": "Ben", "on": True}).json()
    assert all(s["total_cents"] >= 0 for s in v["split"]["shares"])
    assert v["split"]["complete"]
    assert sum(s["total_cents"] for s in v["split"]["shares"]) == v["split"]["total_cents"] == 700


def test_discounts_larger_than_items_are_rejected():
    r = Receipt([Item("Pasta", 1000), Item("Coupon", -1500)], total_cents=-500)
    assert any(i.level == "error" for i in validate_receipt(r))


# ---------------------------------------------------------------- 5. EXIF orientation
def test_phone_photo_is_rotated_upright():
    img = Image.new("RGB", (400, 200), "white")  # stored landscape...
    exif = Image.Exif()
    exif[0x0112] = 6  # ...but the camera says "rotate 90° to display"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    jpeg, _ = server.normalize_image(buf.getvalue())
    assert Image.open(io.BytesIO(jpeg)).size == (200, 400)


# ---------------------------------------------------------------- 6. a slow AI call must not freeze other requests
def test_slow_extraction_does_not_block_other_requests(monkeypatch):
    import ai_client
    import extractor

    def slow_ai(image_bytes, mime_type):
        time.sleep(1.5)
        return Receipt([Item("x", 100)]), ""

    monkeypatch.setenv("OPENAI_API_KEY", "server-key")
    monkeypatch.setattr(server, "extract_ai", slow_ai)
    assert ai_client.provider() == "openai" and extractor  # AI path is taken
    bid = new_bill()
    with open(os.path.join(os.path.dirname(__file__), "..", "samples", "1_lulas_kitchen.png"), "rb") as f:
        photo = f.read()

    with TestClient(server.app) as shared:  # one event loop for both requests, like uvicorn
        t = threading.Thread(target=lambda: shared.post("/api/extract", files={"file": ("p.png", photo, "image/png")}))
        t.start()
        time.sleep(0.4)
        start = time.monotonic()
        assert shared.get(f"/api/bills/{bid}").status_code == 200
        waited = time.monotonic() - start
        t.join()
    assert waited < 0.5, f"bill poll waited {waited:.2f}s behind a slow extraction"


def test_gemini_client_has_a_timeout(monkeypatch):
    from google import genai

    import ai_client
    seen = {}
    real = genai.Client

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(genai, "Client", spy)
    ai_client._gemini_call("k", "p", {"type": "object"}, None)
    timeout = getattr(seen.get("http_options"), "timeout", None)
    assert timeout and timeout <= 60_000


# ---------------------------------------------------------------- 4. images with huge pixel dimensions
def test_decompression_bomb_is_a_friendly_422_not_a_500():
    buf = io.BytesIO()
    Image.new("1", (20000, 20000)).save(buf, "PNG")  # ~50 KB file, 400 megapixels
    assert len(buf.getvalue()) < server.MAX_UPLOAD
    r = c.post("/api/extract", files={"file": ("big.png", buf.getvalue(), "image/png")})
    assert r.status_code == 422 and "too large" in r.json()["detail"]


def test_high_megapixel_phone_jpeg_still_works():
    buf = io.BytesIO()
    Image.new("L", (16320, 12240), 200).save(buf, "JPEG")  # 200 MP, like a phone's high-res mode
    jpeg, _ = server.normalize_image(buf.getvalue())
    assert max(Image.open(io.BytesIO(jpeg)).size) <= 2000
