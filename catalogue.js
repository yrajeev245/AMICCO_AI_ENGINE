/**
 * catalogue.js — Parts Catalogue Page
 * Depends on script.js being loaded first (for `data`, `loadData`,
 * `getSellingPrice`, `getPart`, `getBrand`, `getMaxDiscount`,
 * `stockOk`, `fmt`, `fmtD`, `_addedToCart`, `escAttr`).
 */

// ─── CATALOGUE STATE ────────────────────────────────────────────────────────
let _catSort      = { col: "Part", dir: "asc" };
let _filteredRows = [];
let _proxyMap     = {};   // { partName: proxyName } from Sheet3

const CART_KEY = "pde_catalogue_cart";

function loadCartFromSession() {
  try { return JSON.parse(sessionStorage.getItem(CART_KEY) || "{}"); } catch { return {}; }
}

/**
 * Set the absolute qty for a part+brand in sessionStorage.
 * qty=0 removes the entry.
 */
function setItemInSession(part, brand, qty) {
  const cart = loadCartFromSession();
  const key  = `${part}|||${brand}`;
  if (qty <= 0) {
    delete cart[key];
  } else {
    cart[key] = qty;
  }
  sessionStorage.setItem(CART_KEY, JSON.stringify(cart));
  updateCartUI();
}

function getSessionQty(part, brand) {
  const cart = loadCartFromSession();
  return cart[`${part}|||${brand}`] || 0;
}

function getSessionCartCount() {
  return Object.values(loadCartFromSession()).reduce((s, v) => s + v, 0);
}

function updateCartUI() {
  const n     = getSessionCartCount();
  const badge = document.getElementById("cart-count");
  if (badge) badge.textContent = n;

  const strip = document.getElementById("cart-strip");
  const label = document.getElementById("cart-strip-label");
  if (strip && label) {
    const parts = Object.keys(loadCartFromSession()).length;
    label.textContent = `${parts} part${parts !== 1 ? "s" : ""} (${n} units) added to cart`;
    strip.style.display = n > 0 ? "flex" : "none";
  }
}

function goToCart() {
  window.location.href = "/";
}

// ─── INIT ───────────────────────────────────────────────────────────────────
(function initCatalogue() {
  const showErr = () => {
    document.getElementById("cat-loading").innerHTML =
      '<p style="color:var(--accent)">⚠️ Failed to load parts data. Check your server.</p>';
  };
  Promise.all([
    loadData(),
    fetch("/api/proxy_map").then(r => r.json()).catch(() => ({}))
  ]).then(([_, proxyData]) => {
    _proxyMap = proxyData || {};
    if (window.data && window.data.length) {
      buildCatalogue();
    } else {
      showErr();
    }
  }).catch(showErr);
})();

function buildCatalogue() {
  document.getElementById("cat-loading").style.display = "none";
  document.getElementById("cat-grid-view").style.display = "grid";
  populateFilterDropdowns();
  filterCatalogue();
  updateCartUI();
}

// ─── FILTER DROPDOWNS ───────────────────────────────────────────────────────
function populateFilterDropdowns() {
  const proxySel = document.getElementById("filter-proxy");
  const brandSel = document.getElementById("filter-brand");

  const proxies = [...new Set(Object.values(_proxyMap))].filter(Boolean).sort();
  proxies.forEach(px => {
    const o = document.createElement("option"); o.value = px; o.textContent = px;
    proxySel.appendChild(o);
  });

  // Initial brand population (all brands)
  rebuildBrandDropdown("");
}

function rebuildBrandDropdown(proxyFilter) {
  const brandSel = document.getElementById("filter-brand");
  const currentBrand = brandSel.value;
  brandSel.innerHTML = '<option value="">All Brands</option>';

  const relevantData = proxyFilter
    ? data.filter(d => (_proxyMap[getPart(d)] || "") === proxyFilter)
    : data;

  const brands = [...new Set(relevantData.map(d => getBrand(d)).filter(Boolean))].sort();
  brands.forEach(b => {
    const o = document.createElement("option"); o.value = b; o.textContent = b;
    brandSel.appendChild(o);
  });

  // Keep selected brand if still valid, else reset
  if (brands.includes(currentBrand)) brandSel.value = currentBrand;
}

