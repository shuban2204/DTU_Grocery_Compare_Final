# DTU Grocery Compare — Design Note

## Architecture & key decisions

The app follows a provider-based pipeline:

**UI → FastAPI → SearchService → Provider Adapters → Relevance Filter → Normalizer → Matcher → Pricing Engine**

The delivery location is fixed to **Delhi Technological University**, so it is resolved once per provider session rather than on every search.

For **Blinkit**, the prototype uses Playwright against the visible desktop website. I chose browser automation instead of direct HTTP parsing because the catalog is dynamically rendered and location-dependent. I deliberately avoided undocumented/private API calls because they would require reverse-engineering and make the implementation more brittle.

For **Instamart**, browser automation was initially attempted using both Playwright Chromium and installed Chrome, but automated sessions were consistently rejected with `Request Blocked`. Rather than attempting anti-bot circumvention, the final implementation uses a **third-party structured quick-commerce data API** for live Instamart catalog results at DTU coordinates. The provider returns product name, brand, size, price, MRP, availability, deeplink and bundle variants. It is isolated behind the same provider interface as Blinkit.

If the external Instamart API is unavailable, times out, or is not configured, the app falls back to **timestamped manually captured Instamart snapshots**. The UI explicitly distinguishes the source:

**Blinkit: LIVE**  
**Instamart: LIVE** or **Instamart: SNAPSHOT**

This provider abstraction is intentional: data acquisition can later be replaced with authorized merchant APIs without changing matching, pricing or frontend logic.

A short in-memory cache reduces repeated provider requests while retaining freshness information and manual refresh support.

## Deciding whether two listings are the same product

Direct title matching is unreliable because Blinkit and Instamart often describe the same SKU differently. Listings are therefore normalized into structured attributes including **brand, core product, flavour/variant, individual quantity, unit, pack count and total quantity**.

Units and pack expressions are normalized before comparison, for example:

`0.5 kg → 500 g`  
`4 × 70 g → item size 70 g, pack count 4`

The matcher is deliberately **precision-first**.

An **Exact Match** requires strong product-name similarity, compatible known brands, known and equal item sizes, equal pack structure, and no explicit variant conflict.

Example:

`Lay's India's Magic Masala 58 g`  
↔  
`Lay's Magic Masala Potato Chips 58 g`

A **Comparable Product** is used when the products are clearly from the same family but differ in size or packaging.

Example:

`Lay's Classic Salted 51 g`  
↔  
`Lay's Classic Salted 58 g`

These should not be presented as the same SKU, but the app can still compare their **₹/100 g** price.

Similarly, `4 × 70 g` is not automatically treated as the same SKU as one `280 g` family pack, even though the total weight is equal.

Explicit variant conflicts are hard boundaries. Examples such as **salted vs unsalted**, **regular Coca-Cola vs Coca-Cola Zero**, and **Magic Masala vs Cream & Onion** cannot become exact matches.

Missing information is treated differently from conflicting information. For example, `Amul Butter` vs `Amul Salted Butter` is ambiguous rather than automatically rejected.

When a promising Blinkit match is missing important metadata such as pack size, the app can selectively open the product-detail page and extract semantic fields such as `Pack Size`, `Weight`, `Volume` or `Flavour`, then recompute the match.

### Where the logic breaks

Product identity is still heuristic. Platforms may omit flavour or size information, use inconsistent titles, represent multipacks differently, or stock different generations of a product because of shrinkflation.

Because a false exact match is more misleading than a missing match, the system intentionally prefers **Comparable** or **No Match** when confidence is insufficient.

## Pricing

The cheapest platform is calculated for the **user-selected quantity**, not just from the single-unit sticker price.

The Instamart data source can expose bundle SKUs such as:

`Coca-Cola 750 ml → ₹38`  
`750 ml × 2 → ₹65`

These are consolidated into one base product plus quantity offers, allowing the pricing engine to select the cheapest valid combination.

For example, a ₹20 product with a visible `4 for ₹75` offer costs ₹75 at quantity four rather than ₹80. This means the cheapest platform can change as quantity changes.

The prototype intentionally excludes checkout-only coupons, memberships, bank offers, delivery/handling fees and personalized promotions because those depend on the user and the final cart rather than the product listing itself.

## Scaling to more locations or users

For multiple locations, location would become part of each provider request and cache key, partitioned by pincode/store region instead of being fixed to DTU.

For higher traffic, I would separate provider workers from the API layer, use distributed caching and request queues, apply provider-specific rate limits, and persist normalized catalog observations so repeated searches do not repeatedly hit upstream sources.

Most importantly, a production system should replace browser extraction and third-party aggregation with **authorized merchant feeds or official partner APIs**. Because all acquisition logic is isolated behind provider adapters, that migration would not require rewriting the matcher, pricing engine or UI.

The final implementation is covered by **49 deterministic regression tests**, and the Blinkit live path was manually verified at DTU across Maggi, Amul Butter, Coca Cola, Lay's and Milk.