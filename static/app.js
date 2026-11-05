/* SplitMyReceipt — mobile web frontend (no framework, no build step). */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const app = $("#app");
const meKey = (id) => `smr:me:${id}`;

// ------------------------------------------------------------------ utils
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (c) => (c == null ? "—" : (c < 0 ? "-" : "") + "$" + (Math.abs(c) / 100).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ","));
const dollars = (c) => (c / 100).toFixed(2);
function toCents(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).replace(/[$,\s]/g, "");
  if (s === "" || !/^-?\d*\.?\d*$/.test(s) || s === "." || s === "-") return null;
  const [w, f = ""] = s.replace("-", "").split(".");
  const cents = parseInt(w || "0", 10) * 100 + parseInt((f + "00").slice(0, 2), 10) + (f.length > 2 && +f[2] >= 5 ? 1 : 0);
  return s.startsWith("-") ? -cents : cents;
}
const initial = (name) => (Array.from(name.trim())[0] || "?").toUpperCase();
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: fine */ } },
};

async function api(path, { method = "GET", json, form } = {}) {
  const headers = {};
  let body;
  if (json) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  let res;
  try { res = await fetch(path, { method, headers, body }); }
  catch { throw new Error("Can't reach the server. Check your connection and try again."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? "Some of the numbers aren't valid." : "Something went wrong.");
  }
  return data;
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

async function shareOrCopy(text, url) {
  if (navigator.share) {
    try { await navigator.share({ text, url }); return; } catch (e) { if (e.name === "AbortError") return; }
  }
  try { await navigator.clipboard.writeText(url ? `${text}\n${url}` : text); toast("Copied — paste it in your group chat"); }
  catch { prompt("Copy this:", url ? `${text}\n${url}` : text); }
}

// ------------------------------------------------------------------ mode
let config = { ai: false, provider: "Demo", samples: [] };
function aiMode() { return config.ai ? "ai" : "demo"; }
function modeLine() {
  return config.ai
    ? `${config.provider} reads your receipt and understands who had what.`
    : "Demo mode: the AI is mocked for the sample receipts. To read your own photos, the server needs an AI key."
}
let rerender = () => {};

// ================================================================== CREATE
const c = { receipt: null, notes: "", mode: "", issues: [], preview: null, loading: false, error: "",
            tip: 18, customTip: "", payer: store.get("smr:my-name") || "", venmo: store.get("smr:venmo") || "", cashapp: store.get("smr:cashapp") || "" };

function renderStart() {
  app.innerHTML = `
    <h1>Snap the receipt. Everyone taps what they ate.</h1>
    <p class="lede">You get each person's exact share — tax and tip included — and a link they can pay you from. No app or sign-up for anyone.</p>
    <label class="photo-drop" for="photo">
      <span class="cam" aria-hidden="true">📷</span>
      <strong>Take a photo of the receipt</strong>
      <span class="muted small">or choose one from your photos</span>
    </label>
    <input id="photo" type="file" accept="image/*" class="sr-only">
    <p class="muted small" style="margin-top:14px">No receipt handy? Try a sample:</p>
    <div class="samples">
      ${config.samples.map((s, i) => `<button class="chip" data-sample="${esc(s)}">${["Dinner for 3", "Blurry photo", "Not a receipt"][i] || esc(s)}</button>`).join("")}
    </div>
    <div id="start-msg">${c.error ? `<div class="note err">${esc(c.error)}</div>` : ""}</div>
    <p class="muted small" style="margin-top:18px"><span class="mode-tag ${aiMode() === "ai" ? "ai" : ""}">${aiMode() === "ai" ? esc(config.provider) : "Demo mode"}</span> ${esc(modeLine())}</p>`;
  $("#photo").onchange = (e) => e.target.files[0] && readReceipt({ file: e.target.files[0] });
  app.querySelectorAll("[data-sample]").forEach((b) => (b.onclick = () => readReceipt({ sample: b.dataset.sample })));
}

async function readReceipt({ file, sample }) {
  const form = new FormData();
  if (file) form.append("file", file); else form.append("sample", sample);
  c.preview = file ? URL.createObjectURL(file) : `/samples/${encodeURIComponent(sample)}`;
  c.error = "";
  $("#start-msg").innerHTML = `<div class="note info" style="display:flex;gap:10px;align-items:center"><span class="spinner" style="border-color:rgba(29,79,122,.3);border-top-color:#1D4F7A"></span> Reading the receipt…</div>`;
  try {
    const r = await api("/api/extract", { method: "POST", form });
    Object.assign(c, { receipt: r.receipt, notes: r.notes, mode: r.mode, issues: r.issues });
    renderReview();
    window.scrollTo(0, 0);
  } catch (e) {
    c.error = e.message; renderStart();
  }
}

function itemsSum() { return c.receipt.items.reduce((a, i) => a + (i.price_cents || 0), 0); }
function extraTip() {
  if (c.receipt.tip_cents) return 0;
  if (c.tip === "custom") return Math.max(0, toCents(c.customTip) || 0);
  return Math.round(itemsSum() * c.tip / 100);
}

function renderReview() {
  const r = c.receipt;
  if (!r.is_receipt) {
    app.innerHTML = `
      <h1>That doesn't look like a receipt</h1>
      <img class="preview" src="${esc(c.preview)}" alt="Your photo">
      <div class="note err">We couldn't find any items or prices in this photo. Take a photo of the printed receipt, with the item list and total in view.</div>
      ${c.notes ? `<p class="muted small">AI note: ${esc(c.notes)}</p>` : ""}
      <button class="btn wide" id="again">Try another photo</button>`;
    $("#again").onclick = () => { c.receipt = null; renderStart(); };
    return;
  }
  app.innerHTML = `
    <h1>Check what we read</h1>
    <p class="muted">Tap any line to fix it. <span class="mode-tag ${c.mode !== "Demo" ? "ai" : ""}">${c.mode !== "Demo" ? "Read by " + esc(c.mode) : "Demo: AI mocked"}</span></p>
    <details><summary class="link-btn" style="display:inline">Show photo</summary><img class="preview" style="margin-top:8px;max-height:none" src="${esc(c.preview)}" alt="Receipt photo"></details>
    ${c.notes ? `<div class="note info">AI note: ${esc(c.notes)}</div>` : ""}
    <div class="receipt" id="paper">
      <input class="merchant" id="merchant" value="${esc(r.merchant)}" placeholder="Restaurant name" aria-label="Restaurant name"
        style="display:block;width:100%;border:0;font:inherit;text-align:center;font-weight:500;font-size:17px;background:transparent">
      <div class="rule"></div>
      <div id="lines"></div>
      <button class="link-btn" id="add-item" style="font-family:var(--sans);font-size:14px">+ Add a missing item</button>
      <div class="rule"></div>
      <div class="money-row"><span>Subtotal</span><input id="m-sub" inputmode="decimal" aria-label="Subtotal"><i></i></div>
      <div class="money-row"><span>Tax</span><input id="m-tax" inputmode="decimal" aria-label="Tax"><i></i></div>
      <div class="money-row"><span>Tip on receipt</span><input id="m-tip" inputmode="decimal" aria-label="Tip on receipt" placeholder="none"><i></i></div>
      <div class="money-row" style="font-weight:500"><span>Total</span><input id="m-tot" inputmode="decimal" aria-label="Total"><i></i></div>
    </div>
    <div id="issues"></div>
    <div id="tip-block"></div>
    <h2>You paid. Where should friends send money?</h2>
    <label for="payer">Your name</label>
    <input class="field" id="payer" value="${esc(c.payer)}" placeholder="e.g. Amy" maxlength="30" autocomplete="given-name">
    <div class="two">
      <div><label for="venmo">Venmo <span class="hint">optional</span></label>
        <input class="field" id="venmo" value="${esc(c.venmo)}" placeholder="@username" autocapitalize="off"></div>
      <div><label for="cashapp">Cash App <span class="hint">optional</span></label>
        <input class="field" id="cashapp" value="${esc(c.cashapp)}" placeholder="$cashtag" autocapitalize="off"></div>
    </div>
    <p class="muted small" style="margin-top:8px">Payment buttons open Venmo or Cash App with the amount filled in. This app never handles money.</p>
    <div class="bar"><div class="bar-inner">
      <button class="btn quiet" id="back">Back</button>
      <button class="btn" id="create" style="flex:1">Create share link</button>
    </div></div>`;

  const money = { "m-sub": "subtotal_cents", "m-tax": "tax_cents", "m-tip": "tip_cents", "m-tot": "total_cents" };
  for (const [id, field] of Object.entries(money)) {
    const el = $("#" + id);
    el.value = r[field] ? dollars(r[field]) : (field === "tax_cents" ? "0.00" : "");
    el.oninput = () => { const v = toCents(el.value); r[field] = field === "tax_cents" || field === "tip_cents" ? (v || 0) : v; onEdit(); };
    el.onblur = () => { if (r[field] != null && el.value !== "") el.value = dollars(r[field]); };
  }
  $("#merchant").oninput = (e) => (r.merchant = e.target.value);
  $("#add-item").onclick = () => { r.items.push({ name: "", price_cents: 0 }); drawLines(); onEdit(); $("#lines").lastElementChild.querySelector("input").focus(); };
  $("#payer").oninput = (e) => { c.payer = e.target.value; updateCreate(); };
  $("#venmo").oninput = (e) => (c.venmo = e.target.value);
  $("#cashapp").oninput = (e) => (c.cashapp = e.target.value);
  $("#back").onclick = () => { c.receipt = null; renderStart(); };
  $("#create").onclick = createBill;
  drawLines(); drawIssues(); drawTip(); updateCreate();
}

function drawLines() {
  $("#lines").innerHTML = c.receipt.items.map((it, i) => `
    <div class="edit-line" data-i="${i}">
      <input value="${esc(it.name)}" placeholder="Item name" aria-label="Item ${i + 1} name" data-k="name">
      <input class="num" value="${dollars(it.price_cents)}" inputmode="decimal" aria-label="Item ${i + 1} price" data-k="price">
      <button class="del" aria-label="Remove ${esc(it.name || "item")}" data-del="${i}">×</button>
    </div>`).join("");
  $("#lines").querySelectorAll("input").forEach((el) => {
    const i = +el.closest(".edit-line").dataset.i;
    el.oninput = () => {
      if (el.dataset.k === "name") c.receipt.items[i].name = el.value;
      else c.receipt.items[i].price_cents = toCents(el.value) ?? 0;
      onEdit();
    };
    if (el.dataset.k === "price") el.onblur = () => (el.value = dollars(c.receipt.items[i].price_cents));
  });
  $("#lines").querySelectorAll("[data-del]").forEach((b) => (b.onclick = () => { c.receipt.items.splice(+b.dataset.del, 1); drawLines(); onEdit(); }));
}

let validateTimer;
function onEdit() {
  drawTip();
  clearTimeout(validateTimer);
  validateTimer = setTimeout(async () => {
    try { c.issues = (await api("/api/validate", { method: "POST", json: c.receipt })).issues; } catch { /* keep last */ }
    drawIssues(); updateCreate();
  }, 250);
}

function drawIssues() {
  const box = $("#issues");
  if (!box) return;
  if (!c.issues.length) {
    const r = c.receipt;
    box.innerHTML = `<div class="note ok">✓ It all adds up: items ${fmt(itemsSum())} + tax ${fmt(r.tax_cents)}${r.tip_cents ? ` + tip ${fmt(r.tip_cents)}` : ""} = ${fmt(r.total_cents)}</div>`;
  } else {
    box.innerHTML = c.issues.map((i) => `<div class="note ${i.level === "error" ? "err" : "warn"}">${i.level === "error" ? "⛔" : "⚠️"} ${esc(i.message)}</div>`).join("");
  }
}

function drawTip() {
  const box = $("#tip-block");
  if (!box) return;
  if (c.receipt.tip_cents) { box.innerHTML = `<p class="muted small">Tip is already on the receipt (${fmt(c.receipt.tip_cents)}), so we'll use that.</p>`; return; }
  const opts = [0, 15, 18, 20];
  box.innerHTML = `
    <h2>Add a tip?</h2>
    <p class="muted small">No tip on the receipt. It's split in proportion to what each person ordered.</p>
    <div class="tips">
      ${opts.map((p) => `<button class="chip" data-tip="${p}" aria-pressed="${c.tip === p}">${p ? p + "%" : "No tip"}</button>`).join("")}
      <button class="chip" data-tip="custom" aria-pressed="${c.tip === "custom"}">Custom</button>
    </div>
    ${c.tip === "custom" ? `<input class="field" id="custom-tip" inputmode="decimal" placeholder="Tip amount in $" value="${esc(c.customTip)}" style="margin-top:8px">` : ""}
    <p class="small" style="margin-top:8px">Tip: <b>${fmt(extraTip())}</b> · New total: <b>${fmt(itemsSum() + (c.receipt.tax_cents || 0) + extraTip())}</b></p>`;
  box.querySelectorAll("[data-tip]").forEach((b) => (b.onclick = () => { c.tip = b.dataset.tip === "custom" ? "custom" : +b.dataset.tip; drawTip(); }));
  const ct = $("#custom-tip");
  if (ct) ct.oninput = () => { c.customTip = ct.value; const p = box.querySelector("p.small:last-child"); p.innerHTML = `Tip: <b>${fmt(extraTip())}</b> · New total: <b>${fmt(itemsSum() + (c.receipt.tax_cents || 0) + extraTip())}</b>`; };
}

function updateCreate() {
  const btn = $("#create");
  if (!btn) return;
  const blocked = c.issues.some((i) => i.level === "error") || !c.payer.trim() || !c.receipt.items.length;
  btn.disabled = blocked;
  btn.textContent = !c.payer.trim() ? "Enter your name to continue" : "Create share link";
}

async function createBill() {
  const btn = $("#create");
  btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> Creating…`;
  try {
    const { id } = await api("/api/bills", { method: "POST", json: {
      receipt: c.receipt, extra_tip_cents: extraTip(), payer: c.payer.trim(), venmo: c.venmo, cashapp: c.cashapp } });
    store.set(meKey(id), c.payer.trim());
    store.set("smr:my-name", c.payer.trim()); store.set("smr:venmo", c.venmo); store.set("smr:cashapp", c.cashapp);
    history.pushState({}, "", `/b/${id}`);
    route();
  } catch (e) {
    toast(e.message); updateCreate();
  }
}

// ================================================================== BILL
const b = { id: "", bill: null, me: "", lang: store.get("smr:lang") || "en-US", proposal: null, listening: false,
            rec: null, prevClaims: new Set(), paySheet: false, poll: null };

const ALL = "*";
const covers = (who, name) => who.includes(ALL) || who.includes(name);
const whoLabel = (who) => (who.includes(ALL) ? "Everyone" : who.map(esc).join(", "));
const colorOf = (name) => `p${Math.max(0, b.bill.people.indexOf(name)) % 6}`;
const stamp = (name, extra = "") => `<span class="stamp ${colorOf(name)} ${extra}" title="${esc(name)}">${esc(initial(name))}</span>`;

async function openBill(id) {
  b.id = id; b.me = store.get(meKey(id)) || ""; b.proposal = null; b.paySheet = false;
  app.innerHTML = `<p class="muted" style="margin-top:30px">Loading the bill…</p>`;
  try { b.bill = await api(`/api/bills/${id}`); }
  catch (e) { app.innerHTML = `<h1>Bill not found</h1><div class="note err">${esc(e.message)}</div><a class="btn" href="/">Split a new receipt</a>`; return; }
  b.prevClaims = claimSet();
  renderBill();
  if (!b.me || !b.bill.people.includes(b.me)) askWho();
  clearInterval(b.poll);
  b.poll = setInterval(poll, 2500);
}

const expand = (who) => (who.includes(ALL) ? b.bill.people : who);
function claimSet() { return new Set(b.bill.claims.flatMap((who, i) => expand(who).map((n) => `${i}:${n}`))); }

async function poll() {
  if (document.hidden || !b.bill || !location.pathname.startsWith("/b/")) return;
  try {
    const fresh = await api(`/api/bills/${b.id}`);
    if (fresh.version !== b.bill.version) { b.bill = fresh; drawBill(); }
  } catch { /* offline for a moment: try again next tick */ }
}

function renderBill() {
  app.innerHTML = `
    <div id="b-head"></div>
    <section class="voice" id="b-voice"></section>
    <div id="b-receipt"></div>
    <h2>Everyone</h2>
    <ul class="people" id="b-people"></ul>
    <div class="bar" id="b-bar"></div>`;
  drawVoice(); drawBill();
}

function drawBill() {
  const bill = b.bill, s = bill.split;
  const claimable = bill.items.filter((it) => it.price_cents >= 0).length;
  const claimed = bill.claims.filter((w, i) => w.length && bill.items[i].price_cents >= 0).length;
  const now = claimSet();
  $("#b-head").innerHTML = `
    <div class="bill-head">
      <div><h1>${esc(bill.merchant || "Your bill")}</h1><span class="muted">${fmt(s.total_cents)} · paid by ${esc(bill.payer)}</span></div>
      <button class="btn quiet" id="share">Share link</button>
    </div>
    <div class="progress" aria-hidden="true"><i style="width:${claimable ? (claimed / claimable) * 100 : 100}%"></i></div>
    <p class="small muted">${claimed === claimable ? "Every item is claimed." : `${claimed} of ${claimable} items claimed. Tap the dishes you had.`}</p>
    ${b.me ? `<div class="who-bar">${stamp(b.me, "big")}<span class="grow">You're <b>${esc(b.me)}</b></span><button class="link-btn" id="not-me">Not you?</button></div>` : ""}`;
  $("#share").onclick = () => shareOrCopy(`Tap what you had at ${bill.merchant || "dinner"} and see what you owe:`, location.href);
  const nm = $("#not-me"); if (nm) nm.onclick = askWho;

  $("#b-receipt").innerHTML = `
    <div class="receipt">
      <div class="merchant">${esc(bill.merchant || "RECEIPT")}</div>
      <div class="sub">tap to claim · tap again to undo</div>
      <div class="rule"></div>
      ${bill.items.map((it, i) => {
        const raw = bill.claims[i], who = expand(raw), mine = covers(raw, b.me);
        const each = who.length > 1 ? `<span class="each">${fmt(Math.ceil(it.price_cents / who.length))} each</span>` : "";
        return `<button class="claim ${mine ? "mine" : ""}" data-i="${i}" aria-pressed="${mine}">
          <span class="name">${esc(it.name)}</span><span class="price">${fmt(it.price_cents)}</span>
          <span class="stamps">${raw.includes(ALL) ? `<span class="each" style="margin:0 4px 0 0;font-weight:600">Everyone</span>` : ""}${who.length ? who.map((n) => stamp(n, b.prevClaims.has(`${i}:${n}`) ? "" : "new")).join("") + each : `<span class="nobody">${it.price_cents < 0 ? "Shared by the table" : "Unclaimed"}</span>`}</span>
        </button>`;
      }).join("")}
      <div class="rule"></div>
      <div class="line dim"><span class="name">Subtotal</span><span class="price">${fmt(s.subtotal_cents)}</span></div>
      <div class="line dim"><span class="name">Tax</span><span class="price">${fmt(bill.tax_cents)}</span></div>
      <div class="line dim"><span class="name">Tip</span><span class="price">${fmt(bill.tip_cents)}</span></div>
      <div class="line total"><span class="name">Total</span><span class="price">${fmt(s.total_cents)}</span></div>
    </div>`;
  b.prevClaims = now;
  app.querySelectorAll(".claim").forEach((btn) => (btn.onclick = () => toggleClaim(+btn.dataset.i)));

  $("#b-people").innerHTML = s.shares.map((p) => `
    <li><details class="person">
      <summary>${stamp(p.name, "big")}
        <span class="pname">${esc(p.name)}${p.name === b.me ? " (you)" : ""}
          <span class="status ${p.paid ? "paid" : ""}">${p.name === bill.payer ? "Paid the bill" : p.paid ? "✓ Paid " + esc(bill.payer) : p.paid_cents != null ? (p.due_cents > 0 ? `Paid ${fmt(p.paid_cents)}, owes ${fmt(p.due_cents)} more` : `Overpaid — ${esc(bill.payer)} owes ${fmt(-p.due_cents)} back`) : p.items.length ? "Not paid yet" : "Hasn't claimed anything"}</span></span>
        <span class="amt">${fmt(p.total_cents)}</span></summary>
      <div class="detail">
        ${p.items.map((x) => `<div><span>${esc(x.name)}</span><span>${fmt(x.cents)}</span></div>`).join("") || "<div>No items yet</div>"}
        <div><span>Tax share</span><span>${fmt(p.tax_cents)}</span></div>
        <div><span>Tip share</span><span>${fmt(p.tip_cents)}</span></div>
      </div></details></li>`).join("") +
    (s.unassigned.length ? `<li class="note warn">Still unclaimed: ${s.unassigned.map(esc).join(", ")} (${fmt(s.unassigned_cents)} with tax &amp; tip)</li>` : "");
  drawBar();
}

async function toggleClaim(i) {
  if (!b.me) return askWho();
  const who = b.bill.claims[i], on = !covers(who, b.me);
  // optimistic update so the tap feels instant
  if (who.includes(ALL)) b.bill.claims[i] = b.bill.people.filter((p) => p !== b.me);
  else if (on) who.push(b.me); else who.splice(who.indexOf(b.me), 1);
  drawBill();
  try { b.bill = await api(`/api/bills/${b.id}/claim`, { method: "POST", json: { item: i, person: b.me, on } }); drawBill(); }
  catch (e) { toast(e.message); poll(); }
}

function drawBar() {
  const bill = b.bill, s = bill.split, bar = $("#b-bar");
  const me = s.shares.find((p) => p.name === b.me);
  if (!me) { bar.innerHTML = ""; return; }
  if (b.me === bill.payer) {
    const unpaid = s.shares.filter((p) => p.name !== bill.payer && p.due_cents > 0);
    const owed = unpaid.reduce((a, p) => a + p.due_cents, 0);
    bar.innerHTML = `<div class="bar-inner">
      <div class="owe"><span>${s.complete ? (unpaid.length ? `Waiting on ${unpaid.length} ${unpaid.length === 1 ? "person" : "people"}` : "Everyone has paid you") : "Your share so far"}</span>
        <b>${s.complete && unpaid.length ? fmt(owed) + " owed" : fmt(me.total_cents)}</b></div>
      <button class="btn" id="remind">${s.complete && unpaid.length ? "Send reminder" : "Invite friends"}</button></div>`;
    $("#remind").onclick = () => {
      const url = location.href;
      if (s.complete && unpaid.length) {
        const lines = unpaid.map((p) => `${p.name}: ${fmt(p.due_cents)}`).join("\n");
        shareOrCopy(`Hi! Here's what everyone owes me for ${bill.merchant || "dinner"}:\n${lines}\nTap to pay:`, url);
      } else shareOrCopy(`Tap what you had at ${bill.merchant || "dinner"} and see what you owe:`, url);
    };
    return;
  }
  const note = encodeURIComponent(`${bill.merchant || "Dinner"} split`);
  const due = me.due_cents, amt = dollars(due), owesMore = me.paid_cents != null && due > 0;
  bar.innerHTML = `<div class="bar-inner" style="flex-wrap:wrap">
    <div class="owe"><span>${me.paid ? `You paid ${esc(bill.payer)}`
      : me.paid_cents != null && due < 0 ? `Your share went down — ${esc(bill.payer)} owes you back`
      : owesMore ? `Your share changed — you owe ${esc(bill.payer)} more`
      : s.complete ? `You owe ${esc(bill.payer)}` : me.items.length ? "Your share so far" : "Tap what you had"}</span>
      <b>${me.paid ? fmt(me.total_cents) : fmt(Math.abs(due))}</b></div>
    ${me.paid || (me.paid_cents != null && due < 0)
      ? `<button class="btn quiet" id="unpaid">Undo</button>`
      : !s.complete
        ? `<button class="btn" disabled>${s.unassigned.length} item${s.unassigned.length > 1 ? "s" : ""} unclaimed</button>`
        : due > 0
          ? `<button class="btn" id="pay">${b.paySheet ? "Close" : "Pay " + esc(bill.payer)}</button>`
          : ""}
    ${b.paySheet && s.complete && due > 0 ? `<div class="pay-sheet" style="width:100%">
      ${bill.pay.venmo ? `<a class="btn venmo" target="_blank" rel="noopener" href="https://venmo.com/${encodeURIComponent(bill.pay.venmo)}?txn=pay&amount=${amt}&note=${note}">Pay ${fmt(due)} with Venmo</a>` : ""}
      ${bill.pay.cashapp ? `<a class="btn cash" target="_blank" rel="noopener" href="https://cash.app/$${encodeURIComponent(bill.pay.cashapp)}/${amt}">Pay with Cash App</a>` : ""}
      <button class="btn quiet" id="copy-amt">Copy ${fmt(due)} (for Zelle or cash)</button>
      <button class="btn ghost" id="paid">I've paid ${esc(bill.payer)}</button>
    </div>` : ""}</div>`;
  const pay = $("#pay"); if (pay) pay.onclick = () => { b.paySheet = !b.paySheet; drawBar(); };
  const paid = $("#paid"); if (paid) paid.onclick = () => setPaid(true);
  const un = $("#unpaid"); if (un) un.onclick = () => setPaid(false);
  const cp = $("#copy-amt"); if (cp) cp.onclick = async () => { try { await navigator.clipboard.writeText(amt); toast(`Copied ${fmt(due)}`); } catch { toast(amt); } };
}

