# 🧾 SplitMyReceipt

Snap the receipt, share one link, and everyone taps what they ate — or one person just *says* who had what. Each friend sees their exact share (tax and tip included) and pays you with one tap. No app download, no sign-up.

**Live demo:** `<add your Render link here>` — open it on your phone.

## The problem

After a group meal one person pays, then has to (1) find out who had what, usually by asking around in a group chat, (2) do the math, including tax and tip, and (3) chase everyone for money. Splitting evenly is unfair when orders differ; splitting exactly is slow and error-prone.

Existing apps (Splitwise, Tab, Forks, SplitBill AI) already scan receipts. In their App Store reviews people complain about misread receipts (subtotal/tax treated as items, a phantom tip, tax recorded as $0), features behind paywalls, and friends having to install the app to join. SplitMyReceipt focuses on: **zero friction for friends** (a web link), **fast assignment** (voice), and **numbers you can trust** (AI output is checked against the receipt's own totals).

## Core workflow

1. **Payer snaps the receipt.** The AI (OpenAI or Gemini) reads items, tax, tip and total into a fixed JSON schema.
2. **Check.** Items are cross-checked against the printed subtotal and total; mismatches, non-receipts and odd tax are flagged, and every line is editable. A tip can be added if none was printed.
3. **Share the link.** Friends open `/b/<id>`, pick or type their name, and tap the dishes they had. Everyone's screen updates live.
4. **Or say it.** "I had the kung pao chicken, Ben got the chow fun, we all shared the dumplings." The AI maps the sentence to items and people; the app shows the proposal and **nothing changes until you tap Apply**. "Everyone" is stored as *the whole table*, so friends who join later are included automatically.
5. **Pay.** When every item is claimed, each friend gets "Pay Amy $28.43" → opens Venmo or Cash App with the amount filled in (or copy the amount for Zelle), then taps "I've paid". The payer sees who still owes and can send a reminder.

### Where AI is used — and where it isn't

| Task | How | Why |
|---|---|---|
| Read the receipt photo | OpenAI or Gemini, strict JSON Schema output | Photos are messy; rules can't do this |
| Understand "who had what" speech | Browser speech-to-text → AI maps text to item indexes | Natural language, nicknames, English/Chinese |
| Check the reading | Plain code: items vs subtotal, sum vs total | The receipt's printed totals are a free checksum |
| All money math | Plain code, integer cents, largest-remainder rounding | AI arithmetic isn't reliable; shares must add up exactly |
| Apply anything to the bill | Only after the user confirms | AI proposes, people decide |

## Run locally

Python 3.10+.

```bash
pip install -r requirements.txt
uvicorn server:app --reload        # open http://localhost:8000
pytest -q                          # 49 tests: money logic, parser, API flow, AI providers, retry/fallback, edge cases
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

Other handled errors: non-image or corrupt file, photo over 8 MB, your own photo in demo mode (explains a server key is needed), bad key / network error, sentence that matches no items ("Couldn't match that…" with the unclear phrase shown), unknown bill link, microphone permission denied, browsers without speech recognition (typing still works).

## Project layout

```
server.py         FastAPI: receipt API, shared bills, voice-assign, paid status; serves the web app
ai_client.py      The single AI caller: OpenAI or Gemini, retries on 503/429/timeouts, model fallback, friendly errors
extractor.py      Receipt reading (prompt + JSON Schema) + demo mock
assigner.py       Sentence -> proposed assignments (AI, or keyword matcher in demo)
splitter.py       Validation + exact split (no AI); live preview while items are unclaimed
static/           Mobile web app: index.html, app.js (vanilla JS), style.css
samples/          Synthetic receipts + mocked extractions; make_samples.py regenerates them
tests/            pytest: splitter, assigner, end-to-end API
render.yaml       One-click deploy config for Render
```

## Deploy (free) on Render

1. Push this folder to a GitHub repo.
2. On https://render.com → **New → Blueprint** → pick the repo (uses `render.yaml`), or **New → Web Service** with build `pip install -r requirements.txt` and start `uvicorn server:app --host 0.0.0.0 --port $PORT`.
3. Add `OPENAI_API_KEY` (or `GEMINI_API_KEY`) under **Environment** for real AI; without one the deployed app runs in demo mode. Watch your spend: anyone with the link triggers AI calls on your key. On OpenAI you can set a monthly budget limit in the account's billing settings.

Note: on the free plan the service sleeps when idle (first load takes ~1 minute) and its disk is temporary, so bills disappear on restart. Fine for a prototype; see "Deferred".

## Implemented / mocked / deferred

- **Implemented:** receipt reading (OpenAI or Gemini, switchable by env), validation + editing, tip, shareable bill link, live multi-person claiming, voice/text assignment with confirmation, live "everyone", exact proportional split, Venmo/Cash App deep links, paid tracking, reminder message, retry + model fallback when the AI is overloaded, 36 automated tests.
- **Mocked / simplified:** AI output in demo mode; keyword matcher instead of AI in demo mode; payments are deep links only (no money moves through the app, no confirmation that a payment actually happened); identity is a name on the bill (no accounts — anyone with the link can claim for anyone); storage is JSON files; live updates use polling every 2.5 s.
- **Deferred:** a real database, edit/delete rights for the payer, per-item tax rules (non-taxable items), different tip rates for food vs drinks, fractional shares (2/3 – 1/3), multi-currency, push notifications instead of manual reminders, measuring AI accuracy on a set of real receipts (and comparing OpenAI vs Gemini on it).

To verify on a real phone before submitting: Venmo/Cash App links open the app with the amount pre-filled; voice input works in iOS Safari and Android Chrome.

## Time spent & how AI was used

- Time spent: `<fill in>`
- AI use: `<fill in — which assistant you used and for what; how you checked it (tests, running the sample cases on phone-sized screens with several users, reading every file)>`
