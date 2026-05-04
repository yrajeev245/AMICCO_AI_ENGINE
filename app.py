"""
Parts Discount Engine — app.py
================================
Sheet1: Part, Brand, SellingPrice, BuyingPrice, MinDiscount, MinMarginPercent,
        Stock, Priority, QtyThreshold, BonusDiscount_QtyThreshold,
        MinCartValue, BonusDiscount_MinCartValue
Sheet2: Order Reference, Quantity, Part   (sales history)
Sheet3: Part, PartProxy                   (grouping map)
Sheet4: Written by /api/refresh_reco      (recommendation matrix — for human review)
"""

import sys, os as _os
# Guard: prevent a local file named flask.py from shadowing the package
_this_dir = _os.path.dirname(_os.path.abspath(__file__))
if _this_dir in sys.path:
    sys.path.remove(_this_dir)
    sys.path.insert(0, _this_dir)  # keep it but after site-packages
try:
    from flask import Flask, request, jsonify, Response
except ImportError as _e:
    raise ImportError(
        f"Flask import failed: {_e}. Run: pip install flask"
    ) from _e
import json, urllib.request, os, io, zipfile, re, time
from collections import defaultdict
from itertools import combinations
from datetime import datetime
from xml.sax.saxutils import escape

app = Flask(__name__)

SHEET_ID   = "1_qYI5e9373-9Ay7oPlcR-9VQ6YJ5dsaOuyaPvE9ny8w"

# CSV export URLs have no row limit (gviz API caps at ~500 rows)
def _csv_url(gid: int) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
        f"/export?format=csv&gid={gid}"
    )

SHEET1_URL = _csv_url(0)            # Sheet1 — catalogue (gid=0 for first sheet)
SHEET2_URL = _csv_url(1270729691)    # Sheet2 — orders    (update gid if needed)
SHEET3_URL = _csv_url(440887828)   # Sheet3 — proxy map (update gid if needed)

CACHE_TTL_SECONDS = 300
_sheet_cache = {}
_reco_cache = {}

# ───────────────────────────────────────────────────────────────────────────
# 1. SHEET LOADING
# ───────────────────────────────────────────────────────────────────────────

def _fetch(url: str) -> list:
    """Fetch a CSV export URL → list of dicts keyed by header row.

    Uses the /export?format=csv endpoint which returns ALL rows with no
    limit (the old gviz/tq endpoint silently capped at ~500 rows).
    """
    cached = _sheet_cache.get(url)
    if cached and time.time() - cached["at"] < CACHE_TTL_SECONDS:
        return cached["rows"]

    try:
        import csv as _csv
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as res:
            raw = res.read().decode("utf-8-sig")   # strip BOM if present
        reader = _csv.DictReader(io.StringIO(raw))
        result = []
        for row in reader:
            # Skip completely empty rows
            if not any(v.strip() for v in row.values()):
                continue
            # Normalise: replace None keys (extra cols) and strip whitespace
            clean = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
            result.append(clean)
        _sheet_cache[url] = {"at": time.time(), "rows": result}
        return result
    except Exception as e:
        print(f"[fetch error] {url}: {e}")
        return []

def _f(val, default=0.0) -> float:
    """Safe float conversion; strips % signs."""
    try:
        return float(str(val).replace("%", "").strip())
    except:
        return default


def _key_id(text: str) -> str:
    """Normalise a sheet header/key for alias lookups."""
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _row_value(row: dict, *names: str) -> str:
    """Return the first non-empty value from a row across possible column names."""
    for name in names:
        value = row.get(name)
        if str(value or "").strip():
            return str(value).strip()

    normalised = {_key_id(k): v for k, v in row.items()}
    for name in names:
        value = normalised.get(_key_id(name))
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _part_key(text: str) -> str:
    """Normalise part names for resilient proxy/reco matching."""
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def resolve_proxy(part: str, proxy_map: dict, normalised_proxy_map: dict | None = None) -> str:
    """Map a part to its proxy using exact match first, then normalised match."""
    part = str(part or "").strip()
    if not part:
        return ""
    if part in proxy_map:
        return proxy_map[part]
    lookup = normalised_proxy_map
    if lookup is None:
        lookup = {_part_key(p): proxy for p, proxy in proxy_map.items()}
    return lookup.get(_part_key(part), part)


def _stock_ok_row(row: dict) -> bool:
    """True if stock is blank/missing OR > 0. Only hides rows with explicit stock <= 0."""
    raw = row.get('stock', row.get('Stock', ''))
    s = str(raw).strip()
    if not s:
        return True
    try:
        return float(s) > 0
    except (ValueError, TypeError):
        return True

def _normalise(row: dict) -> dict:
    """
    Normalise Sheet1 column names → snake_case keys used in code.
    New columns:
      QtyThreshold              → qty_threshold
      BonusDiscount_QtyThreshold → bonus_disc_qty
      MinCartValue              → min_cart_value
      BonusDiscount_MinCartValue → bonus_disc_cart
      MinDiscount               → min_discount   (floor, always given)
    """
    ALIASES = {
        "sellingprice":              "selling_price",
        "buyingprice":               "buying_price",
        "mindiscount":               "min_discount",
        "minmarginpercent":          "min_margin_percent",
        "qtythreshold":              "qty_threshold",
        "bonusdiscount_qtythreshold":"bonus_disc_qty",
        "mincartvalue":              "min_cart_value",
        "bonusdiscount_mincartvalue":"bonus_disc_cart",
    }
    out = {}
    for k, v in row.items():
        key = k.strip().lower().replace(" ", "_")
        out[ALIASES.get(key, key)] = v
    return out

def load_catalogue() -> list:
    return [_normalise(r) for r in _fetch(SHEET1_URL)]

