"""Core money logic for SplitMyReceipt.

Deliberately has NO AI in it: everything here is deterministic and works in
integer cents, so every split adds up to the exact receipt total.

Rules
-----
* An item shared by N people is split evenly; leftover cents go to the first
  people in the list (so 10.00 / 3 -> 3.34, 3.33, 3.33).
* Discounts (negative lines) don't need claiming. Unclaimed ones come off everyone
  in proportion to what they ordered. A claimed discount can bring its claimers
  down to $0 but never below; whatever is left is shared by the table the same way.
* Fees (service charge, delivery fee, card surcharge…), tax and tip are allocated in proportion to each person's item subtotal,
  using the largest-remainder method so the shares sum exactly to the total.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


# ---------------------------------------------------------------- helpers
def to_cents(value) -> int | None:
    """Convert '12.5', 12.5, '$12.50' or None to integer cents (or None)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").strip()
        if value == "":
            return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite():
        return None
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt(cents: int | None) -> str:
    if cents is None:
        return "—"
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


# ---------------------------------------------------------------- models
@dataclass
class Item:
    name: str
    price_cents: int  # line total (quantity already applied)


@dataclass
class Receipt:
    items: list[Item]
    tax_cents: int = 0
    tip_cents: int = 0
    fees_cents: int = 0  # service charges and other fees, shared like tax
    subtotal_cents: int | None = None  # as printed on the receipt
    total_cents: int | None = None  # as printed on the receipt
    merchant: str = ""
    is_receipt: bool = True

    @property
    def items_sum_cents(self) -> int:
        return sum(i.price_cents for i in self.items)


@dataclass
class Issue:
    level: str  # "error" blocks splitting, "warning" asks the user to double-check
    message: str


@dataclass
class PersonShare:
    name: str
    items: list[tuple[str, int]] = field(default_factory=list)
    subtotal_cents: int = 0
    tax_cents: int = 0
    tip_cents: int = 0
    fees_cents: int = 0

    @property
    def total_cents(self) -> int:
        return self.subtotal_cents + self.tax_cents + self.tip_cents + self.fees_cents


@dataclass
class SplitResult:
    shares: list[PersonShare]
    subtotal_cents: int
    tax_cents: int
    tip_cents: int
    fees_cents: int = 0
    unassigned: list[str] = field(default_factory=list)  # item names nobody has claimed yet
    unassigned_cents: int = 0  # their price + their share of tax/tip

    @property
    def total_cents(self) -> int:
        return self.subtotal_cents + self.tax_cents + self.tip_cents + self.fees_cents

    @property
    def complete(self) -> bool:
        return not self.unassigned


class SplitError(ValueError):
    pass


# ---------------------------------------------------------------- validation
TOLERANCE = 1  # cents; receipts sometimes round per line


def validate_receipt(r: Receipt) -> list[Issue]:
    """Sanity-check an (AI-extracted, possibly user-edited) receipt."""
    issues: list[Issue] = []

    if not r.is_receipt:
        issues.append(Issue("error", "This image doesn't look like a receipt. Please upload a photo of a receipt."))
        return issues
    if not r.items:
        issues.append(Issue("error", "No items were found. Add the items manually or retake the photo."))
        return issues

    for it in r.items:
        if not it.name.strip():
            issues.append(Issue("warning", f"An item priced {fmt(it.price_cents)} has no name."))
        if it.price_cents == 0:
            issues.append(Issue("warning", f"“{it.name}” has a price of $0.00 — was it read correctly?"))
        elif it.price_cents < 0:
            issues.append(Issue("warning", f"“{it.name}” is negative ({fmt(it.price_cents)}); treated as a discount."))

    if r.tax_cents < 0 or r.tip_cents < 0 or r.fees_cents < 0:
        issues.append(Issue("error", "Tax, tip and fees cannot be negative."))

    items_sum = r.items_sum_cents
    if items_sum < 0:
        issues.append(Issue("error", "Discounts add up to more than the items. Please check the negative lines."))
    if r.subtotal_cents is not None and abs(items_sum - r.subtotal_cents) > TOLERANCE:
        issues.append(Issue(
            "warning",
            f"Items add up to {fmt(items_sum)} but the receipt subtotal says {fmt(r.subtotal_cents)} "
            f"(off by {fmt(abs(items_sum - r.subtotal_cents))}). An item may be missing or misread.",
        ))

    if r.total_cents is None:
        issues.append(Issue("warning", "No total was found on the receipt, so the sum can't be cross-checked."))
    else:
        computed = items_sum + r.tax_cents + r.tip_cents + r.fees_cents
        if r.tip_cents > 0 and abs(computed - r.tip_cents - r.total_cents) <= TOLERANCE:
            # Receipts often print a "suggested tip" guide; the total without it matches exactly.
            issues.append(Issue(
                "warning",
                f"The tip {fmt(r.tip_cents)} isn't included in the receipt total {fmt(r.total_cents)}. "
                "It may only be a suggested tip — clear it if it wasn't actually charged.",
            ))
        elif abs(computed - r.total_cents) > TOLERANCE:
            issues.append(Issue(
                "warning",
                f"Items + tax + tip{' + fees' if r.fees_cents else ''} = {fmt(computed)}, but the receipt total is {fmt(r.total_cents)} "
                f"(off by {fmt(abs(computed - r.total_cents))}). Please check the highlighted numbers.",
            ))

    if items_sum > 0 and r.tax_cents > items_sum * 0.15:
        issues.append(Issue("warning", f"Tax is {r.tax_cents / items_sum:.0%} of the subtotal, which is unusually high."))

    return issues


