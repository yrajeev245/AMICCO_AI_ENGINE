/**
 * script.js — Parts Discount Engine
 */

window.data = [];   // raw catalogue — explicit global so catalogue.js can share it

// Persists "added" state across re-renders so buttons stay green
const _addedToCart = new Set();  // "part|||brand"

const getPart  = d => d.Part  || d.part;
const getBrand = d => d.Brand || d.brand;

// ─── FORMAT HELPERS ────────────────────────────────────────────────────────
const fmt  = n => Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const fmtD = n => Number(n).toFixed(1);
const getSellingPrice = d => Number(d.SellingPrice || d.selling_price || d.sellingPrice || 0);

/**
 * Returns true if a catalogue row is in-stock.
 * Blank / missing stock = in-stock (show it).
 * Only hides rows where stock is explicitly a number ≤ 0.
 */
function stockOk(d) {
  const raw = d.Stock !== undefined ? d.Stock : (d.stock !== undefined ? d.stock : '');
  const s = String(raw).trim();
  if (!s || s === 'null' || s === 'undefined') return true;
  const n = parseFloat(s);
  return isNaN(n) || n > 0;
}

// ─── 1. DATA LOADING ───────────────────────────────────────────────────────
async function loadData() {
  try {
    const res = await fetch("/api/data");
    if (!res.ok) throw new Error(`Server ${res.status}`);
    data = await res.json();
    if (!data.length) throw new Error("No parts in sheet");
  } catch(e) {
    showError("Failed to load parts: " + e.message);
  }
}

// Only auto-init cart builder on index page; catalogue.js handles its own init
if (document.getElementById("cart")) {
  loadData().then(() => {
    // If catalogue prefill data exists, skip the blank row — prefill will handle it
    let hasPrefill = false;
    try {
      const stored = JSON.parse(sessionStorage.getItem("pde_catalogue_cart") || "null");
      hasPrefill = stored && Object.keys(stored).length > 0;
    } catch {}
    if (!hasPrefill) addItem();
  });
}

// ─── CATALOGUE LOOKUP ──────────────────────────────────────────────────────
function getMaxDiscount(part, brand) {
  const row = data.find(d => getPart(d) === part && getBrand(d) === brand);
  if (!row) return null;
  const minDisc   = Number(row.MinDiscount                || row.min_discount    || 0);
  const bonusQty  = Number(row.BonusDiscount_QtyThreshold || row.bonus_disc_qty  || 0);
  const bonusCart = Number(row.BonusDiscount_MinCartValue || row.bonus_disc_cart || 0);
  const total     = minDisc + bonusQty + bonusCart;
  return total > 0 ? { minDisc, bonusQty, bonusCart, total } : null;
}

// ─── 2. CART BUILDER ───────────────────────────────────────────────────────
function addItem(prefillPart=null, prefillBrand=null) {
  if (!data.length) { showError("Parts data not loaded yet."); return null; }

  const wrapper = document.createElement("div");
  wrapper.className = "row-wrap";

  const div = document.createElement("div");
  div.className = "row";
  div.innerHTML = `
    <select class="part"></select>
    <select class="brand"></select>
    <input type="number" class="qty" value="1" min="1" oninput="warnCartQty(this)"/>
    <button class="remove-btn" onclick="removeCartRow(this)" title="Remove">✕</button>
  `;

  const warn = document.createElement("div");
  warn.className = "cart-qty-warn";
  warn.style.display = "none";

  wrapper.appendChild(div);
  wrapper.appendChild(warn);

  const cart = document.getElementById("cart");
  cart.insertBefore(wrapper, cart.firstChild);
  populateParts(div, prefillPart, prefillBrand);
  return div;
}

function populateParts(row, prefillPart=null, prefillBrand=null) {
  const partSel = row.querySelector(".part");
  const parts   = [...new Set(
    data.filter(d => stockOk(d)).map(d => getPart(d)).filter(Boolean)
  )].sort();

  partSel.innerHTML = "";
  parts.forEach(p => {
    const o = document.createElement("option");
    o.value = p; o.textContent = p;
    partSel.appendChild(o);
  });

  if (prefillPart && parts.includes(prefillPart)) {
    partSel.value = prefillPart;
  }

  partSel.addEventListener("change", () => {
    updateBrands(row, null);
    clearCartRowWarn(row);
  });
  updateBrands(row, prefillBrand);
}