// ─── FILTER + SORT ──────────────────────────────────────────────────────────
function filterCatalogue(changedField) {
  const proxyFilt = document.getElementById("filter-proxy").value;
  const brandFilt = document.getElementById("filter-brand").value;
  const q         = (document.getElementById("cat-search").value || "").toLowerCase().trim();

  // Rebuild brand options whenever proxy changes
  if (changedField === "proxy") rebuildBrandDropdown(proxyFilt);

  const activeBrand = document.getElementById("filter-brand").value;

  _filteredRows = data.filter(d => {
    const part  = getPart(d)  || "";
    const brand = getBrand(d) || "";
    const proxy = _proxyMap[part] || "";
    if (proxyFilt && proxy !== proxyFilt) return false;
    if (activeBrand && brand !== activeBrand) return false;
    if (q && !part.toLowerCase().includes(q) && !brand.toLowerCase().includes(q) && !proxy.toLowerCase().includes(q)) return false;
    return true;
  });

  sortRows();
  renderGrid();

  const label = document.getElementById("cat-count-label");
  if (label) label.textContent = `${_filteredRows.length} of ${data.length} parts`;
}

function clearFilters() {
  document.getElementById("cat-search").value  = "";
  document.getElementById("filter-proxy").value = "";
  document.getElementById("filter-brand").value = "";
  filterCatalogue();
}

function sortRows() {
  const { col, dir } = _catSort;
  const sign = dir === "asc" ? 1 : -1;
  _filteredRows.sort((a, b) => {
    let av = (a[col] || a[col.toLowerCase()] || "").toString().toLowerCase();
    let bv = (b[col] || b[col.toLowerCase()] || "").toString().toLowerCase();
    if (av < bv) return -sign;
    if (av > bv) return  sign;
    return 0;
  });
}

// ─── STOCK HELPER ───────────────────────────────────────────────────────────
function stockLabel(d) {
  const raw = d.Stock !== undefined ? d.Stock : (d.stock !== undefined ? d.stock : "");
  const s   = String(raw).trim();
  if (!s || s === "null" || s === "undefined") return { ok: true, label: "In Stock", count: null };
  const n = parseFloat(s);
  if (isNaN(n)) return { ok: true, label: "In Stock", count: null };
  return n > 0
    ? { ok: true,  label: `In Stock`, count: n }
    : { ok: false, label: "Out of Stock", count: 0 };
}

// Compute a fake "MRP" for strikethrough display: SP / (1 - minDisc/100)
function computeMRP(sp, minD) {
  if (!minD || minD <= 0) return null;
  return Math.round(sp / (1 - minD / 100));
}

