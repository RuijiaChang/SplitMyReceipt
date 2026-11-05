"""Service charges / fees, and printed "suggested tip" lines that aren't really charged."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
for _k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "AI_PROVIDER"):
    os.environ.pop(_k, None)

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from extractor import PROMPT, RECEIPT_SCHEMA, receipt_from_dict  # noqa: E402
from splitter import Item, Receipt, compute_split, format_summary, validate_receipt  # noqa: E402

c = TestClient(server.app)


def base(**kw):
    d = {"is_receipt": True, "merchant": "M", "items": [{"name": "Pasta", "quantity": 1, "price": 20},
                                                       {"name": "Salad", "quantity": 1, "price": 10}],
         "subtotal": 30, "tax": 2.4, "tip": None, "fees": None, "total": 32.4, "notes": ""}
    d.update(kw)
    return d


# ---------------------------------------------------------------- extraction
def test_schema_and_prompt_know_about_fees_and_suggested_tips():
    assert "fees" in RECEIPT_SCHEMA["required"] and "fees" in RECEIPT_SCHEMA["properties"]
    assert "suggested" in PROMPT.lower() and "service charge" in PROMPT.lower()


def test_fees_are_read():
    r, _ = receipt_from_dict(base(fees=5.4, total=37.8))
    assert r.fees_cents == 540 and validate_receipt(r) == []


def test_old_extractions_without_fees_still_work():
    d = base()
    del d["fees"]
    assert receipt_from_dict(d)[0].fees_cents == 0


def test_fee_lines_listed_as_items_are_moved_to_fees():
    items = base()["items"] + [{"name": "18% Service Charge", "quantity": 1, "price": 5.4},
                               {"name": "Delivery fee", "quantity": 1, "price": 3}]
    r, notes = receipt_from_dict(base(items=items, total=40.8))
    assert [i.name for i in r.items] == ["Pasta", "Salad"]
    assert r.fees_cents == 840 and "Service Charge" in notes and "Delivery fee" in notes
    assert validate_receipt(r) == []


def test_gratuity_listed_as_an_item_is_moved_to_tip():
    items = base()["items"] + [{"name": "Gratuity (20%)", "quantity": 1, "price": 6}]
    r, notes = receipt_from_dict(base(items=items, total=38.4))
    assert [i.name for i in r.items] == ["Pasta", "Salad"] and r.tip_cents == 600 and "Gratuity" in notes


def test_dishes_that_merely_contain_tip_or_fee_words_stay_items():
    items = [{"name": "Tri-Tip Steak", "quantity": 1, "price": 24}, {"name": "Coffee", "quantity": 1, "price": 3}]
    r, _ = receipt_from_dict(base(items=items, subtotal=27, total=29.4))
    assert [i.name for i in r.items] == ["Tri-Tip Steak", "Coffee"] and r.fees_cents == 0 and r.tip_cents == 0


# ---------------------------------------------------------------- validation
def test_tip_not_in_printed_total_is_flagged_as_suggested():
    r = Receipt([Item("Pasta", 2000), Item("Salad", 1000)], tax_cents=240, tip_cents=540, total_cents=3240)
    msgs = [i.message for i in validate_receipt(r) if i.level == "warning"]
    assert any("suggested" in m.lower() for m in msgs)


def test_real_tip_inside_total_is_not_flagged():
    r = Receipt([Item("Pasta", 2000), Item("Salad", 1000)], tax_cents=240, tip_cents=540, total_cents=3780)
    assert validate_receipt(r) == []


def test_negative_fees_are_an_error():
    r = Receipt([Item("Pasta", 2000)], fees_cents=-100)
    assert any(i.level == "error" for i in validate_receipt(r))


# ---------------------------------------------------------------- splitting
def test_fees_are_shared_in_proportion_and_add_up():
    r = Receipt([Item("Pasta", 2000), Item("Salad", 1000)], tax_cents=240, fees_cents=601)
    res = compute_split(r, [["Amy"], ["Ben"]])
    by = {s.name: s for s in res.shares}
    assert by["Amy"].fees_cents == 401 and by["Ben"].fees_cents == 200
    assert res.fees_cents == 601 and res.total_cents == 3000 + 240 + 601
    assert sum(s.total_cents for s in res.shares) == res.total_cents
    assert "fees" in format_summary(res).lower()


# ---------------------------------------------------------------- API
def test_bill_with_fees_end_to_end():
    receipt = {"items": [{"name": "Pasta", "price_cents": 2000}, {"name": "Salad", "price_cents": 1000}],
               "tax_cents": 240, "fees_cents": 600, "total_cents": 3840}
    assert c.post("/api/validate", json=receipt).json()["issues"] == []
    bid = c.post("/api/bills", json={"receipt": receipt, "payer": "Amy"}).json()["id"]
    c.post(f"/api/bills/{bid}/claim", json={"item": 0, "person": "Amy", "on": True})
    v = c.post(f"/api/bills/{bid}/claim", json={"item": 1, "person": "Ben", "on": True}).json()
    assert v["fees_cents"] == 600 and v["split"]["total_cents"] == 3840
    assert sum(s["fees_cents"] for s in v["split"]["shares"]) == 600
    assert sum(s["total_cents"] for s in v["split"]["shares"]) == 3840


def test_bills_saved_before_fees_existed_still_load():
    bid = c.post("/api/bills", json={"receipt": {"items": [{"name": "A", "price_cents": 100}]}, "payer": "Amy"}).json()["id"]
    bill = server.load_bill(bid)
    del bill["fees_cents"]
    server.save_bill(bill)
    v = c.get(f"/api/bills/{bid}").json()
    assert v["fees_cents"] == 0 and v["split"]["total_cents"] == 100