def load_raw() -> list:
    """Raw Sheet1 — for /api/data dropdown population."""
    return _fetch(SHEET1_URL)

def load_orders() -> list:
    return _fetch(SHEET2_URL)

def load_proxy_map() -> dict:
    """Returns {part_name: proxy_name} from Sheet3."""
    out = {}
    for r in _fetch(SHEET3_URL):
        p = _row_value(r, "Part", "Product Template/Name", "Product")
        x = _row_value(r, "PartProxy", "Part Proxy", "Proxy", "Recommendation Proxy")
        if p and x:
            out[p] = x
    return out

def find_row(catalogue, part, brand):
    for r in catalogue:
        if r.get("part") == part and r.get("brand") == brand:
            return r
    return None

def proxy_label_parts(proxy: str) -> tuple:
    """
    Parse recommendation labels like 'Part Name[Brand Name]' into
    (part_name, brand_name). If no brand is embedded, brand_name is None.
    """
    text = str(proxy or "").strip()
    if text.endswith("]") and "[" in text:
        part, brand = text.rsplit("[", 1)
        return part.strip(), brand[:-1].strip()
    return text, None

# ───────────────────────────────────────────────────────────────────────────
# 2. PRICING ENGINE
# ───────────────────────────────────────────────────────────────────────────

def compute_pricing(row: dict, qty: int, cart_total_sp: float = 0) -> dict:
    """
    Discount layers (additive):
      1. MinDiscount  — always given (floor)
      2. +BonusDiscount_QtyThreshold  if qty >= QtyThreshold
      3. +BonusDiscount_MinCartValue  if cart_total_sp >= MinCartValue
      4. Margin guard — step down 0.5% until margin >= MinMarginPercent

    Returns:
      selling_price   — original SP (shown as "Unit Price" in UI)
      final_price     — SP after discount (what garage pays)
      discount        — actual % applied
      total           — final_price × qty
      profit          — (final_price − buying_price) × qty
      margin          — profit / (buying_price × qty) × 100
      qty_bonus_available  — True if qty threshold not yet hit (for suggestions)
      cart_bonus_available — True if cart threshold not yet hit (for suggestions)
    """
    sp         = _f(row.get("selling_price", 0))
    bp         = _f(row.get("buying_price",  0))
    min_disc   = _f(row.get("min_discount",  0))   # floor — always given
    min_margin = _f(row.get("min_margin_percent", 6))
    qty_thresh = _f(row.get("qty_threshold",  0))
    bonus_qty  = _f(row.get("bonus_disc_qty", 0))
    cart_thresh= _f(row.get("min_cart_value", 0))
    bonus_cart = _f(row.get("bonus_disc_cart",0))

    discount = min_disc

    # Layer 2: qty bonus
    qty_bonus_hit = qty_thresh > 0 and qty >= qty_thresh
    if qty_bonus_hit:
        discount += bonus_qty

    # Layer 3: cart value bonus
    cart_bonus_hit = cart_thresh > 0 and cart_total_sp >= cart_thresh
    if cart_bonus_hit:
        discount += bonus_cart

    # Layer 4: margin guard
    while discount > 0:
        final  = sp * (1 - discount / 100)
        profit = final - bp
        margin = (profit / bp) * 100 if bp else 0
        if margin >= min_margin:
            break
        discount -= 0.5

    if discount <= 0:
        discount = 0
        final    = sp
        profit   = final - bp
        margin   = (profit / bp) * 100 if bp else 0

    return {
        "selling_price":         round(sp, 2),        # original SP
        "final_price":           round(final, 2),      # what garage pays per unit
        "discount":              round(discount, 2),   # % off
        "total":                 round(final * qty, 2),
        "profit":                round(profit * qty, 2),
        "margin":                round(margin, 2),
        # metadata for suggestion engine
        "qty_bonus_available":   qty_thresh > 0 and not qty_bonus_hit,
        "qty_threshold":         int(qty_thresh) if qty_thresh > 0 else None,
        "bonus_disc_qty":        bonus_qty,
        "cart_bonus_available":  cart_thresh > 0 and not cart_bonus_hit,
        "cart_bonus_hit":        cart_bonus_hit,
        "min_cart_value":        cart_thresh,
        "bonus_disc_cart":       bonus_cart,
        "min_discount":          round(min_disc, 2),
    }

# ───────────────────────────────────────────────────────────────────────────
# 3. CART EVALUATION (two-pass)
# ───────────────────────────────────────────────────────────────────────────

def evaluate_cart(cart: list, catalogue: list) -> dict:
    """
    Pass 1: compute cart_total_sp (sum of SP×qty) needed for MinCartValue check.
    Pass 2: price every item with full bonus knowledge.
    """
    # Pass 1
    cart_total_sp = 0
    for item in cart:
        row = find_row(catalogue, item["part"], item["brand"])
        if row:
            cart_total_sp += _f(row.get("selling_price", 0)) * item["qty"]

    # Pass 2
    total_final_rev = 0
    total_cost      = 0
    total_sp        = 0
    items, errors   = [], []

    for item in cart:
        row = find_row(catalogue, item["part"], item["brand"])
        if not row:
            errors.append(f"Part not found: {item['part']} ({item['brand']})")
            continue

        pricing = compute_pricing(row, item["qty"], cart_total_sp)

        total_final_rev += pricing["total"]
        total_cost      += _f(row.get("buying_price", 0)) * item["qty"]
        total_sp        += pricing["selling_price"] * item["qty"]

        items.append({**item, **pricing})

    profit       = total_final_rev - total_cost
    margin       = (profit / total_final_rev) * 100 if total_final_rev else 0
    eff_discount = ((total_sp - total_final_rev) / total_sp * 100) if total_sp else 0

    return {
        "items":        items,
        "total_sp":     round(total_sp, 2),           # cart at full SP
        "revenue":      round(total_final_rev, 2),    # cart after discounts
        "profit":       round(profit, 2),
        "margin":       round(margin, 2),
        "eff_discount": round(eff_discount, 2),
        "errors":       errors,
    }