// ─── RENDER GRID ────────────────────────────────────────────────────────────
function renderGrid() {
  const grid = document.getElementById("cat-grid-view");
  // Always read fresh cart from session so grid reflects real persisted state
  const cart = loadCartFromSession();

  if (!_filteredRows.length) {
    grid.innerHTML = `<div class="cat-empty">
      <div class="cat-empty-icon">🔍</div><p>No parts match your filters.</p>
    </div>`;
    return;
  }

  grid.innerHTML = _filteredRows.map(d => {
    const part    = getPart(d);
    const brand   = getBrand(d);
    const sp      = getSellingPrice(d);
    const minD    = Number(d.MinDiscount || d.min_discount || 0);
    const stock   = stockLabel(d);
    const proxy   = _proxyMap[part] || null;
    const mrp     = computeMRP(sp, minD);
    const key     = `${part}|||${brand}`;
    const cartQty = cart[key] || 0;
    const added   = cartQty > 0;

    const discLine = minD > 0
      ? `<span class="cc-discount">${fmtD(minD)}% off</span>`
      : "";

    const mrpLine = mrp
      ? `<span class="cc-mrp">₹${fmt(mrp)}</span>`
      : "";

    const stockDot = stock.ok
      ? `<span class="cc-stock-dot ok"></span><span class="cc-stock-label">${stock.count ? `${Math.round(stock.count)} in stock` : "In Stock"}</span>`
      : `<span class="cc-stock-dot out"></span><span class="cc-stock-label out">Out of Stock</span>`;

    const proxyTag = proxy
      ? `<span class="cc-proxy-tag">${proxy}</span>`
      : "";

    const stockCount = stock.count !== null ? stock.count : null;
    const escKey     = escAttr(key);
    const cssKey     = CSS.escape(key);
    const maxAttr    = stockCount !== null ? `data-max="${stockCount}"` : "";

    // ── PRICE ROW: always show qty input (only visible when NOT added) ──
    const priceRow = `
      <div class="cc-price-row">
        <span class="cc-price">₹${fmt(sp)}</span>
        ${mrpLine}
        ${!added && stock.ok
          ? `<span class="cc-qty-label">Qty:</span>
             <input type="number" class="qty-input cc-qty" value="1" min="1"
                    ${stockCount !== null ? `max="${stockCount}"` : ""}
                    id="qty-${escKey}"
                    oninput="checkQtyWarning(this, ${stockCount !== null ? stockCount : 'null'})"/>`
          : ""}
      </div>`;

    // ── FOOTER RIGHT: stepper if already in cart, else Add button ──
    const footerRight = added
      ? `<div class="cc-added-control">
           <button class="cc-qty-btn cc-stepper-btn" data-part="${escAttr(part)}" data-brand="${escAttr(brand)}" data-delta="-1" onclick="adjustCatalogueQty(this)">−</button>
           <span class="cc-added-qty">${cartQty}</span>
           <button class="cc-qty-btn cc-stepper-btn" data-part="${escAttr(part)}" data-brand="${escAttr(brand)}" data-delta="1" ${maxAttr} onclick="adjustCatalogueQty(this)">+</button>
         </div>`
      : `<button class="btn-add-to-cart2"
               data-key="${escKey}"
               data-brand="${escAttr(brand)}"
               onclick="handleAddToCart(this)"
               ${!stock.ok ? "disabled title='Out of stock'" : ""}>
           + Add
         </button>`;

    return `
      <div class="cat-card2 ${added ? "is-added" : ""} ${!stock.ok ? "is-out" : ""}" data-key="${escKey}" data-rawkey="${escKey}">
        <div class="cc-body">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
            <div class="cc-stock-row">${stockDot}</div>
            ${stock.ok
              ? `<div class="cc-instock-badge">In Stock</div>`
              : `<div class="cc-instock-badge out">Out of Stock</div>`}
          </div>
          <div class="cc-name">${part}</div>
          ${proxyTag}

          ${priceRow}

          ${discLine}
          <div id="warn-${escKey}" class="cc-qty-warn" style="display:none"></div>

          <div class="cc-footer">
            <span class="cc-brand">${brand}</span>
            ${footerRight}
          </div>
        </div>
      </div>`;
  }).join("");
}

// Inline qty warning for catalogue page (before adding)
function checkQtyWarning(input, stockCount) {
  if (stockCount === null || stockCount === undefined) return;
  const key  = input.id.replace(/^qty-/, "");
  const warn = document.getElementById(`warn-${key}`);
  if (!warn) return;
  const qty = parseInt(input.value, 10) || 0;
  if (qty > stockCount) {
    input.style.borderColor = "var(--accent)";
    warn.textContent = `⚠️ Only ${Math.round(stockCount)} in stock`;
    warn.style.display = "block";
  } else {
    input.style.borderColor = "";
    warn.style.display = "none";
  }
}