function updateBrands(row, prefillBrand=null) {
  const part     = row.querySelector(".part").value;
  const brandSel = row.querySelector(".brand");
  brandSel.innerHTML = "";

  data.filter(d => getPart(d) === part && stockOk(d)).forEach(b => {
    const o  = document.createElement("option");
    const sp = getSellingPrice(b);
    o.value       = getBrand(b);
    o.textContent = sp ? `${getBrand(b)} - ₹${fmt(sp)}` : getBrand(b);
    brandSel.appendChild(o);
  });

  if (prefillBrand) {
    const found = Array.from(brandSel.options).find(o => o.value === prefillBrand);
    if (found) brandSel.value = prefillBrand;
    // else: first option is auto-selected, which is fine
  }
}

function getCart() {
  const raw = Array.from(document.querySelectorAll("#cart .row")).map(row => ({
    part:  row.querySelector(".part").value,
    brand: row.querySelector(".brand").value,
    qty:   parseInt(row.querySelector(".qty").value) || 1,
  })).filter(item => item.part && item.brand);

  // Merge duplicate part+brand entries by summing qty
  const merged = {};
  raw.forEach(item => {
    const key = `${item.part}|||${item.brand}`;
    if (merged[key]) merged[key].qty += item.qty;
    else             merged[key] = { ...item };
  });
  return Object.values(merged);
}