# ───────────────────────────────────────────────────────────────────────────
# 4. SMART SUGGESTIONS
# ───────────────────────────────────────────────────────────────────────────

def build_suggestions(cart: list, catalogue: list, result: dict) -> list:
    """
    Two suggestion types:
      cart  — spend more to hit MinCartValue and unlock bonus
      brand — switch brand to one with higher MinDiscount floor

    Qty nudges are intentionally kept out of Smart Recommendations and shown
    only in the target-discount section.
    """
    suggestions = []
    seen_cart_msg = False   # only show cart-value suggestion once
    seen_cart_active_msg = False
    cart_bonus_part_seen = False

    for item in result["items"]:
        row = find_row(catalogue, item["part"], item["brand"])
        if not row:
            continue

        # --- Cart value bonus already active ---
        if item.get("cart_bonus_hit") and item.get("bonus_disc_cart", 0) > 0 and not seen_cart_active_msg:
            cart_bonus_part_seen = True
            eligible = [
                i for i in result["items"]
                if i.get("cart_bonus_hit")
                and i.get("bonus_disc_cart", 0) > 0
                and i.get("min_cart_value") == item.get("min_cart_value")
                and i.get("bonus_disc_cart") == item.get("bonus_disc_cart")
            ]
            eligible_text = ", ".join(
                f"{i['part']} ({i['brand']})" for i in eligible[:3]
            )
            if len(eligible) > 3:
                eligible_text += f" +{len(eligible) - 3} more"

            suggestions.append({
                "type": "cart",
                "icon": "🛒",
                "message": (
                    f"Cart total crossed <span class='sugg-bold'>₹{item['min_cart_value']:,.0f}</span>, "
                    f"so <span class='sugg-bold'>{eligible_text}</span> gets "
                    f"<span class='sugg-bold'>+{item['bonus_disc_cart']}% cart bonus</span>."
                )
            })
            seen_cart_active_msg = True

        # --- Cart value bonus suggestion (show once, for first eligible item) ---
        if item.get("cart_bonus_available") and item.get("bonus_disc_cart", 0) > 0 and not seen_cart_msg:
            cart_bonus_part_seen = True
            shortfall = round(item["min_cart_value"] - result["total_sp"], 2)
            if shortfall > 0:
                eligible = [
                    i for i in result["items"]
                    if i.get("cart_bonus_available")
                    and i.get("bonus_disc_cart", 0) > 0
                    and i.get("min_cart_value") == item.get("min_cart_value")
                    and i.get("bonus_disc_cart") == item.get("bonus_disc_cart")
                ]
                eligible_text = ", ".join(
                    f"{i['part']} ({i['brand']})" for i in eligible[:3]
                )
                if len(eligible) > 3:
                    eligible_text += f" +{len(eligible) - 3} more"

                add_ideas = cart_bonus_add_candidates(cart, catalogue, result, shortfall, limit=3)
                ideas_text = "; ".join(
                    f"{'Add ' + str(i['qty']) + ' x ' if i['qty'] > 1 else ''}{i['part']} ({i['brand']}) - ₹{i['add_value']:,.0f}"
                    for i in add_ideas
                )
                suggestions.append({
                    "type": "cart",
                    "icon": "🛒",
                    "actions": add_ideas,
                    "message": (
                        f"Add <span class='sugg-bold'>₹{shortfall:,.0f} more</span> "
                        f"to cart total to unlock "
                        f"<span class='sugg-bold'>+{item['bonus_disc_cart']}% cart bonus</span> "
                        f"on <span class='sugg-bold'>{eligible_text}</span> "
                        f"(threshold: ₹{item['min_cart_value']:,.0f}). "
                        f"Any parts can be added to reach the threshold."
                    )
                })
                seen_cart_msg = True

        if item.get("bonus_disc_cart", 0) > 0:
            cart_bonus_part_seen = True

        # --- Brand switch suggestion ---
        min_disc    = _f(row.get("min_discount", 0))
        same_part   = [r for r in catalogue if r.get("part") == item["part"] and _stock_ok_row(r)]
        better      = sorted(
            [
                r for r in same_part
                if r.get("brand") != item["brand"]
                and _f(r.get("min_discount", 0)) > min_disc
            ],
            key=lambda r: _f(r.get("min_discount", 0)),
            reverse=True
        )
        for alt in better[:1]:
            suggestions.append({
                "type": "brand",
                "icon": "🔄",
                "part": item["part"],
                "from_brand": item["brand"],
                "to_brand": alt["brand"],
                "message": (
                    f"Switch <span class='sugg-bold'>{item['part']}</span> "
                    f"from <span class='sugg-bold'>{item['brand']}</span> → "
                    f"<span class='sugg-bold'>{alt['brand']}</span> "
                    f"for higher base discount: "
                    f"<span class='sugg-bold'>{_f(alt.get('min_discount',0))}%</span> "
                    f"vs {min_disc}%"
                )
            })

    if not cart_bonus_part_seen:
        opportunities = cart_bonus_catalogue_opportunities(catalogue, result["total_sp"], limit=3)
        if opportunities:
            suggestions.insert(0, {
                "type": "cart",
                "icon": "🛒",
                "actions": [
                    {
                        "part": o["part"],
                        "brand": o["brand"],
                        "qty": 1,
                        "selling_price": o["selling_price"],
                        "add_value": o["selling_price"],
                        "bonus_disc_cart": o["bonus_disc_cart"],
                        "min_cart_value": o["min_cart_value"],
                    }
                    for o in opportunities
                ],
                "message": (
                    "Cart-value discount parts available. "
                    "Add the eligible part, then add any other parts to reach the cart value. "
                    "The extra discount applies to the eligible part."
                )
            })

    return suggestions


