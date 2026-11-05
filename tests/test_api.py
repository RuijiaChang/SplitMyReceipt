"""End-to-end API flow in demo mode (no AI key needed)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATA_DIR"] = tempfile.mkdtemp()
for _k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "AI_PROVIDER"):
    os.environ.pop(_k, None)

from fastapi.testclient import TestClient  # noqa: E402

from server import app  # noqa: E402

c = TestClient(app)


def make_bill(sample="1_lulas_kitchen.png", extra_tip=0):
    ex = c.post("/api/extract", data={"sample": sample}).json()
    bill = c.post("/api/bills", json={"receipt": ex["receipt"], "payer": "Amy", "venmo": "@amy-w",
                                      "extra_tip_cents": extra_tip}).json()
    return bill["id"]


def test_extract_clean_sample():
    ex = c.post("/api/extract", data={"sample": "1_lulas_kitchen.png"}).json()
    assert ex["mode"] == "Demo" and ex["issues"] == [] and len(ex["receipt"]["items"]) == 6


def test_extract_rejects_non_image_and_own_photo_in_demo():
    r = c.post("/api/extract", files={"file": ("x.png", b"not an image", "image/png")})
    assert r.status_code == 422 and "readable image" in r.json()["detail"]
    with open(os.path.join(os.path.dirname(__file__), "..", "samples", "3_not_a_receipt.png"), "rb") as f:
        r = c.post("/api/extract", files={"file": ("my_photo.png", f.read(), "image/png")})
    assert r.status_code == 422 and "Demo mode" in r.json()["detail"]


def test_not_a_receipt_cannot_become_a_bill():
    ex = c.post("/api/extract", data={"sample": "3_not_a_receipt.png"}).json()
    assert ex["issues"][0]["level"] == "error"
    r = c.post("/api/bills", json={"receipt": ex["receipt"], "payer": "Amy"})
    assert r.status_code == 400


def test_friends_claim_and_totals_add_up():
    bid = make_bill()
    c.post(f"/api/bills/{bid}/claim", json={"item": 0, "person": "Ben", "on": True})
    c.post(f"/api/bills/{bid}/claim", json={"item": 1, "person": "Amy", "on": True})
    v = c.post(f"/api/bills/{bid}/claim", json={"item": 2, "person": "Chen", "on": True}).json()
    assert v["people"] == ["Amy", "Ben", "Chen"] and not v["split"]["complete"]
    # voice sentence -> proposal -> apply
    prop = c.post(f"/api/bills/{bid}/assign-text",
                  json={"text": "everyone shared the fries and the iced tea, Ben had the beer", "speaker": "Amy"}).json()
    assert prop["mode"] == "Demo" and len(prop["assignments"]) == 3
    v = c.post(f"/api/bills/{bid}/apply", json={"assignments": prop["assignments"]}).json()
    s = v["split"]
    assert s["complete"] and sum(x["total_cents"] for x in s["shares"]) == 8787 == s["total_cents"]


def test_unclaim_and_paid():
    bid = make_bill()
    c.post(f"/api/bills/{bid}/claim", json={"item": 0, "person": "Ben", "on": True})
    v = c.post(f"/api/bills/{bid}/claim", json={"item": 0, "person": "Ben", "on": False}).json()
    assert v["claims"][0] == []
    v = c.post(f"/api/bills/{bid}/paid", json={"person": "Ben", "paid": True}).json()
    assert next(x for x in v["split"]["shares"] if x["name"] == "Ben")["paid"]
    assert v["pay"]["venmo"] == "amy-w"


def test_extra_tip_when_none_printed():
    bid = make_bill("2_golden_wok_blurry.png", extra_tip=1000)
    assert c.get(f"/api/bills/{bid}").json()["tip_cents"] == 1000


def test_unknown_bill_is_404():
    assert c.get("/api/bills/nope1234").status_code == 404


def test_everyone_includes_people_who_join_later():
    bid = make_bill()
    prop = c.post(f"/api/bills/{bid}/assign-text", json={"text": "we all shared the fries", "speaker": "Amy"}).json()
    c.post(f"/api/bills/{bid}/apply", json={"assignments": prop["assignments"]})
    v = c.post(f"/api/bills/{bid}/people", json={"name": "Ben"}).json()["bill"]
    fries = {s["name"]: s for s in v["split"]["shares"]}
    assert fries["Ben"]["subtotal_cents"] == 450 and fries["Amy"]["subtotal_cents"] == 450
    # Ben opts out of the shared fries -> Amy pays for them alone
    v = c.post(f"/api/bills/{bid}/claim", json={"item": 3, "person": "Ben", "on": False}).json()
    assert v["claims"][3] == ["Amy"]


def test_key_comes_only_from_server_env(monkeypatch):
    assert c.get("/api/config").json()["ai"] is False
    # a key sent by a browser is ignored: still demo mode
    r = c.post("/api/extract", data={"sample": "1_lulas_kitchen.png"}, headers={"X-Gemini-Key": "abc"})
    assert r.json()["mode"] == "Demo"
    monkeypatch.setenv("OPENAI_API_KEY", "server-key")
    assert c.get("/api/config").json() | {"samples": []} == {"ai": True, "provider": "OpenAI", "samples": []}


def test_own_photo_goes_through_ai_path(monkeypatch):
    import json as _json

    import ai_client
    seen = {}

    def fake_generate_json(prompt, schema, image=None):
        seen["mime"], seen["jpeg"] = image[1], image[0][:2] == b"\xff\xd8"
        return _json.load(open(os.path.join(os.path.dirname(__file__), "..", "samples", "1_lulas_kitchen.json")))

    monkeypatch.setenv("OPENAI_API_KEY", "server-key")
    monkeypatch.setattr(ai_client, "generate_json", fake_generate_json)
    with open(os.path.join(os.path.dirname(__file__), "..", "samples", "2_golden_wok_blurry.png"), "rb") as f:
        r = c.post("/api/extract", files={"file": ("IMG_0042.png", f.read(), "image/png")}).json()
    assert r["mode"] == "OpenAI" and r["issues"] == []
    assert seen == {"mime": "image/jpeg", "jpeg": True}  # PNG was converted to JPEG before sending
