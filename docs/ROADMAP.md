# Roadmap: features to add

[← Back to README](../README.md)

Ordered by how much they improve trust in the numbers, then everyday use, then production readiness.

## P0: correctness and trust

1. **Payer admin link.** A secret edit token in the creator's link that lets the payer fix a misread price or add an item after sharing, remove, rename or merge people, and lock the bill once settled. Right now nothing can be changed after the link is shared, and a typo'd or AI-invented name stays on the bill (and in "everyone") forever.
2. **Uneven and per-unit shares.** "Iced Tea ×2" should split into two units someone can each claim, and a dish should allow 2/3 – 1/3 shares. Today an item is always split evenly among the people who claimed it.
3. **AI accuracy evaluation.** A labeled set of real receipts (blurry, long, handwritten tip, service charge, foreign-language, tax-inclusive) with per-field accuracy for items, subtotal, tax, tip, fees and total. Use it to compare OpenAI and Gemini and to catch regressions when the prompt changes.
4. **CI.** GitHub Actions that builds the Docker image and runs pytest on every PR, plus browser end-to-end tests (Playwright) for claim → pay flows, including the stale-poll race that is currently only checked by hand.

## P1: everyday use

5. **Copy the split to the group chat.** `format_summary()` in `splitter.py` already produces the text, but no endpoint or button exposes it.
6. **Live updates over Server-Sent Events** instead of 2.5 s polling: instant updates and fewer requests.
7. **Payer-confirmed payments.** The payer confirms money arrived, and the app prompts a refund when someone overpaid because their share went down.
8. **Locales.** Decimal commas (`12,50`), the receipt's currency instead of always `$`, and a Chinese UI (voice input already supports Chinese).
9. **Undo** after Apply and after a claim.
10. **More photo types:** HEIC from desktop uploads (`pillow-heif`), several photos for one long receipt, and retake guidance when the photo is cut off.
11. **Highlight uncertain fields.** Ask the model for per-field confidence and highlight low-confidence lines on the review screen.
12. **Demo samples** with a service charge and a suggested-tip table, so reviewers can see those checks without an API key.

## P2: production

13. **A real database** (SQLite, then Postgres), bill expiry, and locking that works with several workers.
14. **Abuse and cost controls:** rate limits and spend caps on `/api/extract` and `/assign-text` (anyone with the site can trigger AI calls on the server's key), plus logs and metrics for AI latency, fallback rate and failure rate.
15. **Tax and tip rules:** tax-exempt or differently taxed items (e.g. alcohol), tax-inclusive (VAT) receipts, and a choice of tipping on pre-tax or pre-discount amounts.
16. **Group trips:** several receipts and several payers, with one net settlement at the end.