def cart_bonus_catalogue_opportunities(catalogue: list, cart_total_sp: float,
                                       limit: int = 3) -> list:
    """Top catalogue parts that have a cart-value bonus configured."""
    by_part = {}
    for row in catalogue:
        part = row.get("part")
        brand = row.get("brand")
        bonus = _f(row.get("bonus_disc_cart", 0))
        threshold = _f(row.get("min_cart_value", 0))
        sp = _f(row.get("selling_price", 0))
        if not part or not brand or bonus <= 0 or threshold <= 0 or sp <= 0 or not _stock_ok_row(row):
            continue

        candidate = {
            "part": part,
            "brand": brand,
            "bonus_disc_cart": bonus,
            "min_cart_value": threshold,
            "selling_price": sp,
            "shortfall": max(0, threshold - cart_total_sp),
        }
        existing = by_part.get(part)
        if not existing or (
            candidate["shortfall"],
            -candidate["bonus_disc_cart"],
            candidate["selling_price"],
        ) < (
            existing["shortfall"],
            -existing["bonus_disc_cart"],
            existing["selling_price"],
        ):
            by_part[part] = candidate

    return sorted(
        by_part.values(),
        key=lambda o: (o["shortfall"], -o["bonus_disc_cart"], o["selling_price"])
    )[:limit]


