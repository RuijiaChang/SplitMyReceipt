"""One sentence -> who had what.

"I had the risotto, Ben and Chen shared the fries, everyone had the beer"
    -> {item 1: [Amy], item 3: [Ben, Chen], item 5: [Amy, Ben, Chen]}

* AI mode (OpenAI or Gemini): the model maps the sentence to item indexes + names,
  returning JSON in a fixed schema. Works for messy speech, nicknames, Chinese/English mix.
* Demo mode: a small keyword matcher (no AI) so the feature runs without a key.
  It's deliberately simple and is labeled as such in the UI.

In both modes the result is only a PROPOSAL: the app shows it and the user
confirms before anything is applied. AI never changes the bill on its own.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


EVERYONE = "*"  # stored on a claim: "the whole table", including people who join later
_EVERYONE_WORDS = {"everyone", "everybody", "all", "all of us", "the table", "whole table", "大家", "所有人", "我们"}


@dataclass
class Proposal:
    assignments: dict[int, list[str]] = field(default_factory=dict)  # item index -> people
    new_people: list[str] = field(default_factory=list)
    unclear: list[str] = field(default_factory=list)  # parts of the sentence we couldn't map

    def to_json(self) -> dict:
        return {"assignments": [{"item": i, "people": p} for i, p in sorted(self.assignments.items())],
                "new_people": self.new_people, "unclear": self.unclear}


def clean_proposal(raw: dict, n_items: int, people: list[str], speaker: str) -> Proposal:
    """Validate untrusted model output: drop bad indexes, normalise names."""
    known = {p.lower(): p for p in people}
    prop = Proposal()
    for a in raw.get("assignments") or []:
        try:
            idx = int(a.get("item_index", a.get("item")))
        except (TypeError, ValueError):
            continue
        if not 0 <= idx < n_items:
            continue
        names = []
        for n in a.get("people") or []:
            n = str(n).strip()
            if not n:
                continue
            if n.lower() in _EVERYONE_WORDS or n == EVERYONE:
                names.append(EVERYONE)
                continue
            if n.lower() in {"i", "me", "我"} and speaker:
                n = speaker
            n = known.get(n.lower(), n[:30])
            if n.lower() not in known and n not in prop.new_people:
                prop.new_people.append(n)
            names.append(n)
        if EVERYONE in names:
            names = [EVERYONE]  # "everyone" already covers anyone else named
        if names:
            prop.assignments[idx] = list(dict.fromkeys(names))
    prop.unclear = [str(u) for u in (raw.get("unclear") or []) if str(u).strip()][:5]
    return prop


# ------------------------------------------------------------------ demo mode
ME = {"i", "me", "my", "mine", "myself", "我"}
ALL = {"everyone", "everybody", "all", "we", "us", "together", "table", "大家", "我们", "一起", "都"}
STOP = {"the", "a", "an", "and", "had", "have", "got", "ate", "drank", "shared", "split", "of", "with",
        "for", "x2", "x3", "large", "small", "order"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def assign_rules(text: str, items: list[str], people: list[str], speaker: str = "") -> Proposal:
    """Keyword matcher used in demo mode. Splits the sentence into clauses and,
    in each clause, links the people mentioned to the items mentioned."""
    prop = Proposal()
    clauses = [c.strip() for c in re.split(r"[.;,，。；!?\n]+|\bthen\b", text) if c.strip()]
    for clause in clauses:
        words, low = _words(clause), clause.lower()
        who = [p for p in people if p.lower() in words or (not p.isascii() and p in clause)]
        if (words & ME or "我" in clause) and speaker and speaker not in who:
            who.insert(0, speaker)
        if words & ALL or any(k in clause for k in ("大家", "我们", "一起")):
            who = [EVERYONE]
        hits = []
        for i, name in enumerate(items):
            keys = {w for w in _words(name) if len(w) >= 3 and w not in STOP}
            if keys & words or (not name.isascii() and name.split(" ")[0] in clause):
                hits.append(i)
        if hits and who:
            for i in hits:
                prop.assignments[i] = list(dict.fromkeys(who))
        elif hits or (who and low.strip()):
            prop.unclear.append(clause)
    return prop


# ------------------------------------------------------------------ AI mode
PROMPT = """People at a restaurant table are splitting a receipt. Map what the user said to receipt items.

Receipt items (index: name):
{items}

People at the table: {people}
The speaker (who "I"/"me"/"我" refers to): {speaker}

The user said: "{text}"

Return JSON:
- assignments: for each item the sentence mentions, item_index and the people who had it.
  "everyone"/"we all"/"大家" means the whole table: return people as ["everyone"] (people may still be joining). "shared"/"split" means each listed person had part.
  Match items by meaning, not exact words (e.g. "the beer" -> "Craft Beer", "饺子" -> "Veg Dumplings").
  Only include items that were actually mentioned. Never guess.
- unclear: short phrases you could not map to an item or person (empty list if none).
A name not in the list may be a new person; include it as said."""


ASSIGN_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["assignments", "unclear"],
    "properties": {
        "assignments": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["item_index", "people"],
            "properties": {"item_index": {"type": "integer"},
                           "people": {"type": "array", "items": {"type": "string"}}}}},
        "unclear": {"type": "array", "items": {"type": "string"}},
    },
}


def assign_ai(text: str, items: list[str], people: list[str], speaker: str) -> Proposal:
    from ai_client import generate_json

    prompt = PROMPT.format(items="\n".join(f"{i}: {n}" for i, n in enumerate(items)),
                           people=", ".join(people) or "(none yet)", speaker=speaker or "unknown",
                           text=text.replace('"', "'")[:600])
    return clean_proposal(generate_json(prompt, ASSIGN_SCHEMA), len(items), people, speaker)