async function setPaid(paid) {
  try { b.bill = await api(`/api/bills/${b.id}/paid`, { method: "POST", json: { person: b.me, paid } }); b.paySheet = false; drawBill(); if (paid) toast(`Marked as paid — thanks!`); }
  catch (e) { toast(e.message); }
}

function askWho() {
  const people = b.bill.people;
  const wrap = document.createElement("div");
  wrap.className = "sheet-backdrop";
  wrap.innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="who-title">
    <h2 id="who-title">Who are you?</h2>
    <p class="muted small">${esc(b.bill.payer)} paid ${fmt(b.bill.split.total_cents)} at ${esc(b.bill.merchant || "dinner")}. Pick your name or add it — no sign-up.</p>
    <div class="name-grid">${people.map((p) => `<button class="chip" data-name="${esc(p)}">${esc(p)}</button>`).join("")}</div>
    <label for="new-name">${people.length ? "Not listed?" : "Your name"}</label>
    <div style="display:flex;gap:8px"><input class="field" id="new-name" placeholder="Your name" maxlength="30" autocomplete="given-name" value="${esc(people.includes(store.get("smr:my-name")) ? "" : store.get("smr:my-name") || "")}"><button class="btn" id="join">Join</button></div>
  </div>`;
  document.body.appendChild(wrap);
  const choose = async (name) => {
    name = name.trim();
    if (!name) return $("#new-name", wrap).focus();
    try {
      const r = await api(`/api/bills/${b.id}/people`, { method: "POST", json: { name } });
      b.me = r.name; b.bill = r.bill; store.set(meKey(b.id), b.me); store.set("smr:my-name", b.me);
      wrap.remove(); drawBill(); drawVoice();
    } catch (e) { toast(e.message); }
  };
  wrap.querySelectorAll("[data-name]").forEach((x) => (x.onclick = () => choose(x.dataset.name)));
  $("#join", wrap).onclick = () => choose($("#new-name", wrap).value);
  $("#new-name", wrap).onkeydown = (e) => e.key === "Enter" && choose(e.target.value);
}

// ------------------------------------------------------------------ voice
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

function drawVoice() {
  const box = $("#b-voice");
  if (!box) return;
  const prop = b.proposal;
  box.innerHTML = `
    <p><b style="color:#fff">Faster: say who had what.</b> One person can sort out the whole table, e.g. “I had the risotto, Ben got the chicken sandwich, we all shared the fries.”</p>
    <div class="voice-row">
      <button class="mic ${b.listening ? "on" : ""}" id="mic" aria-label="${b.listening ? "Stop listening" : "Start speaking"}" ${SR ? "" : "disabled title='Voice input isn’t supported in this browser — type instead'"}>${b.listening ? "■" : "🎙"}</button>
      <textarea id="say" placeholder="${SR ? "Tap the mic and talk, or type here" : "Type who had what (voice isn't supported in this browser)"}" rows="2" aria-label="Who had what">${esc(b.sayText || "")}</textarea>
    </div>
    <div class="lang">
      <span>${["en-US", "zh-CN"].map((l) => `<button class="chip" data-lang="${l}" aria-pressed="${b.lang === l}">${l === "en-US" ? "English" : "中文"}</button>`).join(" ")}</span>
      <button class="btn" id="match" style="min-height:40px;padding:0 16px">Match items</button>
    </div>
    ${prop ? drawProposal(prop) : ""}`;
  const ta = $("#say");
  ta.oninput = () => (b.sayText = ta.value);
  box.querySelectorAll("[data-lang]").forEach((x) => (x.onclick = () => { b.lang = x.dataset.lang; store.set("smr:lang", b.lang); drawVoice(); }));
  $("#mic").onclick = toggleMic;
  $("#match").onclick = matchText;
  const ap = $("#apply"); if (ap) ap.onclick = applyProposal;
  const cn = $("#cancel-prop"); if (cn) cn.onclick = () => { b.proposal = null; drawVoice(); };
}

function drawProposal(prop) {
  const items = b.bill.items;
  if (!prop.assignments.length) {
    return `<div class="proposal"><div class="note warn" style="margin:0">Couldn't match that to any items on the receipt. Try naming the dishes, like “Ben had the fries”.</div>
      ${prop.unclear.length ? `<p class="small muted" style="margin:8px 0 0">Not understood: ${prop.unclear.map(esc).join(" · ")}</p>` : ""}</div>`;
  }
  return `<div class="proposal">
    <p class="small" style="color:var(--ink-2);margin:0 0 6px">Here's what I understood. Check it, then apply. <span class="mode-tag ${prop.mode !== "Demo" ? "ai" : ""}">${prop.mode !== "Demo" ? esc(prop.mode) : "Demo matcher"}</span></p>
    ${prop.assignments.map((a) => `<div class="pline"><span>${esc(items[a.item].name)}</span><span><b>${whoLabel(a.people)}</b>${b.bill.claims[a.item].length ? ` <span class="small muted">(replaces ${whoLabel(b.bill.claims[a.item])})</span>` : ""}</span></div>`).join("")}
    ${prop.new_people.length ? `<p class="small" style="margin:8px 0 0">New ${prop.new_people.length > 1 ? "people" : "person"} will be added: ${prop.new_people.map(esc).join(", ")}</p>` : ""}
    ${prop.unclear.length ? `<p class="small" style="margin:8px 0 0;color:var(--warn)">Not understood: ${prop.unclear.map(esc).join(" · ")}</p>` : ""}
    <div class="row-end"><button class="btn quiet" id="cancel-prop">Cancel</button><button class="btn" id="apply">Apply ${prop.assignments.length} item${prop.assignments.length > 1 ? "s" : ""}</button></div>
  </div>`;
}

function toggleMic() {
  if (!SR) return;
  if (b.listening && b.rec) { b.rec.stop(); return; }
  const rec = new SR();
  rec.lang = b.lang; rec.interimResults = true; rec.continuous = true;
  const base = b.sayText ? b.sayText.trim() + " " : "";
  rec.onresult = (e) => {
    let text = "";
    for (const r of e.results) text += r[0].transcript;
    b.sayText = base + text; $("#say").value = b.sayText;
  };
  rec.onerror = (e) => toast(e.error === "not-allowed" ? "Allow microphone access to use voice, or type instead." : "Didn't catch that — try again or type it.");
  rec.onend = () => { b.listening = false; b.rec = null; drawVoice(); if (b.sayText && b.sayText.trim()) matchText(); };
  b.rec = rec; b.listening = true; b.proposal = null; drawVoice();
  try { rec.start(); } catch { b.listening = false; drawVoice(); }
}

async function matchText() {
  const text = (b.sayText || "").trim();
  if (!text) { toast("Say or type who had what first."); return; }
  const btn = $("#match"); btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>`;
  try { b.proposal = await api(`/api/bills/${b.id}/assign-text`, { method: "POST", json: { text, speaker: b.me } }); }
  catch (e) { toast(e.message); }
  drawVoice();
}

async function applyProposal() {
  try {
    b.bill = await api(`/api/bills/${b.id}/apply`, { method: "POST", json: { assignments: b.proposal.assignments } });
    const n = b.proposal.assignments.length;
    b.proposal = null; b.sayText = ""; drawVoice(); drawBill(); toast(`Assigned ${n} item${n > 1 ? "s" : ""}`);
  } catch (e) { toast(e.message); }
}

// ================================================================== router
function route() {
  clearInterval(b.poll);
  const m = location.pathname.match(/^\/b\/([A-Za-z0-9_-]+)/);
  if (m) { rerender = () => openBill(m[1]); openBill(m[1]); }
  else { rerender = () => (c.receipt ? renderReview() : renderStart()); c.receipt ? renderReview() : renderStart(); }
}
window.onpopstate = route;

api("/api/config").then((cfg) => (config = cfg)).catch(() => {}).finally(route);