def cart_bonus_add_candidates(cart: list, catalogue: list, result: dict,
                              shortfall: float, limit: int = 3) -> list:
    """Suggest compact add-on options that can bridge a cart-value shortfall."""
    cart_keys = {(i["part"], i["brand"]) for i in result["items"]}
    best_by_part = {}

    for row in catalogue:
        part = row.get("part")
        brand = row.get("brand")
        sp = _f(row.get("selling_price", 0))
        if not part or not brand or sp <= 0:
            continue
        if not _stock_ok_row(row):
            continue
        if (part, brand) in cart_keys:
            continue

        qty = max(1, int((shortfall + sp - 0.01) // sp))
        add_value = sp * qty
        candidate = {
            "part": part,
            "brand": brand,
            "selling_price": sp,
            "qty": qty,
            "add_value": add_value,
            "overage": add_value - shortfall,
            "min_discount": _f(row.get("min_discount", 0)),
        }

        existing = best_by_part.get(part)
        if not existing or (
            candidate["qty"],
            candidate["overage"],
            -candidate["min_discount"],
            candidate["selling_price"],
        ) < (
            existing["qty"],
            existing["overage"],
            -existing["min_discount"],
            existing["selling_price"],
        ):
            best_by_part[part] = candidate

    return sorted(
        best_by_part.values(),
        key=lambda i: (i["qty"], i["overage"], -i["min_discount"], i["selling_price"])
    )[:limit]

# ───────────────────────────────────────────────────────────────────────────
# 5. TARGET DISCOUNT ADVISOR
# ───────────────────────────────────────────────────────────────────────────

def top_discount_lift_additions(cart: list, catalogue: list, result: dict,
                                limit: int = 3) -> list:
    """
    Find the best different parts to add for improving overall discount.

    For each catalogue row not already in cart, simulate adding qty 1. Keep only
    the strongest brand variant per part, then return the top candidates by
    projected effective discount and revenue impact.
    """
    cart_keys = {(i["part"], i["brand"]) for i in result["items"]}
    cart_parts = {i["part"] for i in result["items"]}
    best_by_part = {}

    for r in catalogue:
        part = r.get("part")
        brand = r.get("brand")
        if not part or not brand:
            continue
        if (part, brand) in cart_keys or part in cart_parts:
            continue
        if not _stock_ok_row(r):
            continue

        test_cart = [dict(i) for i in cart] + [{"part": part, "brand": brand, "qty": 1}]
        projected = evaluate_cart(test_cart, catalogue)
        gain = projected["eff_discount"] - result["eff_discount"]

        candidate = {
            "part": part,
            "brand": brand,
            "selling_price": _f(r.get("selling_price", 0)),
            "min_discount": _f(r.get("min_discount", 0)),
            "projected_discount": projected["eff_discount"],
            "discount_gain": gain,
            "projected_revenue": projected["revenue"],
        }

        existing = best_by_part.get(part)
        if not existing:
            best_by_part[part] = candidate
            continue

        current_rank = (
            candidate["projected_discount"],
            candidate["discount_gain"],
            candidate["min_discount"],
            -candidate["selling_price"],
        )
        existing_rank = (
            existing["projected_discount"],
            existing["discount_gain"],
            existing["min_discount"],
            -existing["selling_price"],
        )
        if current_rank > existing_rank:
            best_by_part[part] = candidate

    ranked = sorted(
        best_by_part.values(),
        key=lambda c: (
            c["projected_discount"],
            c["discount_gain"],
            c["min_discount"],
            -c["selling_price"],
        ),
        reverse=True,
    )
    return ranked[:limit]

def build_target_advice(cart: list, catalogue: list, result: dict, target: float) -> list:
    current = result["eff_discount"]
    if current >= target:
        return []

    gap    = round(target - current, 2)
    advice = [{
        "type": "target", "icon": "📊",
        "message": (
            f"Current effective discount is <span class='sugg-bold'>{current:.1f}%</span>. "
            f"You need <span class='sugg-bold'>{gap:.1f}% more</span> to reach {target}%."
        )
    }]

    # 1. Qty bumps not yet hit
    for item in result["items"]:
        if item.get("qty_bonus_available") and item.get("qty_threshold"):
            advice.append({
                "type": "qty", "icon": "📦",
                "message": (
                    f"Increase qty of <span class='sugg-bold'>{item['part']} ({item['brand']})</span> "
                    f"to {item['qty_threshold']}+ to unlock "
                    f"<span class='sugg-bold'>+{item['bonus_disc_qty']}% bonus discount</span>"
                )
            })

    # 2. Brand switches to higher floor
    for item in result["items"]:
        row = find_row(catalogue, item["part"], item["brand"])
        if not row: continue
        cur_min   = _f(row.get("min_discount", 0))
        same_part = [r for r in catalogue if r.get("part") == item["part"] and _stock_ok_row(r)]
        better    = sorted(
            [
                r for r in same_part
                if r.get("brand") != item["brand"]
                and _f(r.get("min_discount", 0)) > cur_min
            ],
            key=lambda r: _f(r.get("min_discount", 0)), reverse=True
        )
        for alt in better[:1]:
            advice.append({
                "type": "brand", "icon": "🔄",
                "part": item["part"],
                "from_brand": item["brand"],
                "to_brand": alt["brand"],
                "message": (
                    f"Switch <span class='sugg-bold'>{item['part']}</span> → "
                    f"<span class='sugg-bold'>{alt['brand']}</span> "
                    f"(min discount: <span class='sugg-bold'>{_f(alt.get('min_discount',0))}%</span> "
                    f"vs current {cur_min}%)"
                )
            })

    # 3. Best different parts to lift overall discount
    for r in top_discount_lift_additions(cart, catalogue, result, limit=3):
        gain_text = f"+{r['discount_gain']:.1f}%" if r["discount_gain"] > 0 else "best available lift"
        advice.append({
            "type": "add", "icon": "➕",
            "actions": [{
                "part": r["part"],
                "brand": r["brand"],
                "qty": 1,
                "selling_price": r["selling_price"],
                "add_value": r["selling_price"],
            }],
            "message": (
                f"Add <span class='sugg-bold'>{r['part']} ({r['brand']}) - ₹{r['selling_price']:,.0f}</span> "
                f"to reach about <span class='sugg-bold'>{r['projected_discount']:.1f}%</span> "
                f"overall discount ({gain_text})"
            )
        })

    return advice

# ───────────────────────────────────────────────────────────────────────────
# 6. RECOMMENDATION ENGINE (Jaccard + Lift + Co-occurrence)
# ───────────────────────────────────────────────────────────────────────────

def compute_reco_map(top_n: int = 10) -> dict:
    """
    Build proxy→ranked-recommendations map from Sheet2 order history.

    Algorithm:
      1. Load orders (Sheet2) + proxy map (Sheet3)
      2. Group by Order Reference → basket of PartProxy values (sets, no duplicates)
      3. Compute frequency[proxy] and pair_count[(A,B)]
      4. For each pair compute Jaccard and Lift
      5. Filter pairs with count < 2 (noise)
      6. Rank by composite score: 0.6×normalised_jaccard + 0.4×normalised_lift
      7. Return top_n per proxy

    Why composite score instead of pure Jaccard?
      Jaccard can be high for very niche pairs; Lift rewards truly above-random
      co-purchase. Blending gives the best real-world results.
    """
    cache_key = f"reco:{top_n}"
    cached = _reco_cache.get(cache_key)
    if cached and time.time() - cached["at"] < CACHE_TTL_SECONDS:
        return cached["map"]

    orders    = load_orders()
    proxy_map = load_proxy_map()
    normalised_proxy_map = {_part_key(p): proxy for p, proxy in proxy_map.items()}

    if not orders:
        _reco_cache[cache_key] = {"at": time.time(), "map": {}}
        return {}

    # Step 2: build baskets
    baskets: dict = defaultdict(set)
    for r in orders:
        ref  = str(r.get("Order Reference", "")).strip()
        part = _row_value(
            r,
            "Part",
            "Product Template/Name",
            "Product",
            "Product Name",
            "Item",
        )
        if not ref or not part:
            continue
        proxy = resolve_proxy(part, proxy_map, normalised_proxy_map)
        baskets[ref].add(proxy)

    total_orders = len(baskets)
    if total_orders == 0:
        _reco_cache[cache_key] = {"at": time.time(), "map": {}}
        return {}

    # Step 3: frequency and pair counts
    frequency:  dict = defaultdict(int)
    pair_count: dict = defaultdict(int)

    for basket in baskets.values():
        items = sorted(basket)
        for p in items:
            frequency[p] += 1
        for a, b in combinations(items, 2):   # sorted tuples = no (A,B)/(B,A) duplicates
            pair_count[(a, b)] += 1

    # Step 4 & 5: Jaccard, Lift, composite score
    # Build raw scores first so we can normalise
    raw: dict = {}   # (a, b) → {count, jaccard, lift}

    for (a, b), count in pair_count.items():
        if count < 2:
            continue   # skip noise

        union   = frequency[a] + frequency[b] - count
        jaccard = count / union if union > 0 else 0

        prob_a  = frequency[a] / total_orders
        prob_b  = frequency[b] / total_orders
        prob_ab = count / total_orders
        lift    = prob_ab / (prob_a * prob_b) if prob_a * prob_b > 0 else 0

        raw[(a, b)] = {"count": count, "jaccard": jaccard, "lift": lift}

    if not raw:
        _reco_cache[cache_key] = {"at": time.time(), "map": {}}
        return {}

    # Normalise Jaccard and Lift to [0,1] for fair blending
    max_j = max(v["jaccard"] for v in raw.values()) or 1
    max_l = max(v["lift"]    for v in raw.values()) or 1

    # Step 6: composite score and build reco_map
    reco_map: dict = defaultdict(list)

    for (a, b), scores in raw.items():
        norm_j  = scores["jaccard"] / max_j
        norm_l  = scores["lift"]    / max_l
        composite = round(0.6 * norm_j + 0.4 * norm_l, 6)

        entry_for_a = {
            "proxy":     b,
            "count":     scores["count"],
            "jaccard":   round(scores["jaccard"], 4),
            "lift":      round(scores["lift"], 4),
            "score":     composite,
        }
        entry_for_b = {
            "proxy":     a,
            "count":     scores["count"],
            "jaccard":   round(scores["jaccard"], 4),
            "lift":      round(scores["lift"], 4),
            "score":     composite,
        }
        reco_map[a].append(entry_for_a)
        reco_map[b].append(entry_for_b)

    # Step 7: sort by composite score DESC, keep top_n
    for proxy in reco_map:
        reco_map[proxy] = sorted(reco_map[proxy], key=lambda x: x["score"], reverse=True)[:top_n]

    out = dict(reco_map)
    _reco_cache[cache_key] = {"at": time.time(), "map": out}
    return out


def _products_for_proxy(proxy: str, rev_proxy: dict, catalogue: list) -> list:
    """Resolve a recommendation proxy back to in-stock catalogue variants."""
    part_names = rev_proxy.get(proxy, [proxy])
    products = sorted(
        [r for r in catalogue if r.get("part") in part_names and _stock_ok_row(r)],
        key=lambda r: _f(r.get("selling_price", 0))
    )
    if products:
        return products

    proxy_part, proxy_brand = proxy_label_parts(proxy)
    products = [
        r for r in catalogue
        if r.get("part") == proxy_part
        and (not proxy_brand or r.get("brand") == proxy_brand)
        and _stock_ok_row(r)
    ]
    if products:
        return sorted(products, key=lambda r: _f(r.get("selling_price", 0)))

    proxy_part_l = proxy_part.lower()
    proxy_brand_l = proxy_brand.lower() if proxy_brand else ""
    products = [
        r for r in catalogue
        if (
            r.get("part", "").lower() in proxy_part_l
            or proxy_part_l in r.get("part", "").lower()
        )
        and (
            not proxy_brand_l
            or r.get("brand", "").lower() == proxy_brand_l
            or r.get("brand", "").lower() in proxy_part_l
        )
        and _stock_ok_row(r)
    ]
    return sorted(products, key=lambda r: _f(r.get("selling_price", 0)))


def _popular_proxy_recos(cart_proxies: set, proxy_map: dict, catalogue: list,
                         top_n: int = 5) -> list:
    """
    Fallback for sparse carts: show popular order-history add-ons so the
    Bought Together section does not go blank when a direct pair is missing.
    """
    orders = load_orders()
    if not orders:
        return []

    normalised_proxy_map = {_part_key(p): proxy for p, proxy in proxy_map.items()}
    frequency = defaultdict(int)
    for r in orders:
        part = _row_value(
            r,
            "Part",
            "Product Template/Name",
            "Product",
            "Product Name",
            "Item",
        )
        proxy = resolve_proxy(part, proxy_map, normalised_proxy_map)
        if proxy and proxy not in cart_proxies:
            frequency[proxy] += 1

    if not frequency:
        return []

    rev_proxy = defaultdict(list)
    for part, proxy in proxy_map.items():
        rev_proxy[proxy].append(part)

    results = []
    for proxy, count in sorted(frequency.items(), key=lambda x: x[1], reverse=True):
        products = _products_for_proxy(proxy, rev_proxy, catalogue)
        if not products:
            continue
        results.append({
            "proxy": proxy,
            "jaccard": 0,
            "lift": 1,
            "score": 0,
            "count": count,
            "products": products,
            "fallback": True,
        })
        if len(results) >= top_n:
            break
    return results


def get_cart_recos(cart_items: list, reco_map: dict, proxy_map: dict,
                   catalogue: list, top_n: int = 5) -> list:
    """
    Given a cart, return top product recommendations.

    Steps:
      1. Map each cart item to its PartProxy
      2. Collect all reco candidates for those proxies
      3. Remove proxies already in the cart
      4. Aggregate: for same target proxy seen from multiple cart items,
         take MAX scores (union of signals)
      5. Rank by composite score, resolve back to catalogue rows
      6. Return top_n with all brand variants attached
    """
    # Reverse proxy: proxy → [part names]
    rev_proxy: dict = defaultdict(list)
    for part, proxy in proxy_map.items():
        rev_proxy[proxy].append(part)

    normalised_proxy_map = {_part_key(p): proxy for p, proxy in proxy_map.items()}

    cart_proxies = {
        resolve_proxy(i.get("part", ""), proxy_map, normalised_proxy_map)
        for i in cart_items
    }

    combined: dict = {}
    if reco_map:
        for item in cart_items:
            item_proxy = resolve_proxy(item.get("part", ""), proxy_map, normalised_proxy_map)
            for rec in reco_map.get(item_proxy, []):
                tp = rec["proxy"]
                if tp in cart_proxies:
                    continue
                if tp not in combined:
                    combined[tp] = rec.copy()
                else:
                    # Union of signals — take max
                    combined[tp]["jaccard"] = max(combined[tp]["jaccard"], rec["jaccard"])
                    combined[tp]["lift"]    = max(combined[tp]["lift"],    rec["lift"])
                    combined[tp]["score"]   = max(combined[tp]["score"],   rec["score"])
                    combined[tp]["count"]   = max(combined[tp]["count"],   rec["count"])

    ranked = sorted(combined.values(), key=lambda x: x["score"], reverse=True)[:top_n]

    results = []
    for rec in ranked:
        proxy = rec["proxy"]
        products = _products_for_proxy(proxy, rev_proxy, catalogue)
        if not products:
            continue
        results.append({
            "proxy":    proxy,
            "jaccard":  rec["jaccard"],
            "lift":     rec["lift"],
            "score":    rec["score"],
            "count":    rec["count"],
            "products": products,
        })

    if len(results) < top_n:
        seen = {r["proxy"] for r in results} | cart_proxies
        for rec in _popular_proxy_recos(seen, proxy_map, catalogue, top_n - len(results)):
            if rec["proxy"] not in seen:
                results.append(rec)
                seen.add(rec["proxy"])

    return results


def build_reco_sheet_data(reco_map: dict, proxy_map: dict) -> list:
    """
    Build flat rows for the Sheet4 review tab.
    Each row includes the recommendation category and a top recommendation label
    so the exported report can be analysed directly.
    """
    seen = set()
    rows = [[
        "Recommendation Category", "Product A", "Product B", "Top Recommendation",
        "Co-orders", "Jaccard", "Lift", "Score", "Strength"
    ]]

    for proxy_a, recs in reco_map.items():
        for rec in recs:
            proxy_b = rec["proxy"]
            key     = tuple(sorted([proxy_a, proxy_b]))
            if key in seen:
                continue
            seen.add(key)

            score  = rec["score"]
            if score >= 0.7:   strength = "🔴 Very Strong"
            elif score >= 0.4: strength = "🟠 Strong"
            elif score >= 0.2: strength = "🟡 Moderate"
            else:              strength = "⚪ Weak"

            top_label = f"{proxy_b} with {proxy_a}" if rec["score"] >= 0.4 else f"Test {proxy_b} with {proxy_a}"
            rows.append([
                "Bought Together", proxy_a, proxy_b, top_label,
                rec["count"],
                rec["jaccard"],
                rec["lift"],
                rec["score"],
                strength,
            ])

    # Sort by score DESC (skip header row)
    rows[1:] = sorted(rows[1:], key=lambda r: r[7], reverse=True)
    return rows


def strip_html(text: str) -> str:
    """Convert UI suggestion markup into readable spreadsheet text."""
    return re.sub(r"<[^>]+>", "", str(text or "")).replace("→", "to")


def xlsx_col(idx: int) -> str:
    """1-based column number to Excel letters."""
    letters = ""
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def sheet_xml(rows: list) -> str:
    xml_rows = []
    for r_idx, row in enumerate(rows, 1):
        cells = []
        for c_idx, value in enumerate(row, 1):
            ref = f"{xlsx_col(c_idx)}{r_idx}"
            if value is None or value == "":
                cells.append(f'<c r="{ref}"/>')
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                )
        xml_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(xml_rows)}</sheetData>'
        '</worksheet>'
    )