# ---------------------------------------------------------------- splitting
def split_evenly(amount: int, n: int) -> list[int]:
    if n <= 0:
        raise SplitError("Cannot split among zero people.")
    base, extra = divmod(amount, n)
    return [base + (1 if i < extra else 0) for i in range(n)]


def allocate_proportional(amount: int, weights: list[int]) -> list[int]:
    """Largest-remainder allocation: result sums exactly to `amount`."""
    if not weights:
        return []
    total_w = sum(weights)
    if total_w <= 0:
        return split_evenly(amount, len(weights))
    raw = [amount * w / total_w for w in weights]
    floors = [int(x // 1) for x in raw]
    leftover = amount - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-(raw[i] - floors[i]), i))
    for i in order[:leftover]:
        floors[i] += 1
    return floors


_UNCLAIMED = "\x00unclaimed"  # internal bucket for items nobody has claimed yet


def compute_split(receipt: Receipt, assignments: list[list[str]], *,
                  allow_unassigned: bool = False, people: list[str] | None = None) -> SplitResult:
    """assignments[i] = names of people who shared receipt.items[i].

    allow_unassigned=True gives a live preview while friends are still claiming:
    unclaimed items sit in a hidden bucket that also takes its share of tax/tip,
    so each person's number never jumps when someone else claims a dish.
    Once everything is claimed the result is identical to the strict mode.
    `people` lists everyone at the table so people with nothing yet still appear.
    """
    if len(assignments) != len(receipt.items):
        raise SplitError("Every item needs an assignment.")

    # Discounts (negative lines) never need claiming: unclaimed ones are shared by the whole table.
    unassigned = [it.name or "(unnamed)" for it, who in zip(receipt.items, assignments)
                  if it.price_cents >= 0 and not [p for p in who if p.strip()]]
    if unassigned and not allow_unassigned:
        raise SplitError("Not assigned to anyone yet: " + ", ".join(unassigned))

    shares: dict[str, PersonShare] = {p: PersonShare(p) for p in (people or [])}
    table_discount = 0  # cents (>= 0) to take off everyone in proportion to what they ordered
    for item, who in zip(receipt.items, assignments):
        who = list(dict.fromkeys(p.strip() for p in who if p.strip()))  # dedupe, keep order
        if not who and item.price_cents < 0:
            table_discount -= item.price_cents
            continue
        who = who or [_UNCLAIMED]
        portions = split_evenly(item.price_cents, len(who))
        for person, portion in zip(who, portions):
            s = shares.setdefault(person, PersonShare(person))
            label = item.name if len(who) == 1 else f"{item.name} (1/{len(who)})"
            s.items.append((label, portion))
            s.subtotal_cents += portion

    # A claimed discount can bring someone down to $0, never below: the rest goes to the table.
    for s in shares.values():
        if s.subtotal_cents < 0:
            s.items.append(("Rest of discount (shared by the table)", -s.subtotal_cents))
            table_discount -= s.subtotal_cents
            s.subtotal_cents = 0

    buckets = list(shares.values())
    if table_discount:
        weights = [s.subtotal_cents for s in buckets]
        if table_discount > sum(weights):
            raise SplitError("Discounts are larger than the items they apply to.")
        for s, d in zip(buckets, allocate_proportional(table_discount, weights)):
            if d:
                s.items.append(("Shared discount", -d))
                s.subtotal_cents -= d

    weights = [max(0, s.subtotal_cents) for s in buckets]
    for s, t in zip(buckets, allocate_proportional(receipt.tax_cents, weights)):
        s.tax_cents = t
    for s, t in zip(buckets, allocate_proportional(receipt.tip_cents, weights)):
        s.tip_cents = t
    for s, t in zip(buckets, allocate_proportional(receipt.fees_cents, weights)):
        s.fees_cents = t

    # Invariant: nobody's money gets lost or invented.
    assert sum(s.total_cents for s in buckets) == (receipt.items_sum_cents + receipt.tax_cents
                                                   + receipt.tip_cents + receipt.fees_cents)

    unclaimed = shares.pop(_UNCLAIMED, None)
    return SplitResult(
        [s for s in shares.values()], receipt.items_sum_cents, receipt.tax_cents, receipt.tip_cents,
        fees_cents=receipt.fees_cents,
        unassigned=unassigned, unassigned_cents=unclaimed.total_cents if unclaimed else 0,
    )


def format_summary(result: SplitResult, merchant: str = "", payer: str = "") -> str:
    """Plain text the user can paste into a group chat."""
    title = f"🧾 {merchant} split" if merchant else "🧾 Bill split"
    fees = f", fees {fmt(result.fees_cents)}" if result.fees_cents else ""
    lines = [title, f"Total {fmt(result.total_cents)} (tax {fmt(result.tax_cents)}, tip {fmt(result.tip_cents)}{fees})", ""]
    for s in result.shares:
        owes = "" if s.name == payer else (f" → pay {payer}" if payer else "")
        lines.append(f"• {s.name}: {fmt(s.total_cents)}{owes}")
        lines.append("    " + ", ".join(f"{n} {fmt(c)}" for n, c in s.items))
    lines += ["", "Tax, tip and fees shared in proportion to what each person ordered.", "— SplitMyReceipt"]
    return "\n".join(lines)
