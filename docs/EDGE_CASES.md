# Edge cases

[← Back to README](../README.md)

Every case the prototype was checked against, grouped by area.

✅ covered by automated tests · 🟡 handled, but only checked by hand · ❌ known gap, not handled yet

## Reading the receipt

| Case | Status |
|---|---|
| Not a receipt; misread price flagged against the printed subtotal | ✅ |
| Non-image or corrupt file; photo over 8 MB; your own photo in demo mode | ✅ |
| Tiny PNG that expands to hundreds of megapixels (rejected with 422) | ✅ |
| 200 MP phone JPEG (decoded at reduced size, still works) | ✅ |
| Sideways phone photo (EXIF orientation applied before sending) | ✅ |
| Empty answer, OpenAI refusal, or JSON that isn't an object (falls back to the next model, then a clear message) | ✅ |
| Service charge / delivery fee / gratuity listed as a dish (moved to fees or tip); "Tri-Tip Steak" stays a dish | ✅ |
| Printed tip not included in the total (warned as a possible suggested tip) | ✅ |
| **Handwritten tip when the printed total is the pre-tip amount:** the suggested-tip warning fires wrongly, and following it would drop a real tip | ❌ |
| Fee read both into `fees` and as a dish line (double counted; only caught by the total check) | ❌ |
| Fractional quantity (1.5 lb shows as "×1") | ❌ |
| Tax-inclusive (VAT) receipts outside the US | ❌ |
| Long receipt cut across several photos; HEIC upload from a desktop | ❌ |
| Text on the receipt that tries to instruct the model (prompt injection). Money is cross-checked against the printed totals, but `is_receipt` and names are not | ❌ |

## Editing numbers

| Case | Status |
|---|---|
| Negative tax, tip or fees (error); discounts larger than the items (error) | ✅ |
| Decimal comma: `12,50` is read as **$1,250.00** in both the browser and the server | ❌ |
| No upper bound on amounts; above 2⁵³ cents the browser silently loses precision | ❌ |
| More than 60 items: rejected, but the message says "Some of the numbers aren't valid" | ❌ |
| Validation responses arriving out of order on the review screen (an older result can overwrite a newer one) | ❌ |

## Splitting the money

| Case | Status |
|---|---|
| Shared item with leftover cents (10.00 / 3 → 3.34, 3.33, 3.33); tax, tip and fees add up exactly | ✅ |
| Live preview while items are unclaimed matches the final split | ✅ |
| Unclaimed discount (shared by the table, doesn't block "complete"); claimed discount bigger than the claimer's items (capped at $0, rest shared) | ✅ |
| Leftover cents always go to the people listed first (usually the payer) | ❌ small, consistent bias |
| "$X each" on a shared item uses rounding up, so it can differ by 1¢ from the actual split | ❌ display only |

## People and claims

| Case | Status |
|---|---|
| Name `*` rejected; control characters stripped | ✅ |
| "Everyone" includes people who join later; opting out freezes the rest | ✅ |
| Same name in different case is one person | ✅ |
| Stale poll answer arriving after your own tap (no longer undoes it on screen) | 🟡 browser repro |
| Two different people with the same name are merged into one | ❌ |
| People can't be removed or renamed; a mistaken name is charged for "everyone" items | ❌ |
| The payer is included in "everyone" even if they didn't eat | ❌ by design today, worth a toggle |
| Apply replaces claims that someone made by hand after the proposal was shown | ❌ |
| The 20-person limit can be filled with junk names | ❌ |

## Voice and text assignment

| Case | Status |
|---|---|
| Out-of-range item index; "me" → the speaker; new people | ✅ |
| `people` as a string; the same item twice (merged); "I" with no known speaker; non-dict output | ✅ |
| English and Chinese sentences, including "大家" for the whole table | 🟡 checked on the live deploy |
| Two receipt lines with the same name ("Coke", "Coke") can't be told apart | ❌ |
| Demo matcher: names with spaces ("Mary Ann") never match; "all" in "Ben had all the fries" means everyone | ❌ demo only |
| Microphone denied; browser without speech recognition (typing still works) | 🟡 |
| Voice input on iOS Safari and Android Chrome | 🟡 needs a real phone (HTTPS) |

## Paying

| Case | Status |
|---|---|
| Share changes after "I've paid": shows the amount still due, and Venmo/Cash App ask only for the difference | ✅ |
| The payer always counts as paid | ✅ |
| Share went down after paying (overpaid): the friend sees it, but the payer gets no refund prompt | ❌ |
| Venmo/Cash App links open the app with the amount filled in | 🟡 needs a real phone |
| Anyone with the link can mark anyone as paid | ❌ no auth (prototype) |
| With the pay options open, the "Everyone" list underneath can't be scrolled into view | ❌ layout |

## Server and deployment

| Case | Status |
|---|---|
| Slow AI call doesn't block other requests; Gemini client has a timeout; retry, fallback, bad key fails fast | ✅ |
| Bills saved before fees or paid amounts existed still load | ✅ |
| Unknown bill link shows "Bill not found" | ✅ |
| Several workers: the in-process lock no longer serializes writes | ❌ run one worker |
| Render free plan: temporary disk, bills vanish on restart or redeploy; no bill expiry | ❌ |
| A corrupt bill file returns a 500 | ❌ |
| A bill page left open across a redeploy keeps polling a bill that no longer exists, without saying so (taps then fail with "This bill doesn't exist") | ❌ |
| No rate limit on AI endpoints (cost abuse) | ❌ |
| Browser storage blocked: the app asks your name on every visit | 🟡 works, just repetitive |