// ─── 3. CALCULATE ──────────────────────────────────────────────────────────
async function calculateCart() {
  const cart = getCart();
  if (!cart.length) { showError("Add at least one part."); return; }

  const target = parseFloat(document.getElementById("target-discount").value) || null;
  const btn    = document.querySelector(".btn-primary");
  btn.disabled = true;
  btn.textContent = "⏳ Calculating...";
  clearError();

  try {
    const res = await fetch("/api/deal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cart, target_discount: target }),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new Error(e.error || `Server ${res.status}`);
    }
    renderResult(await res.json(), target);
  } catch(e) {
    showError("Error: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Get Best Deal";
  }
}

// ─── 4. RENDER ─────────────────────────────────────────────────────────────
function renderResult(api, target) {
  renderSummary(api.result);
  renderLineItems(api.result);
  renderSuggestions(api.suggestions, api.result);
  renderTargetAdvice(api.target_advice, target);
  renderRecommendations(api.recommendations);
  document.getElementById("details-section").style.display = "block";
  document.getElementById("empty-state").style.display     = "none";
}

// 4a. Summary
function renderSummary(r) {
  document.getElementById("summary-cards").innerHTML = `
    <div class="stat-card">
      <div class="stat-label">Total Cart Value</div>
      <div class="stat-value">₹${fmt(r.total_sp)}</div>
      <div class="stat-sub">at full price</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Discount Given</div>
      <div class="stat-value amber">${fmtD(r.eff_discount)}%</div>
      <div class="stat-sub">overall on cart</div>
    </div>
    <div class="stat-card highlight-green">
      <div class="stat-label">Value After Discount</div>
      <div class="stat-value green">₹${fmt(r.revenue)}</div>
      <div class="stat-sub">garage pays this</div>
    </div>
  `;
}

// 4b. Line items
function renderLineItems(r) {
  const itemsHtml = r.items.map(i => `
    <div class="item-card">
      <div class="item-top">
        <div>
          <span class="item-name">${i.part}</span>
          <span class="brand-tag">${i.brand}</span>
        </div>
        <div class="item-total">₹${fmt(i.total)}</div>
      </div>
      <div class="item-meta">
        <span class="meta-pill">Qty: ${i.qty}</span>
        <span class="meta-pill">Unit Price: ₹${fmt(i.selling_price)}</span>
        <span class="meta-pill discount">Discount: ${i.discount}%</span>
        <span class="meta-pill final">Final: ₹${i.final_price}</span>
        ${i.cart_bonus_hit && Number(i.bonus_disc_cart) > 0
          ? `<span class="meta-pill cart-bonus">Cart Bonus: +${fmtD(i.bonus_disc_cart)}%</span>`
          : ""}
      </div>
    </div>
  `).join("");

  const errHtml = (r.errors || []).map(e => `<div class="error-card">⚠️ ${e}</div>`).join("");
  document.getElementById("details").innerHTML = itemsHtml + errHtml;
}

// 4c. Smart Suggestions
// Cart-type suggestions from the server are suppressed entirely —
// the dedicated "🔓 All Cart-Bonus Eligible Parts" section handles that.
// We only show brand-switch suggestions here.
function renderSuggestions(suggs, result) {
  const el = document.getElementById("suggestions");

  // Brand-switch suggestions only
  const brandSuggs = (suggs || []).filter(s => s.type === "brand");
  const suggsHtml  = brandSuggs.length
    ? brandSuggs.map(renderSuggestionCard).join("")
    : `<p class="muted-note">No brand-switch optimisations found.</p>`;

  // Cart-bonus eligible parts — always show all from catalogue
  const bonusParts    = getBonusCatalogueParts();
  const cartTotal     = result ? result.total_sp : 0;
  const bonusSection  = bonusParts.length ? renderBonusCatalogueSection(bonusParts, cartTotal) : "";

  el.innerHTML = suggsHtml + bonusSection;
  reapplyAddedState(el);
}

// Re-apply "✓ Added" style after re-render
function reapplyAddedState(container) {
  syncAddedStateFromCart();

  container.querySelectorAll(".btn-add-reco").forEach(btn => {
    // Try data-* attributes first (new style), fall back to parsing onclick
    let part  = btn.dataset.part;
    let brand = btn.dataset.brand;
    if (!part || !brand) {
      const row = btn.closest(".rec-variant-row");
      part = row?.dataset.part;
      brand = row?.querySelector(".rec-brand-select")?.value;
    }
    if (!part || !brand) {
      const oc    = btn.getAttribute("onclick") || "";
      const match = oc.match(/addToCartFrom\w+\('([^']+)','([^']+)'/);
      if (match) { part = match[1]; brand = match[2]; }
    }
    if (part && brand && _addedToCart.has(`${part}|||${brand}`)) {
      markBtnAdded(btn);
    }
  });
}

function syncAddedStateFromCart() {
  _addedToCart.clear();
  document.querySelectorAll("#cart .row").forEach(row => {
    const part = row.querySelector(".part")?.value;
    const brand = row.querySelector(".brand")?.value;
    if (part && brand) _addedToCart.add(`${part}|||${brand}`);
  });
}

function refreshAddedButtons() {
  document.querySelectorAll(".btn-add-reco").forEach(btn => {
    btn.textContent = "+ Add";
    btn.disabled = false;
    btn.style.background = "";
    btn.style.color = "";
    btn.style.borderColor = "";
  });
  reapplyAddedState(document);
}

function removeCartRow(btn) {
  const row = btn.closest(".row");
  const wrap = row?.closest(".row-wrap") || row;
  wrap?.remove();
  syncAddedStateFromCart();
  refreshAddedButtons();
}

// All catalogue parts with cart-value bonus, sorted best-bonus first
function getBonusCatalogueParts() {
  return data.filter(d => {
    const bonus = Number(d.BonusDiscount_MinCartValue || d.bonus_disc_cart || 0);
    return bonus > 0 && stockOk(d);
  }).sort((a, b) => {
    const bA = Number(a.BonusDiscount_MinCartValue || a.bonus_disc_cart || 0);
    const bB = Number(b.BonusDiscount_MinCartValue || b.bonus_disc_cart || 0);
    if (bB !== bA) return bB - bA;
    return getSellingPrice(a) - getSellingPrice(b);
  });
}

function renderBonusCatalogueSection(parts, cartTotal) {
  const rows = parts.map(d => {
    const part   = getPart(d);
    const brand  = getBrand(d);
    const sp     = getSellingPrice(d);
    const bonus  = Number(d.BonusDiscount_MinCartValue || d.bonus_disc_cart || 0);
    const thresh = Number(d.MinCartValue               || d.min_cart_value  || 0);
    const maxDisc = getMaxDiscount(part, brand);

    // Show how much more to spend to unlock this bonus
    const shortfall = thresh > 0 ? Math.max(0, thresh - cartTotal) : 0;
    const hintText  = shortfall > 0
      ? `🔓 Add ₹${fmt(shortfall)} more to cart → unlock <strong>+${fmtD(bonus)}%</strong> extra`
      : thresh > 0
        ? `✅ Cart threshold met → <strong>+${fmtD(bonus)}%</strong> bonus active`
        : `🔓 Spend ₹${fmt(thresh)}+ → unlock <strong>+${fmtD(bonus)}%</strong> extra`;

    const maxBadge = maxDisc
      ? `<span class="max-disc-badge" title="Base ${maxDisc.minDisc}% + Qty ${maxDisc.bonusQty}% + Cart ${maxDisc.bonusCart}%">Max ${fmtD(maxDisc.total)}% off</span>`
      : "";

    return `
      <div class="rec-variant-row sugg-action-row" style="margin-bottom:5px">
        <div style="min-width:0;flex:1 1 auto;">
          <div class="rec-variant-label-row">
            <span class="rec-variant-label">${part} (${brand}) — ₹${fmt(sp)}</span>
            ${maxBadge}
          </div>
          <span class="cart-bonus-hint">${hintText}</span>
        </div>
        <div class="rec-add-control">
          <input type="number" class="add-qty" value="1" min="1" title="Qty"/>
          <button class="btn-add-reco"
            data-part="${escAttr(part)}" data-brand="${escAttr(brand)}"
            onclick="addToCartFromSuggestion(this.dataset.part,this.dataset.brand,this.parentElement.querySelector('.add-qty').value,this)">
            + Add
          </button>
        </div>
      </div>`;
  }).join("");

  return `
    <div style="margin-top:10px">
      <div class="section-label" style="padding-top:10px">🔓 All Cart-Bonus Eligible Parts</div>
      <div style="padding:0 11px 8px">
        <div class="suggestion-card type-cart" style="margin-bottom:8px;font-size:0.79rem">
          Add any of these parts to cart, then spend enough to hit the threshold and unlock extra discount.
        </div>
        <div style="display:flex;flex-direction:column;gap:5px">${rows}</div>
      </div>
    </div>`;
}

// Brand-switch suggestion card
function renderSuggestionCard(s) {
  if (s.type !== "brand") return "";

  // Use structured fields sent directly from the server.
  // Fall back to parsing the HTML message only if the fields are absent
  // (for backwards compatibility with older server responses).
  let part = s.part  || "";
  let from = s.from_brand || "";
  let to   = s.to_brand   || "";

  if (!part || !from || !to) {
    // Legacy fallback: parse bold spans from message HTML
    const tmp = document.createElement("div");
    tmp.innerHTML = s.message;
    const boldTexts = Array.from(tmp.querySelectorAll(".sugg-bold, b, strong"))
                          .map(el => el.textContent.trim());
    part = boldTexts[0] || "";
    from = boldTexts[1] || "";
    to   = boldTexts[2] || "";
  }

  const switchBtn = (part && from && to)
    ? `<button class="btn-switch-brand"
         data-part="${escAttr(part)}"
         data-from="${escAttr(from)}"
         data-to="${escAttr(to)}"
         onclick="switchBrandInCart(this.dataset.part, this.dataset.from, this.dataset.to, this)">
         ⇄ Switch to ${to}
       </button>`
    : "";

  return `
    <div class="suggestion-card type-brand">
      <span class="sugg-icon">${s.icon}</span>${s.message}
      ${switchBtn ? `<div style="margin-top:8px">${switchBtn}</div>` : ""}
    </div>`;
}

// Standard action row (target advice)
function renderActionRow(a) {
  const unit = Number(a.selling_price || a.add_value || 0);
  return `
    <div class="rec-variant-row sugg-action-row">
      <div style="min-width:0;flex:1 1 auto;">
        <span class="rec-variant-label">${a.part}${a.brand ? ` (${a.brand})` : ""} — ₹${fmt(unit)}</span>
      </div>
      <div class="rec-add-control">
        <input type="number" class="add-qty" value="1" min="1" title="Qty"/>
        <button class="btn-add-reco"
          data-part="${escAttr(a.part)}" data-brand="${escAttr(a.brand || '')}"
          onclick="addToCartFromSuggestion(this.dataset.part, this.dataset.brand, this.parentElement.querySelector('.add-qty').value, this)">
          + Add
        </button>
      </div>
    </div>`;
}

// 4d. Target advice
function renderTargetCard(s) {
  if (s.type === "brand") return renderSuggestionCard(s);

  const actions = (s.actions || []).map(renderActionRow).join("");
  return `
    <div class="suggestion-card type-${s.type}">
      <span class="sugg-icon">${s.icon}</span>${s.message}
      ${actions ? `<div class="suggestion-actions">${actions}</div>` : ""}
    </div>`;
}

function renderTargetAdvice(advice, target) {
  const sec = document.getElementById("target-advice-section");
  if (target && advice && advice.length) {
    sec.style.display = "block";
    document.getElementById("target-advice").innerHTML = advice.map(renderTargetCard).join("");
    reapplyAddedState(document.getElementById("target-advice"));
  } else if (target) {
    sec.style.display = "block";
    document.getElementById("target-advice").innerHTML =
      `<div class="suggestion-card type-qty">✅ Cart already meets your ${target}% target.</div>`;
  } else {
    sec.style.display = "none";
  }
}

// 4e. Bought-together recommendations
function renderRecommendations(recos) {
  const sec = document.getElementById("recommendations-section");
  if (!recos || !recos.length) {
    sec.style.display = "block";
    document.getElementById("recommendations").innerHTML =
      `<p class="muted-note">No frequent bought-together parts found for this cart.</p>`;
    return;
  }

  sec.style.display = "block";
  document.getElementById("recommendations").innerHTML = recos.map(rec => {
    const scoreBadges = rec.fallback
      ? `<span class="rec-score count" title="Popular in recent orders">${rec.count} recent orders</span>
         <span class="rec-score lift" title="Fallback recommendation">Popular add-on</span>`
      : `<span class="rec-score jaccard" title="Jaccard similarity">J: ${rec.jaccard.toFixed(2)}</span>
         <span class="rec-score lift"    title="Lift score">L: ${rec.lift.toFixed(1)}x</span>
         <span class="rec-score count"   title="Times bought together">${rec.count} orders</span>`;

    const groupedProducts = new Map();
    (rec.products || []).forEach(p => {
      const part  = p.part  || p.Part;
      const brand = p.brand || p.Brand;
      const sp    = p.selling_price || p.SellingPrice || "?";
      if (!groupedProducts.has(part)) groupedProducts.set(part, []);
      groupedProducts.get(part).push({ part, brand, sp });
    });

    const chips = Array.from(groupedProducts.entries()).map(([part, variants]) => {
      variants.sort((a, b) => Number(a.sp || 0) - Number(b.sp || 0));
      const options = variants.map(v =>
        `<option value="${escAttr(v.brand)}">${v.brand} — ₹${fmt(v.sp)}</option>`
      ).join("");
      return `
        <div class="rec-variant-row" data-part="${escAttr(part)}">
          <span class="rec-variant-label">${part}</span>
          <div class="rec-inline-controls">
            <select class="rec-brand-select" title="Brand and price" onchange="refreshAddedButtons()">${options}</select>
            <input type="number" class="add-qty" value="1" min="1" title="Qty"/>
            <button class="btn-add-reco" onclick="addGroupedRecoToCart(this)">+ Add</button>
          </div>
        </div>`;
    }).join("");

    return `
      <div class="rec-card">
        <div class="rec-top">
          <span class="rec-name">${rec.proxy}</span>
          <div class="rec-scores">
            ${scoreBadges}
          </div>
        </div>
        <div class="rec-variants">${chips}</div>
      </div>`;
  }).join("");

  reapplyAddedState(document.getElementById("recommendations-section"));
}

function addGroupedRecoToCart(btn) {
  const row = btn.closest(".rec-variant-row");
  if (!row) return;
  const part  = row.dataset.part;
  const brand = row.querySelector(".rec-brand-select")?.value;
  const qty   = row.querySelector(".add-qty")?.value || 1;
  addToCartFromReco(part, brand, qty, btn);
}

// ─── 5. SWITCH BRAND ───────────────────────────────────────────────────────
/**
 * Finds the cart row where part matches AND brand matches fromBrand,
 * then sets its brand dropdown to toBrand.
 * Uses data-* attributes so special characters in brand names never break anything.
 */
function switchBrandInCart(part, fromBrand, toBrand, btn) {
  const rows = Array.from(document.querySelectorAll("#cart .row"));
  let switched = false;
  const partRows = rows.filter(row => row.querySelector(".part").value === part);

  for (const row of partRows) {
    const partSel  = row.querySelector(".part");
    const brandSel = row.querySelector(".brand");
    if (partSel.value !== part) continue;
    if (brandSel.value !== fromBrand && partRows.length !== 1) continue;

    // Repopulate the brand dropdown (ensures toBrand is present),
    // then set the value. updateBrands handles the prefillBrand param.
    updateBrands(row, toBrand);
    row.querySelector(".brand").value = toBrand;
    flashRow(row);
    switched = true;
    break;
  }

  if (!switched) {
    // fromBrand row not found — remove any row for this part with fromBrand or blank brand
    rows.forEach(row => {
      const pv = row.querySelector(".part").value;
      const bv = row.querySelector(".brand").value;
      if (pv === part && (bv === fromBrand || bv === "")) row.remove();
    });
    const newRow = addItem(part, toBrand);
    if (newRow) flashRow(newRow);
  }

  if (btn) {
    btn.textContent      = "✓ Switched";
    btn.disabled         = true;
    btn.style.background = "var(--green)";
    btn.style.color      = "#fff";
    btn.style.borderColor= "var(--green)";
  }

  calculateCart();
}

function flashRow(row) {
  row.style.transition = "background .4s";
  row.style.background = "var(--green-bg)";
  setTimeout(() => { row.style.background = ""; }, 900);
}

// ─── 6. ADD FROM RECO / SUGGESTION ────────────────────────────────────────
function addOrIncrementCart(part, brand, addQty, btn) {
  if (!part || !brand) return;
  const qty = Math.max(1, parseInt(addQty, 10) || 1);

  // Persist so re-renders keep the "✓ Added" state
  _addedToCart.add(`${part}|||${brand}`);

  // If already in cart — increment qty
  const rows = Array.from(document.querySelectorAll("#cart .row"));
  for (const row of rows) {
    if (row.querySelector(".part").value  === part &&
        row.querySelector(".brand").value === brand) {
      const qi = row.querySelector(".qty");
      qi.value = (parseInt(qi.value) || 0) + qty;
      flashRow(row);
      document.getElementById("cart").scrollIntoView({ behavior: "smooth", block: "nearest" });
      markBtnAdded(btn);
      calculateCart();
      return;
    }
  }

  // Not in cart — add new row
  const row = addItem(part, brand);
  if (row) row.querySelector(".qty").value = qty;
  document.getElementById("cart").scrollIntoView({ behavior: "smooth", block: "nearest" });
  markBtnAdded(btn);
  calculateCart();
}

function markBtnAdded(btn) {
  if (!btn) return;
  btn.textContent      = "✓ Added";
  btn.disabled         = true;
  btn.style.background = "var(--green)";
  btn.style.color      = "#fff";
  btn.style.borderColor= "var(--green)";
}

function addToCartFromReco(part, brand, qty=1, btn=null) {
  addOrIncrementCart(part, brand, qty, btn);
}

function addToCartFromSuggestion(part, brand, qty=1, btn=null) {
  addOrIncrementCart(part, brand, qty, btn);
}

// ─── 7. UTILS ──────────────────────────────────────────────────────────────
function clearCartRowWarn(row) {
  const qtyInput = row?.querySelector(".qty");
  if (qtyInput) { qtyInput.style.borderColor = ""; qtyInput.style.boxShadow = ""; }
  const warn = row?.closest(".row-wrap")?.querySelector(".cart-qty-warn");
  if (warn) warn.style.display = "none";
}

function warnCartQty(input) {
  const row   = input.closest(".row");
  if (!row) return;
  const part  = row.querySelector(".part")?.value;
  const brand = row.querySelector(".brand")?.value;
  if (!part || !brand) return;
  const d = data.find(d => getPart(d) === part && getBrand(d) === brand);
  const warn = row.closest(".row-wrap")?.querySelector(".cart-qty-warn");
  if (!d) return;
  const raw = d.Stock !== undefined ? d.Stock : (d.stock !== undefined ? d.stock : "");
  const stockN = parseFloat(String(raw).trim());
  if (isNaN(stockN) || stockN <= 0) return;
  const qty = parseInt(input.value, 10) || 0;
  if (qty > stockN) {
    input.style.borderColor = "var(--accent)";
    input.style.boxShadow   = "0 0 0 3px rgba(200,75,47,.15)";
    if (warn) { warn.textContent = `⚠️ Only ${Math.round(stockN)} in stock`; warn.style.display = "block"; }
  } else {
    input.style.borderColor = "";
    input.style.boxShadow   = "";
    if (warn) warn.style.display = "none";
  }
}

// Use data-* attributes for all onclick buttons — never inline escaping
function escQ(s)    { return (s || "").replace(/'/g, "\\'"); }
function escAttr(s) { return (s || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }

function showError(msg) {
  const el = document.getElementById("error-banner");
  el.textContent = "⚠️ " + msg;
  el.style.display = "block";
}
function clearError() {
  document.getElementById("error-banner").style.display = "none";
}