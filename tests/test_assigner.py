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


# ------------------------------------------------------------------ malformed / tricky model output
def test_clean_proposal_survives_non_dict_output():
    assert clean_proposal(["not", "a", "dict"], len(ITEMS), PEOPLE, "Amy").assignments == {}
    p = clean_proposal({"assignments": ["junk", None, {"item_index": 0, "people": ["Ben"]}]}, len(ITEMS), PEOPLE, "Amy")
    assert p.assignments == {0: ["Ben"]}


def test_people_given_as_a_string_is_one_person():
    p = clean_proposal({"assignments": [{"item_index": 0, "people": "Ben"}]}, len(ITEMS), PEOPLE, "Amy")
    assert p.assignments == {0: ["Ben"]} and p.new_people == []


def test_same_item_twice_merges_people():
    raw = {"assignments": [{"item_index": 3, "people": ["Ben"]}, {"item_index": 3, "people": ["Chen", "Ben"]}]}
    assert clean_proposal(raw, len(ITEMS), PEOPLE, "Amy").assignments == {3: ["Ben", "Chen"]}
    raw = {"assignments": [{"item_index": 3, "people": ["Ben"]}, {"item_index": 3, "people": ["everyone"]}]}
    assert clean_proposal(raw, len(ITEMS), PEOPLE, "Amy").assignments == {3: ["*"]}


def test_i_without_a_speaker_is_unclear_not_a_new_person():
    p = clean_proposal({"assignments": [{"item_index": 0, "people": ["I", "Ben"]}]}, len(ITEMS), PEOPLE, "")
    assert p.assignments == {0: ["Ben"]} and p.new_people == [] and p.unclear


def test_new_people_are_deduped_case_insensitively():
    raw = {"assignments": [{"item_index": 0, "people": ["Dana"]}, {"item_index": 1, "people": ["dana"]}]}
    p = clean_proposal(raw, len(ITEMS), PEOPLE, "Amy")
    assert p.new_people == ["Dana"] and p.assignments == {0: ["Dana"], 1: ["Dana"]}


def test_unclear_given_as_a_string():
    p = clean_proposal({"assignments": [], "unclear": "the thing"}, len(ITEMS), PEOPLE, "Amy")
    assert p.unclear == ["the thing"]
