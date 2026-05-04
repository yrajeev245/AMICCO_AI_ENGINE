# Parts Discount Engine - Product & Technical Documentation

## 1. What This Project Is

Parts Discount Engine is a garage pricing and deal optimisation web app.

The goal is simple:

- A sales/user person builds a cart of parts for a garage.
- The app calculates the best allowed discount for every line item.
- The app shows the final cart value, effective discount, and garage payable value.
- The app gives nudges to improve the deal:
  - switch to a better brand variant
  - increase quantity to unlock quantity bonus
  - add parts that improve overall discount
  - add cart-bonus eligible parts and reach a cart threshold
  - add frequently bought together parts

The product is designed for garages and sales teams, so the UI avoids margin/profit language and focuses on price, discount, value, and easy add/switch actions.

## 2. Main User Flow

1. User opens the app.
2. App loads the parts catalogue from Google Sheets.
3. User selects part, brand, and quantity in Build Cart.
4. User optionally enters target overall discount.
5. User clicks Get Best Deal.
6. Backend calculates:
   - price per item
   - discount per item
   - final price per item
   - total cart value
   - value after discount
   - effective overall discount
7. UI shows:
   - Deal Summary
   - Line Items
   - Smart Recommendations
   - To Reach Target Discount
   - Bought Together

## 3. Files In The Project

### `index.html`

This is the page structure.

It defines:

- Header: Parts Discount Engine title.
- Left panel:
  - Build Cart
  - Garage target discount input
  - Bought Together recommendations
- Right panel:
  - Deal Summary
  - Line Items
  - Smart Recommendations
  - To Reach Target Discount
  - Empty state before calculation

It loads:

- `style.css`
- `script.js`

### `style.css`

This controls all visual design:

- layout
- cards
- buttons
- cart rows
- recommendation rows
- badges
- discount pills
- bought-together rows
- target advice cards

The design uses muted garage-friendly colours, compact cards, and direct action buttons.

### `script.js`

This is frontend logic.

It:

- loads parts from `/api/data`
- populates dropdowns
- reads cart rows
- sends cart to `/api/deal`
- renders results
- handles add buttons
- handles switch brand buttons
- tracks whether recommendation parts are already in cart
- refreshes `Added` state when parts are removed

### `app.py`

This is the backend engine.

It:

- loads data from Google Sheets
- calculates pricing and discounts
- builds all suggestions
- calculates bought-together recommendations
- exposes API routes for the frontend
- can export recommendation/report data

### `tempCodeRunnerFile.py`

This appears to be a temporary file from a code runner/editor. It is not part of the main app logic.

## 4. Data Source: Google Sheets

The app uses one Google Sheet with multiple tabs.

### Sheet1 - Catalogue

This is the master parts catalogue.

Important columns:

- `Part`: part name
- `Brand`: brand/vendor/variant
- `SellingPrice`: price shown to garage before discount
- `BuyingPrice`: internal purchase/cost price
- `MinDiscount`: base discount always considered
- `MinMarginPercent`: minimum margin guard
- `Stock`: used to hide explicit zero-stock rows
- `QtyThreshold`: quantity needed for quantity bonus
- `BonusDiscount_QtyThreshold`: extra discount when quantity threshold is met
- `MinCartValue`: cart value needed for cart-value bonus
- `BonusDiscount_MinCartValue`: extra discount when cart value threshold is met

### Sheet2 - Order History

Used for Bought Together recommendations.

Important columns:

- `Order Reference`
- `Quantity`
- `Part`

The app groups rows by order reference to understand which parts were bought together in the same order.

### Sheet3 - Part Proxy Map

Used to group similar or equivalent parts.

Important columns:

- `Part`
- `PartProxy`

Example idea:

- Different exact part names may map to the same logical family.
- Recommendations are calculated at the proxy/family level.

### Sheet4 - Recommendation Matrix

The backend has logic to build a flat recommendation matrix for review/export.

It contains rows like:

- recommendation category
- product A
- product B
- co-orders
- Jaccard
- Lift
- score
- strength

## 5. Discount Logic In Simple Terms

For each cart line, the backend calculates discount in layers.

### Layer 1: Base Discount

`MinDiscount` is the starting discount.

Example:

If Coolant Green has `MinDiscount = 5%`, the app starts with 5%.

### Layer 2: Quantity Bonus

If quantity is greater than or equal to `QtyThreshold`, the app adds `BonusDiscount_QtyThreshold`.

Example:

- QtyThreshold = 6
- BonusDiscount_QtyThreshold = 3%
- User buys 6 or more
- App adds 3% extra discount

### Layer 3: Cart Value Bonus

If total cart value reaches `MinCartValue`, the app adds `BonusDiscount_MinCartValue` to eligible parts.

Important product rule:

The user can add any parts to reach the cart threshold. The extra discount applies only to eligible parts.

Example:

- Coolant Green has `+10%` at cart value `₹10,000`
- User adds Coolant Green
- User adds any other parts to make cart reach ₹10,000
- Coolant Green receives the extra 10% cart bonus

### Layer 4: Margin Guard

The app checks margin after applying discounts.

If margin goes below `MinMarginPercent`, the backend reduces discount by 0.5% steps until margin is safe.

This means:

- the app tries to give the best discount
- but it will not break minimum margin rules

## 6. Deal Summary

The app shows three top numbers:

### Total Cart Value

Sum of selling price x quantity before discount.

### Discount Given

Effective overall discount on the full cart.

Formula concept:

`(Full cart value - final cart value) / full cart value`

### Value After Discount

Final amount garage pays after all discounts.

## 7. Line Items

Each line item shows:

- Part
- Brand
- Quantity
- Unit price
- Discount
- Final price
- Cart bonus badge if active

Margin is intentionally not shown because this is garage-facing.

## 8. Smart Recommendations

Smart Recommendations is mainly for helping the user improve the deal.

Current behaviour:

### Brand Switch Recommendations

The app checks if the same part has another in-stock brand with a higher base discount.

Example:

`Switch Coolant Green from Bosch to Golden Star for higher base discount: 25% vs 5%`

The UI gives a direct `Switch to Golden Star` button.

Important detail:

Same-brand switch recommendations are removed because the cart identifies variants by `part + brand`. If two rows have the same brand but different price, switching safely is ambiguous.

### All Cart-Bonus Eligible Parts

The app always shows catalogue parts that can unlock extra cart-value discounts.

Example:

`Coolant Green (Golden Star) - ₹70`

It also shows:

- max possible discount badge
- how much more cart value is needed
- quantity input
- `+ Add` button

This helps the user discover parts that become more attractive once the cart reaches a threshold.

## 9. To Reach Target Discount

This section appears when the user enters a target overall discount.

It explains:

- current effective discount
- gap to target
- actions that can help reach target

### Quantity Nudges

If a cart item has not reached quantity threshold, the app shows:

`Increase qty of X to 6+ to unlock +3% bonus discount`

### Brand Switch Nudges

If a better in-stock brand exists, the app shows a switch recommendation.

Now target-section brand switches also use the same switch logic as Smart Recommendations.

### Add-Part Nudges

The backend simulates adding different parts and returns the top 3 different parts that improve overall discount.

Each add suggestion includes:

- part
- brand
- price
- projected overall discount
- add button
- quantity input

## 10. Bought Together Recommendations

Bought Together uses order history from Sheet2.

The idea:

If garages frequently buy Part B when they buy Part A, the app recommends Part B when Part A is in cart.

This section is placed under Build Cart because it is an important sales action area.

### How It Works

1. Backend loads Sheet2 order history.
2. It groups parts by `Order Reference`.
3. Each order becomes a basket of parts.
4. The app maps parts to `PartProxy` using Sheet3.
5. It calculates how often proxy pairs appear together.
6. It ranks pairs using:
   - co-order count
   - Jaccard similarity
   - Lift
   - composite score
7. Frontend shows recommended part families with add buttons.

### Jaccard

Jaccard measures overlap.

Plain English:

Of all orders that had either A or B, how many had both?

Higher Jaccard means the pair commonly appears together.

### Lift

Lift measures whether two parts are bought together more than random chance.

Plain English:

If Part A and Part B appear together much more often than expected, lift is high.

### Composite Score

The app blends Jaccard and Lift:

- 60% Jaccard
- 40% Lift

This balances:

- common pairs
- unusually strong pair relationships

## 11. Add Buttons And Quantity Controls

Wherever the app recommends adding a part, it gives:

- small quantity input
- `+ Add` button

This is used in:

- Bought Together
- cart-bonus eligible parts
- target discount add suggestions

If the same part and brand already exist in cart:

- app increases quantity instead of adding duplicate cart rows

If a user removes a part:

- the app refreshes button state
- `✓ Added` goes back to `+ Add`

## 12. Brand Switching

Brand switch buttons work by:

1. finding the matching cart row by part and current brand
2. repopulating available brand dropdown options
3. selecting the target brand
4. recalculating the cart