def make_xlsx(sheets: list) -> bytes:
    """
    Build a compact Excel workbook without external dependencies.
    sheets = [(sheet_name, rows), ...]
    """
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        overrides = [
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
            '<Default Extension="xml" ContentType="application/xml"/>',
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        ]
        for i in range(1, len(sheets) + 1):
            overrides.append(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            f'{"".join(overrides)}</Types>'
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        )
        sheet_refs = []
        rels = []
        for i, (name, _) in enumerate(sheets, 1):
            sheet_refs.append(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>')
            rels.append(
                f'<Relationship Id="rId{i}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{i}.xml"/>'
            )
        z.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(sheet_refs)}</sheets></workbook>'
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{"".join(rels)}</Relationships>'
        )
        for i, (_, rows) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml(rows))
    return out.getvalue()


def build_report_sheets(cart: list, target, catalogue: list,
                        result: dict, suggestions: list, target_advice: list,
                        recos: list, reco_map: dict, proxy_map: dict) -> list:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary_rows = [
        ["Parts Discount Engine - Combinations Report"],
        ["Generated At", generated_at],
        [],
        ["Metric", "Value"],
        ["Total Cart Value", result.get("total_sp", 0)],
        ["Discount Given %", result.get("eff_discount", 0)],
        ["Value After Discount", result.get("revenue", 0)],
        ["Target Discount %", target or ""],
    ]

    cart_rows = [["Part", "Brand", "Qty", "Selling Price", "Discount %", "Final Price", "Total"]]
    for item in result.get("items", []):
        cart_rows.append([
            item.get("part"), item.get("brand"), item.get("qty"),
            item.get("selling_price"), item.get("discount"),
            item.get("final_price"), item.get("total"),
        ])

    nudge_rows = [["Category", "Nudge"]]
    for s in suggestions:
        nudge_rows.append(["Smart Recommendation", strip_html(s.get("message"))])
    for s in target_advice:
        nudge_rows.append(["To Reach Target Discount", strip_html(s.get("message"))])

    bought_rows = [["Recommended Proxy", "Variant Part", "Brand", "Selling Price", "Co-orders", "Jaccard", "Lift", "Score"]]
    for rec in recos:
        for p in rec.get("products", []):
            bought_rows.append([
                rec.get("proxy"), p.get("part"), p.get("brand"),
                _f(p.get("selling_price", 0)), rec.get("count"),
                rec.get("jaccard"), rec.get("lift"), rec.get("score"),
            ])

    if len(cart_rows) == 1:
        cart_rows.append(["No current cart selected", "", "", "", "", "", ""])
    if len(nudge_rows) == 1:
        nudge_rows.append(["No nudges", "Current cart has no additional advice."])
    if len(bought_rows) == 1:
        bought_rows.append(["No bought-together recommendations", "", "", "", "", "", "", ""])

    return [
        ("Summary", summary_rows),
        ("Cart", cart_rows),
        ("Recommendation Nudges", nudge_rows),
        ("Bought Together", bought_rows),
        ("Sheet4", build_reco_sheet_data(reco_map, proxy_map)),
    ]

