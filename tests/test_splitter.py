import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from splitter import (  # noqa: E402
    Item, Receipt, SplitError, allocate_proportional, compute_split,
    format_summary, split_evenly, to_cents, validate_receipt,
)


def test_to_cents_parses_common_formats():
    assert to_cents("12.50") == 1250
    assert to_cents("$1,234.5") == 123450
    assert to_cents(0.1 + 0.2) == 30  # float noise is rounded away
    assert to_cents("abc") is None
    assert to_cents(None) is None


def test_split_evenly_keeps_every_cent():
    assert split_evenly(1000, 3) == [334, 333, 333]
    assert sum(split_evenly(1, 4)) == 1


def test_allocate_proportional_sums_exactly():
    assert sum(allocate_proportional(101, [1, 1, 1])) == 101
    assert allocate_proportional(500, [3000, 1000]) == [375, 125]
    assert allocate_proportional(10, [0, 0]) == [5, 5]


def make_receipt():
    items = [Item("Burger", 1500), Item("Salad", 1200), Item("Fries", 600)]
    return Receipt(items=items, tax_cents=330, tip_cents=600,
                   subtotal_cents=3300, total_cents=4230, merchant="Diner")


def test_representative_split():
    res = compute_split(make_receipt(), [["Amy"], ["Ben"], ["Amy", "Ben"]])
    by = {s.name: s for s in res.shares}
    assert by["Amy"].subtotal_cents == 1800
    assert by["Ben"].subtotal_cents == 1500
    assert by["Amy"].total_cents + by["Ben"].total_cents == 4230
    # tax/tip proportional: Amy ordered 18/33 of the food
    assert by["Amy"].tax_cents == 180 and by["Ben"].tax_cents == 150
    assert "Amy" in format_summary(res, "Diner", payer="Ben")


def test_unassigned_item_is_rejected():
    with pytest.raises(SplitError, match="Fries"):
        compute_split(make_receipt(), [["Amy"], ["Ben"], []])


def test_validation_clean_receipt_has_no_issues():
    assert validate_receipt(make_receipt()) == []


def test_validation_catches_total_mismatch():
    r = make_receipt()
    r.total_cents = 5230  # misread total
    assert any("receipt total" in i.message for i in validate_receipt(r))


def test_validation_catches_missing_item():
    r = make_receipt()
    r.items = r.items[:2]  # OCR dropped a line
    assert {i.level for i in validate_receipt(r)} == {"warning"}


def test_not_a_receipt_is_an_error():
    assert validate_receipt(Receipt(items=[], is_receipt=False))[0].level == "error"


def test_discount_line():
    r = Receipt(items=[Item("Pizza", 2000), Item("Coupon", -500)], tax_cents=150, total_cents=1650)
    res = compute_split(r, [["Amy", "Ben"], ["Amy", "Ben"]])
    assert sum(s.total_cents for s in res.shares) == 1650


def test_partial_preview_matches_final_when_complete():
    r = make_receipt()
    full = compute_split(r, [["Amy"], ["Ben"], ["Amy", "Ben"]])
    part = compute_split(r, [["Amy"], ["Ben"], ["Amy", "Ben"]], allow_unassigned=True)
    assert [s.total_cents for s in full.shares] == [s.total_cents for s in part.shares]
    assert part.complete


def test_partial_preview_keeps_unclaimed_bucket():
    r = make_receipt()
    part = compute_split(r, [["Amy"], [], []], allow_unassigned=True, people=["Amy", "Ben"])
    by = {s.name: s for s in part.shares}
    assert by["Ben"].total_cents == 0  # listed even with nothing yet
    assert part.unassigned == ["Salad", "Fries"]
    assert by["Amy"].total_cents + part.unassigned_cents == 4230
    # Amy's number is already final: claiming the rest won't change it
    done = compute_split(r, [["Amy"], ["Ben"], ["Ben"]])
    assert {s.name: s.total_cents for s in done.shares}["Amy"] == by["Amy"].total_cents