// ─── ADD TO CART ─────────────────────────────────────────────────────────────
function handleAddToCart(btn) {
  const decode = s => { const t = document.createElement("textarea"); t.innerHTML = s; return t.value; };
  const rawKey  = decode(btn.dataset.key);          // decoded "part|||brand"
  const rawBrand= decode(btn.dataset.brand);
  const [part]  = rawKey.split("|||");
  const brand   = rawBrand;

  const qtyEl   = document.getElementById(`qty-${btn.dataset.key}`);
  const qty     = Math.max(1, parseInt(qtyEl?.value || "1", 10));

  // Stock check
  const maxVal = qtyEl?.getAttribute("max");
  if (maxVal !== null && maxVal !== "" && qty > parseInt(maxVal, 10)) {
    if (qtyEl) qtyEl.style.borderColor = "var(--accent)";
    const warn = document.getElementById(`warn-${btn.dataset.key}`);
    if (warn) { warn.textContent = `⚠️ Only ${maxVal} in stock`; warn.style.display = "block"; }
    return;
  }

  // Persist
  const prev   = getSessionQty(part, brand);
  const newQty = prev + qty;
  setItemInSession(part, brand, newQty);

  // Mark card
  const card = btn.closest(".cat-card2");
  if (card) card.classList.add("is-added");

  // Swap Add button → stepper
  const footer = btn.closest(".cc-footer");
  if (footer) {
    const brandTag = footer.querySelector(".cc-brand")?.outerHTML || "";
    const escPart  = escAttr(part);
    const escBrand = escAttr(brand);
    const maxData  = maxVal ? `data-max="${maxVal}"` : "";
    footer.innerHTML = `
      ${brandTag}
      <div class="cc-added-control">
        <button class="cc-qty-btn cc-stepper-btn" data-part="${escPart}" data-brand="${escBrand}" data-delta="-1" onclick="adjustCatalogueQty(this)">−</button>
        <span class="cc-added-qty">${newQty}</span>
        <button class="cc-qty-btn cc-stepper-btn" data-part="${escPart}" data-brand="${escBrand}" data-delta="1" ${maxData} onclick="adjustCatalogueQty(this)">+</button>
      </div>`;
  }

  // Remove qty input from price row
  const priceRow = card?.querySelector(".cc-price-row");
  if (priceRow) {
    const priceSpan = priceRow.querySelector(".cc-price")?.outerHTML || "";
    const mrpSpan   = priceRow.querySelector(".cc-mrp")?.outerHTML || "";
    priceRow.innerHTML = priceSpan + mrpSpan;
  }
}

// ─── ADJUST QTY (stepper) ────────────────────────────────────────────────────
function adjustCatalogueQty(btn) {
  const decode = s => { const t = document.createElement("textarea"); t.innerHTML = s; return t.value; };
  const part   = decode(btn.dataset.part);
  const brand  = decode(btn.dataset.brand);
  const delta  = parseInt(btn.dataset.delta, 10);

  const cart    = loadCartFromSession();
  const current = cart[`${part}|||${brand}`] || 0;
  const newQty  = Math.max(0, current + delta);

  // Stock check on increase
  if (delta > 0) {
    const maxStock = btn.dataset.max ? parseInt(btn.dataset.max, 10) : Infinity;
    if (newQty > maxStock) {
      // Show warning on the card
      const card = btn.closest(".cat-card2");
      const warn = card?.querySelector(".cc-qty-warn");
      if (warn) { warn.textContent = `⚠️ Only ${maxStock} in stock`; warn.style.display = "block"; }
      return;
    }
  }

  if (newQty === 0) {
    setItemInSession(part, brand, 0);
    // Re-render just this one card back to un-added state
    filterCatalogue();
    return;
  }

  setItemInSession(part, brand, newQty);

  // Update display: find the qty span (sibling between the two buttons)
  const control = btn.closest(".cc-added-control");
  const qtySpan = control?.querySelector(".cc-added-qty");
  if (qtySpan) qtySpan.textContent = newQty;

  // Clear warning
  const card = btn.closest(".cat-card2");
  const warn = card?.querySelector(".cc-qty-warn");
  if (warn) warn.style.display = "none";
}