# ───────────────────────────────────────────────────────────────────────────
# 7. ROUTES
# ───────────────────────────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.abspath(__file__))

@app.route("/")
def index():
    with open(os.path.join(ROOT, "index.html")) as f:
        return f.read(), 200, {"Content-Type": "text/html"}

@app.route("/<path:filename>")
def static_files(filename):
    fp = os.path.join(ROOT, filename)
    if not os.path.isfile(fp):
        return "Not found", 404
    ext  = filename.rsplit(".", 1)[-1]
    mime = {"html": "text/html", "css": "text/css", "js": "application/javascript"}.get(ext, "text/plain")
    with open(fp) as f:
        return f.read(), 200, {"Content-Type": mime}

@app.route("/api/data")
def api_data():
    raw = load_raw()
    if not raw:
        return jsonify({"error": "Could not load sheet"}), 500
    # Only hide parts where Stock is explicitly set to 0 or negative.
    # Blank / missing stock = treated as in-stock (show it).
    def _stock_ok(r):
        raw_val = r.get("Stock", r.get("stock", ""))
        s = str(raw_val).strip()
        if not s:
            return True
        try:
            return float(s) > 0
        except (ValueError, TypeError):
            return True
    in_stock = [r for r in raw if _stock_ok(r)]
    return jsonify(in_stock)

