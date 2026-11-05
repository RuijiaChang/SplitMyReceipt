import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from assigner import assign_rules, clean_proposal  # noqa: E402

ITEMS = ["Spicy Chicken Sandwich", "Mushroom Risotto", "Caesar Salad", "Truffle Fries", "Iced Tea ×2", "Craft Beer"]
PEOPLE = ["Amy", "Ben", "Chen"]


def test_rules_map_people_and_items():
    p = assign_rules("I had the risotto, Ben got the chicken sandwich; everyone had the salad", ITEMS, PEOPLE, "Amy")
    assert p.assignments == {1: ["Amy"], 0: ["Ben"], 2: ["*"]}


def test_rules_report_unclear_parts():
    p = assign_rules("Chen had something weird", ITEMS, PEOPLE, "Amy")
    assert p.assignments == {} and p.unclear


def test_clean_proposal_drops_bad_model_output():
    raw = {"assignments": [{"item_index": 99, "people": ["Amy"]},      # index out of range
                           {"item_index": "1", "people": ["me", ""]},   # "me" -> speaker
                           {"item_index": 2, "people": ["dana"]}],      # new person
           "unclear": ["the thing"]}
    p = clean_proposal(raw, len(ITEMS), PEOPLE, "Ben")
    assert p.assignments == {1: ["Ben"], 2: ["dana"]}
    assert p.new_people == ["dana"] and p.unclear == ["the thing"]