The backend now sends structured fields:

- `part`
- `from_brand`
- `to_brand`

This avoids fragile parsing from text.

## 13. Frontend Function Map

### `stockOk(d)`

Checks whether a catalogue row should be shown.

Blank stock is treated as available. Explicit stock `0` is hidden.

### `loadData()`

Calls `/api/data` and loads catalogue rows into frontend memory.

### `getMaxDiscount(part, brand)`

Calculates maximum possible discount from catalogue values:

- base discount
- quantity bonus
- cart value bonus

Used for badges like `Max 38.0% off`.

### `addItem(prefillPart, prefillBrand)`

Adds a new cart row.

Can prefill part and brand when user clicks a recommendation add button.

### `populateParts(row, prefillPart, prefillBrand)`

Fills the part dropdown with in-stock part names.

### `updateBrands(row, prefillBrand)`

Fills the brand dropdown based on selected part.

Brand dropdown shows price, for example:

`Golden Star - ₹70`

### `getCart()`

Reads all cart rows and returns clean cart data.

It merges duplicate `part + brand` rows by summing quantity.

### `calculateCart()`

Sends cart and target discount to `/api/deal`.

Then renders the returned result.

### `renderResult(api, target)`

Main rendering coordinator.

Calls:

- `renderSummary`
- `renderLineItems`
- `renderSuggestions`
- `renderTargetAdvice`
- `renderRecommendations`

### `renderSummary(r)`

Shows the three summary cards.

### `renderLineItems(r)`

Shows item-level details.

### `renderSuggestions(suggs, result)`

Shows:

- brand switch recommendations
- all cart-bonus eligible catalogue parts

### `reapplyAddedState(container)`

Makes sure buttons show `✓ Added` only if the part is actually in the cart.

### `syncAddedStateFromCart()`

Rebuilds added-state from current cart rows.

This fixes stale added buttons after removing parts.

### `refreshAddedButtons()`

Resets buttons and reapplies correct added state.

### `removeCartRow(btn)`

Removes a cart row and refreshes added state.

### `getBonusCatalogueParts()`

Finds all catalogue parts with cart-value bonus.

### `renderBonusCatalogueSection(parts, cartTotal)`

Renders the `All Cart-Bonus Eligible Parts` section.

### `renderSuggestionCard(s)`

Renders a brand-switch card.

### `renderActionRow(a)`

Renders addable recommendation rows with qty input and add button.

### `renderTargetCard(s)`

Renders each target-discount advice card.

Brand cards use switch button; add cards use add rows.

### `renderTargetAdvice(advice, target)`

Shows or hides the target discount advice section.

### `renderRecommendations(recos)`

Renders Bought Together cards and addable variant rows.

### `switchBrandInCart(part, fromBrand, toBrand, btn)`

Switches a cart row from one brand to another.

### `flashRow(row)`

Briefly highlights a cart row after add/switch.

### `addOrIncrementCart(part, brand, addQty, btn)`

Adds a recommended part to cart.

If already present, increases quantity.

### `markBtnAdded(btn)`

Turns an add button into `✓ Added`.

### `addToCartFromReco(...)`

Used by Bought Together add buttons.

### `addToCartFromSuggestion(...)`

Used by Smart Recommendation and Target Advice add buttons.

### `escAttr(s)`

Escapes text safely for HTML data attributes.

## 14. Backend Function Map

### `_csv_url(gid)`

Builds Google Sheet CSV export URL.

### `_fetch(url)`

Downloads CSV data from Google Sheets and returns rows as dictionaries.

Uses cache for speed.

### `_f(val)`

Safely converts values to numbers.

Handles strings and percent signs.

### `_stock_ok_row(row)`

Checks if backend row is in stock.

### `_normalise(row)`

Converts sheet column names into code-friendly names.

Example:

`SellingPrice` becomes `selling_price`.

### `load_catalogue()`

Loads Sheet1 catalogue in normalised format.

### `load_raw()`

Loads Sheet1 raw data for frontend dropdowns.

### `load_orders()`

Loads Sheet2 order history.

### `load_proxy_map()`

Loads Sheet3 part-to-proxy mapping.

### `find_row(catalogue, part, brand)`

Finds the catalogue row for a cart item.

### `proxy_label_parts(proxy)`

Handles proxy labels like:

`Part Name[Brand Name]`

### `compute_pricing(row, qty, cart_total_sp)`

Core pricing engine for one line item.

Applies:

- base discount
- quantity bonus
- cart value bonus
- margin guard

### `evaluate_cart(cart, catalogue)`

Calculates the whole cart.

It does two passes:

1. calculate full cart selling price
2. price every item using that cart value

### `build_suggestions(cart, catalogue, result)`

Builds Smart Recommendations:

- active cart bonus
- unlock cart bonus
- brand switch
- catalogue cart-bonus opportunities

### `cart_bonus_catalogue_opportunities(...)`

Finds catalogue parts that have cart-value bonus configured.

### `cart_bonus_add_candidates(...)`

Suggests practical add-on parts to reach cart threshold.

### `top_discount_lift_additions(...)`

Simulates adding each possible part and finds the top 3 different parts that best improve overall discount.

### `build_target_advice(...)`

Builds advice to reach the user-entered target discount.

Includes:

- current gap
- quantity nudges
- brand switch
- add-part suggestions

### `compute_reco_map(top_n)`

Builds bought-together recommendation map from order history.

### `get_cart_recos(...)`

Takes current cart and returns recommended parts to show in Bought Together.

### `build_reco_sheet_data(...)`

Builds Sheet4-style recommendation matrix rows.

### `make_xlsx(...)`

Creates a lightweight Excel workbook from row data.

### `build_report_sheets(...)`

Builds workbook sheets for export/reporting.

## 15. API Routes

### `/`

Serves `index.html`.

### `/<path:filename>`

Serves static files like:

- `style.css`
- `script.js`

### `/api/data`

Returns raw catalogue rows for frontend dropdowns.

### `/api/deal`

Main API.

Input:

```json
{
  "cart": [
    { "part": "Coolant Green", "brand": "Golden Star", "qty": 1 }
  ],
  "target_discount": 10
}
```

Output:

- `result`
- `suggestions`
- `target_advice`
- `recommendations`

### `/api/debug_sheets`

Debug route to inspect sheet loading.

### `/api/reco_matrix`

Returns recommendation matrix as JSON.

### `/api/combinations_report`

Returns Excel report data.

This is backend-supported, but the header download button was removed from the UI.

## 16. Important Product Decisions We Made

### Margin is hidden from garage-facing UI

Because garage users should see prices and discounts, not internal profitability.

### Bought Together moved below Build Cart

Because it is a direct cart-building action.

### Quantity nudge only in target section

To avoid repeating the same qty advice in multiple sections.

### Cart-value bonus visible even before part is added

So users know which parts can unlock extra discount after cart reaches a threshold.

### Add buttons always have quantity input

Users can add 2, 5, or more directly instead of always adding 1.

### Same-brand switch suggestions removed

Because multiple rows with same part and brand cannot be safely switched using only part + brand.

## 17. Current Limitations

### Same brand with different prices is ambiguous

The app identifies variants by:

`Part + Brand`

If the same part and same brand appear multiple times with different selling prices, the app cannot uniquely identify which row to use.

Best future improvement:

Add a unique SKU or VariantID column in Sheet1.

### Google Sheet GIDs are hardcoded

The backend uses specific sheet GIDs for CSV export.

If Sheet2 or Sheet3 tab IDs change, the backend URLs must be updated.

### Recommendation quality depends on Sheet2 history

Bought Together is only as good as order-history cleanliness.

If historical order data has inconsistent part names, Sheet3 proxy mapping becomes very important.

## 18. Recommended Next Improvements

### Add SKU / VariantID

This is the most important technical improvement.

It will solve:

- same-brand duplicate ambiguity
- brand switching precision
- exact add-to-cart variant tracking

### Add admin/debug view for discount rules

Product team could quickly see:

- which parts have qty bonus
- which parts have cart bonus
- which parts have high base discount

### Add reason labels to recommendations

Example:

- `High discount lift`
- `Frequently bought together`
- `Cart value bonus`
- `Quantity bonus`

### Add sorting controls

Useful sorts:

- highest discount
- lowest price
- most frequently bought
- highest lift
- in-stock first

### Add analytics tracking

Track:

- recommendation shown
- recommendation added
- brand switch clicked
- target achieved

This will help measure which nudges actually work.

## 19. How To Run The App

From the app folder:

```bash
/opt/anaconda3/bin/python -B app.py
```

Then open:

```text
http://127.0.0.1:3000
```

## 20. One-Line Summary

This app is a rules-plus-data recommendation engine that helps sales users build better garage carts by applying safe discounts, surfacing discount unlocks, recommending commonly bought parts, and guiding users toward target discounts.