@app.route("/api/proxy_map")
def api_proxy_map():
    """Returns {part_name: proxy_name} from Sheet3 for catalogue filtering."""
    proxy_map = load_proxy_map()
    return jsonify(proxy_map)

@app.route("/api/deal", methods=["POST"])
def api_deal():
    """
    POST { cart: [{part, brand, qty}], target_discount: float|null }
    Returns { result, suggestions, target_advice, recommendations }
    """
    body   = request.get_json(force=True) or {}
    cart   = body.get("cart", [])
    target = body.get("target_discount", None)

    if not cart:
        return jsonify({"error": "Cart is empty"}), 400

    catalogue = load_catalogue()
    if not catalogue:
        return jsonify({"error": "Could not load parts data"}), 500

    result       = evaluate_cart(cart, catalogue)
    suggestions  = build_suggestions(cart, catalogue, result)
    target_advice = build_target_advice(cart, catalogue, result, float(target)) if target else []

    proxy_map    = load_proxy_map()
    reco_map     = compute_reco_map(top_n=10)
    recos        = get_cart_recos(cart, reco_map, proxy_map, catalogue, top_n=5)

    return jsonify({
        "result":          result,
        "suggestions":     suggestions,
        "target_advice":   target_advice,
        "recommendations": recos,
    })

@app.route("/api/debug_sheets")
def api_debug_sheets():
    """
    Returns the row counts loaded from each sheet URL.
    Use this to verify that all rows are being fetched.
    Visit /api/debug_sheets in your browser.
    Also prints the gid values you need for Sheet2/Sheet3 —
    open your Google Sheet, click each tab, and copy the gid= from the URL.
    """
    s1 = load_raw()
    s2 = load_orders()
    s3 = _fetch(SHEET3_URL)
    return jsonify({
        "sheet1_rows": len(s1),
        "sheet2_rows": len(s2),
        "sheet3_rows": len(s3),
        "sheet1_sample": s1[:2] if s1 else [],
        "sheet2_sample": s2[:2] if s2 else [],
        "sheet3_sample": s3[:2] if s3 else [],
        "note": (
            "If sheet2 or sheet3 show 0 rows, update the gid values in app.py. "
            "Open your Google Sheet → click the tab → copy the gid= number from the browser URL."
        ),
    })


@app.route("/api/reco_matrix")
def api_reco_matrix():
    """Returns the full recommendation matrix as JSON — for debugging."""
    proxy_map = load_proxy_map()
    reco_map  = compute_reco_map(top_n=10)
    sheet_data = build_reco_sheet_data(reco_map, proxy_map)
    return jsonify({"headers": sheet_data[0], "rows": sheet_data[1:]})


@app.route("/api/combinations_report", methods=["POST"])
def api_combinations_report():
    """
    Download an Excel workbook with current cart, nudges, bought-together
    recommendations, and Sheet4 recommendation matrix.
    """
    body   = request.get_json(force=True) or {}
    cart   = body.get("cart", [])
    target = body.get("target_discount", None)

    catalogue = load_catalogue()
    if not catalogue:
        return jsonify({"error": "Could not load parts data"}), 500

    result = evaluate_cart(cart, catalogue) if cart else {
        "items": [], "total_sp": 0, "revenue": 0, "profit": 0,
        "margin": 0, "eff_discount": 0, "errors": []
    }
    suggestions = build_suggestions(cart, catalogue, result) if cart else []
    target_advice = build_target_advice(cart, catalogue, result, float(target)) if cart and target else []

    proxy_map = load_proxy_map()
    reco_map  = compute_reco_map(top_n=10)
    recos     = get_cart_recos(cart, reco_map, proxy_map, catalogue, top_n=8) if cart else []

    sheets = build_report_sheets(
        cart, target, catalogue, result, suggestions, target_advice,
        recos, reco_map, proxy_map
    )
    payload = make_xlsx(sheets)
    filename = f"parts-combinations-report-{datetime.now().strftime('%Y%m%d-%H%M')}.xlsx"

    return Response(
        payload,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

if __name__ == "__main__":
    import socket

    def find_free_port(preferred, fallbacks=(3001, 3002, 8080, 5000)):
        for port in (preferred, *fallbacks):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("0.0.0.0", port))
                    return port
                except OSError:
                    continue
        raise RuntimeError("No free port found")

    port = int(os.environ.get("PORT") or find_free_port(3000))
    if port != 3000:
        print(f"Warning: Port 3000 is in use, starting on port {port} instead.")
    print(f"Open http://localhost:{port} in your browser")
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)