# 🧾 SplitMyReceipt

Snap the receipt, share one link, and everyone taps what they ate — or one person just *says* who had what. Each friend sees their exact share (tax and tip included) and pays you with one tap. No app download, no sign-up.

**Live demo:** `<add your Render link here>` — open it on your phone.

## The problem

After a group meal one person pays, then has to (1) find out who had what, usually by asking around in a group chat, (2) do the math, including tax and tip, and (3) chase everyone for money. Splitting evenly is unfair when orders differ; splitting exactly is slow and error-prone.

Existing apps (Splitwise, Tab, Forks, SplitBill AI) already scan receipts. In their App Store reviews people complain about misread receipts (subtotal/tax treated as items, a phantom tip, tax recorded as $0), features behind paywalls, and friends having to install the app to join. SplitMyReceipt focuses on: **zero friction for friends** (a web link), **fast assignment** (voice), and **numbers you can trust** (AI output is checked against the receipt's own totals).

## Core workflow

1. **Payer snaps the receipt.** The AI (OpenAI or Gemini) reads items, tax, tip, service charges/fees and total into a fixed JSON schema. A printed "suggested tip" table is not treated as a tip, and fee or gratuity lines the AI lists as dishes are moved out of the items by code.
2. **Check.** Items are cross-checked against the printed subtotal and total; mismatches, non-receipts and odd tax are flagged, and every line is editable. A tip can be added if none was printed.
3. **Share the link.** Friends open `/b/<id>`, pick or type their name, and tap the dishes they had. Everyone's screen updates live.
4. **Or say it.** "I had the kung pao chicken, Ben got the chow fun, we all shared the dumplings." The AI maps the sentence to items and people; the app shows the proposal and **nothing changes until you tap Apply**. "Everyone" is stored as *the whole table*, so friends who join later are included automatically.
5. **Pay.** When every item is claimed, each friend gets "Pay Amy $28.43" → opens Venmo or Cash App with the amount filled in (or copy the amount for Zelle), then taps "I've paid". The payer sees who still owes and can send a reminder.

### Where AI is used — and where it isn't

| Task | How | Why |
|---|---|---|
| Read the receipt photo | OpenAI or Gemini, strict JSON Schema output | Photos are messy; rules can't do this |
| Understand "who had what" speech | Browser speech-to-text → AI maps text to item indexes | Natural language, nicknames, English/Chinese |
| Check the reading | Plain code: items vs subtotal, sum vs total, tip missing from the total (= only suggested) | The receipt's printed totals are a free checksum |
| All money math | Plain code, integer cents, largest-remainder rounding | AI arithmetic isn't reliable; shares must add up exactly |
| Apply anything to the bill | Only after the user confirms | AI proposes, people decide |

## Run locally

Python 3.10+.

```bash
pip install -r requirements.txt
uvicorn server:app --reload        # open http://localhost:8000
pytest -q                          # 76 tests: money logic, parser, API flow, AI providers, retry/fallback, edge cases
```

Or with Docker (bills are kept in the `smr-data` volume; add `--env-file .env` for AI mode):

```bash
docker build -t splitmyreceipt .
docker run --rm splitmyreceipt pytest -q          # run the tests in the image
docker run -d --name smr -p 8000:8000 -v smr-data:/data splitmyreceipt
```

To try multi-person claiming locally, open the bill link in a second browser (or a private window) and pick a different name. To test on your phone, run `uvicorn server:app --host 0.0.0.0` and open `http://<your-computer-ip>:8000` on the same Wi-Fi (voice input needs HTTPS or localhost, so use the deployed link for voice on a phone).

### AI modes

- **Demo mode (default, no key):** receipt reading is **mocked** — the three bundled sample images return pre-recorded extractions from `samples/*.json`. Voice/text assignment uses a simple **keyword matcher** instead of AI. Both are labeled in the UI ("Demo: AI mocked", "Demo matcher").
- **AI mode — OpenAI (default) or Gemini:** put a key in the server's environment. Keys live only on the server; the browser never sees them, and the app switches to AI mode automatically.

  | Provider | Key | Models tried in order (override) |
  |---|---|---|
  | OpenAI | `OPENAI_API_KEY` | `gpt-5.4-mini`, then `gpt-5.4-nano` (`OPENAI_MODELS`) |
  | Gemini | `GEMINI_API_KEY` | `gemini-flash-latest`, then `gemini-flash-lite-latest` (`GEMINI_MODELS`) |

  If both keys are set, OpenAI is used unless `AI_PROVIDER=gemini`. Both providers get the same strict JSON Schema, so the rest of the app doesn't care which one answered. Photos are converted to JPEG (max 2000 px) before sending, which keeps requests small and works for both. Note: OpenAI API usage is paid (no free tier for these models); Gemini has free keys at https://aistudio.google.com.

  Locally, copy `.env.example` to `.env` and fill in one key (`.env` is git-ignored), or export it in the shell:

  ```bash
  cp .env.example .env             # then edit .env
  # or: export OPENAI_API_KEY=sk-...   (Windows PowerShell: $env:OPENAI_API_KEY="sk-...")
  ```

  **When the AI is busy** (503 overloaded, 429 rate limit, timeouts — temporary, on the provider's side), the server retries the same model with a short backoff, then falls back to the next model in the list. Bad keys and bad requests fail immediately with a clear message. Only if every model is busy does the user see "…is overloaded right now… try again, or type it in yourself", and the receipt stays fully editable by hand.

## Sample data and expected results (all synthetic)

| Input | Shows | Expected |
|---|---|---|
| "Dinner for 3" — `1_lulas_kitchen.png` | Representative case | "✓ It all adds up: items $68.25 + tax $5.97 + tip $13.65 = $87.87" |
| "Blurry photo" — `2_golden_wok_blurry.png` | Difficult case: blurry, tilted; AI misreads Beef Chow Fun as $6.50 (really $16.50); no printed tip | ⚠️ "Items add up to $46.20 but the receipt subtotal says $56.20 (off by $10.00)…" → fix the price, warnings clear |
| "Not a receipt" — `3_not_a_receipt.png` | Invalid input | ⛔ "That doesn't look like a receipt" — cannot create a bill |

**Walkthrough with the blurry sample:** fix the price to 16.50, choose 18% tip ($10.12), payer "Amy". On the bill page type *"I had the kung pao chicken, everyone shared the dumplings and the rice"* → Match items → Apply. Open the link in a second browser as **Ben**, tap Beef Chow Fun; third browser as **Chen**, tap Hot & Sour Soup. Expected:

| Person | Owes |
|---|---|
| Amy (paid) | $27.73 |
| Ben | $28.43 |
| Chen | $15.92 |
| **Total** | **$72.08** = $56.20 food + $5.76 tax + $10.12 tip |

Other handled errors: non-image or corrupt file, photo over 8 MB, images with huge pixel counts (a tiny PNG that expands to gigabytes is rejected; a 200 MP phone JPEG is decoded at reduced size), sideways phone photos (EXIF rotation), your own photo in demo mode (explains a server key is needed), bad key / network error, an empty or refused AI answer ("OpenAI gave no answer (it declined: …)"), sentence that matches no items ("Couldn't match that…" with the unclear phrase shown), unknown bill link, microphone permission denied, browsers without speech recognition (typing still works).

## Project layout

```
server.py         FastAPI: receipt API, shared bills, voice-assign, paid status; serves the web app
ai_client.py      The single AI caller: OpenAI or Gemini, retries on 503/429/timeouts, model fallback, friendly errors
extractor.py      Receipt reading (prompt + JSON Schema) + demo mock
assigner.py       Sentence -> proposed assignments (AI, or keyword matcher in demo)
splitter.py       Validation + exact split (no AI); live preview while items are unclaimed
static/           Mobile web app: index.html, app.js (vanilla JS), style.css
samples/          Synthetic receipts + mocked extractions; make_samples.py regenerates them
tests/            pytest: splitter, assigner, AI client, end-to-end API, fees, edge-case regressions
Dockerfile        Container image (single worker, bills in a /data volume)
render.yaml       One-click deploy config for Render
```

## Deploy (free) on Render

1. Push this folder to a GitHub repo.
2. On https://render.com → **New → Blueprint** → pick the repo (uses `render.yaml`), or **New → Web Service** with build `pip install -r requirements.txt` and start `uvicorn server:app --host 0.0.0.0 --port $PORT`.
3. Add `OPENAI_API_KEY` (or `GEMINI_API_KEY`) under **Environment** for real AI; without one the deployed app runs in demo mode. Watch your spend: anyone with the link triggers AI calls on your key. On OpenAI you can set a monthly budget limit in the account's billing settings.

Note: on the free plan the service sleeps when idle (first load takes ~1 minute) and its disk is temporary, so bills disappear on restart. Fine for a prototype; see "Roadmap" (P2).

## Status

- **Implemented:** receipt reading (OpenAI or Gemini, switchable by env), validation + editing, service charges/fees, suggested-tip detection, tip, shareable bill link, live multi-person claiming, voice/text assignment with confirmation, live "everyone", exact proportional split (tax, tip and fees), discounts that never make a share negative, Venmo/Cash App deep links, paid tracking that notices when a share changes after paying, reminder message, retry + model fallback when the AI is overloaded or returns nothing, Docker image, 76 automated tests.
- **Mocked / simplified:** AI output in demo mode; keyword matcher instead of AI in demo mode; payments are deep links only (no money moves through the app, and "I've paid" is self-reported); identity is a name on the bill (no accounts: anyone with the link can claim or mark paid for anyone); storage is one JSON file per bill; live updates use polling every 2.5 s.

## Roadmap: features to add

Ordered by how much they improve trust in the numbers, then everyday use, then production readiness.

**P0: correctness and trust**

1. **Payer admin link.** A secret edit token in the creator's link that lets the payer fix a misread price or add an item after sharing, remove, rename or merge people, and lock the bill once settled. Right now nothing can be changed after the link is shared, and a typo'd or AI-invented name stays on the bill (and in "everyone") forever.
2. **Uneven and per-unit shares.** "Iced Tea ×2" should split into two units someone can each claim, and a dish should allow 2/3 – 1/3 shares. Today an item is always split evenly among the people who claimed it.
3. **AI accuracy evaluation.** A labeled set of real receipts (blurry, long, handwritten tip, service charge, foreign-language, tax-inclusive) with per-field accuracy for items, subtotal, tax, tip, fees and total. Use it to compare OpenAI and Gemini and to catch regressions when the prompt changes.
4. **CI.** GitHub Actions that builds the Docker image and runs pytest on every PR, plus browser end-to-end tests (Playwright) for claim → pay flows, including the stale-poll race that is currently only checked by hand.

**P1: everyday use**

5. **Copy the split to the group chat.** `format_summary()` in `splitter.py` already produces the text, but no endpoint or button exposes it.
6. **Live updates over Server-Sent Events** instead of 2.5 s polling: instant updates and fewer requests.
7. **Payer-confirmed payments.** The payer confirms money arrived, and the app prompts a refund when someone overpaid because their share went down.
8. **Locales.** Decimal commas (`12,50`), the receipt's currency instead of always `$`, and a Chinese UI (voice input already supports Chinese).
9. **Undo** after Apply and after a claim.
10. **More photo types:** HEIC from desktop uploads (`pillow-heif`), several photos for one long receipt, and retake guidance when the photo is cut off.
11. **Highlight uncertain fields.** Ask the model for per-field confidence and highlight low-confidence lines on the review screen.
12. **Demo samples** with a service charge and a suggested-tip table, so reviewers can see those checks without an API key.

**P2: production**

13. **A real database** (SQLite, then Postgres), bill expiry, and locking that works with several workers.
14. **Abuse and cost controls:** rate limits and spend caps on `/api/extract` and `/assign-text` (anyone with the site can trigger AI calls on the server's key), plus logs and metrics for AI latency, fallback rate and failure rate.
15. **Tax and tip rules:** tax-exempt or differently taxed items (e.g. alcohol), tax-inclusive (VAT) receipts, and a choice of tipping on pre-tax or pre-discount amounts.
16. **Group trips:** several receipts and several payers, with one net settlement at the end.

## Edge cases

✅ covered by automated tests · 🟡 handled, but only checked by hand · ❌ known gap, not handled yet

### Reading the receipt

| Case | Status |
|---|---|
| Not a receipt; blurry photo with a misread price (flagged against the printed subtotal) | ✅ |
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

### Editing numbers

| Case | Status |
|---|---|
| Negative tax, tip or fees (error); discounts larger than the items (error) | ✅ |
| Decimal comma: `12,50` is read as **$1,250.00** in both the browser and the server | ❌ |
| No upper bound on amounts; above 2⁵³ cents the browser silently loses precision | ❌ |
| More than 60 items: rejected, but the message says "Some of the numbers aren't valid" | ❌ |
| Validation responses arriving out of order on the review screen (an older result can overwrite a newer one) | ❌ |

### Splitting the money

| Case | Status |
|---|---|
| Shared item with leftover cents (10.00 / 3 → 3.34, 3.33, 3.33); tax, tip and fees add up exactly | ✅ |
| Live preview while items are unclaimed matches the final split | ✅ |
| Unclaimed discount (shared by the table, doesn't block "complete"); claimed discount bigger than the claimer's items (capped at $0, rest shared) | ✅ |
| Leftover cents always go to the people listed first (usually the payer) | ❌ small, consistent bias |
| "$X each" on a shared item uses rounding up, so it can differ by 1¢ from the actual split | ❌ display only |

### People and claims

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

### Voice and text assignment

| Case | Status |
|---|---|
| Out-of-range item index; "me" → the speaker; new people | ✅ |
| `people` as a string; the same item twice (merged); "I" with no known speaker; non-dict output | ✅ |
| Two receipt lines with the same name ("Coke", "Coke") can't be told apart | ❌ |
| Demo matcher: names with spaces ("Mary Ann") never match; "all" in "Ben had all the fries" means everyone | ❌ demo only |
| Microphone denied; browser without speech recognition | 🟡 |
| Voice input on iOS Safari and Android Chrome | 🟡 needs a real phone (HTTPS) |

### Paying

| Case | Status |
|---|---|
| Share changes after "I've paid": shows the amount still due, and Venmo/Cash App ask only for the difference | ✅ |
| The payer always counts as paid | ✅ |
| Share went down after paying (overpaid): the friend sees it, but the payer gets no refund prompt | ❌ |
| Venmo/Cash App links open the app with the amount filled in | 🟡 needs a real phone |
| Anyone with the link can mark anyone as paid | ❌ no auth (prototype) |

### Server and deployment

| Case | Status |
|---|---|
| Slow AI call doesn't block other requests; Gemini client has a timeout; retry, fallback, bad key fails fast | ✅ |
| Bills saved before fees or paid amounts existed still load | ✅ |
| Several workers: the in-process lock no longer serializes writes | ❌ run one worker |
| Render free plan: temporary disk, bills vanish on restart; no bill expiry | ❌ |
| A corrupt bill file returns a 500 | ❌ |
| No rate limit on AI endpoints (cost abuse) | ❌ |
| Browser storage blocked: the app asks your name on every visit | 🟡 works, just repetitive |

## Time spent & how AI was used

- Time spent: `<fill in>`
- AI use: `<fill in — which assistant you used and for what; how you checked it (tests, running the sample cases on phone-sized screens with several users, reading every file)>`
