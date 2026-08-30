# Kirana — Design & Architecture

A personal quick-commerce price comparison app for Blinkit, Zepto, Swiggy Instamart
and BigBasket. Android client, self-hosted backend, single household scale.

---

## 1. The shape of the problem

The Android app is the easy part. Three things make this genuinely hard, and the
architecture is built around them.

**Prices are per-store, not per-brand.** Quick commerce serves you from the dark
store nearest your pin. Blinkit's price for Amul Taaza in Kondapur is not the price
in Gachibowli, and availability differs even more than price. Every request must
carry a latitude/longitude, and every cached price must be keyed by location.

**Nobody names a product the same way.** The same carton is:

| Store | Title |
|---|---|
| Blinkit | `Amul Taaza Toned Fresh Milk` / 500 ml |
| Zepto | `Amul Taaza Homogenised Toned Milk 500ml` |
| Instamart | `Amul Taaza Toned Milk Pouch` |
| BigBasket | `Amul Taaza Fresh Toned Milk, 500 ml Pouch` |

Displaying four unlinked lists is not a comparison app. The matching engine that
collapses these into one row is the actual product.

**The endpoints will break.** These are private web APIs. They change without
notice, several times a year. If fixing a break requires you to write Python, the
app dies the first time it breaks — you told me you're not a developer. So store
access is defined in **JSON recipe files**, not code, and there's a tool that
generates a recipe from a request you copy out of Chrome DevTools.

---

## 2. System diagram

```
┌─────────────────────┐
│  Android app        │  Kotlin + Jetpack Compose
│  - search box       │  Sends: query + lat/lon
│  - GPS location     │  Renders: matched product rows
│  - results list     │
└──────────┬──────────┘
           │  HTTPS (Tailscale) — one API, one key
           ▼
┌─────────────────────────────────────────────────┐
│  Backend  (Python 3.11, FastAPI, async)          │
│                                                  │
│  /search ──► Cache ──hit──► response             │
│                │ miss                            │
│                ▼                                 │
│         ┌──────────────┐                         │
│         │ Fan-out      │  asyncio.gather         │
│         │ 4 adapters   │  in parallel            │
│         └──────┬───────┘                         │
│                ▼                                 │
│         Normalizer  (brand, quantity, unit)      │
│                ▼                                 │
│         Matcher     (cluster into products)      │
│                ▼                                 │
│         Unit-price calc (₹ per 100ml / 100g)     │
│                ▼                                 │
│         SQLite cache + price history             │
└──────────┬───────────────────────────────────────┘
           │ rate-limited, 1 req/sec/store
           ▼
   Blinkit   Zepto   Instamart   BigBasket
```

### Why a backend at all?

You could put the fetching in the app. Don't:

- Every user's home IP gets seen by four retailers. One backend IP is one
  fingerprint instead of five, and it's *yours*.
- When an endpoint breaks, you edit a JSON file on the server. The alternative is
  rebuilding and resideloading an APK on four phones.
- Caching only works if it's shared. Four people searching "milk" should cost one
  fetch, not four.
- Secrets (recipes, tokens) stay off devices you don't control.

---

## 3. Component design

### 3.1 Adapters (`app/adapters/`)

Every store implements one interface:

```python
class StoreAdapter:
    slug: str
    display_name: str
    async def search(self, query: str, loc: Location) -> list[RawOffer]
```

`RecipeAdapter` is a generic implementation driven by a JSON file — it handles the
HTTP call, the location injection, the JSON extraction, retries and rate limiting.
Adding a fifth store (DMart Ready, JioMart) means writing a JSON file, not Python.
A store with genuinely weird behaviour can still subclass `StoreAdapter` directly.

**Failure is expected and isolated.** If Zepto times out or returns garbage, the
other three still render and the response carries a `degraded` list. A comparison
app that shows nothing because one of four sources hiccupped is useless.

### 3.2 Normalizer (`app/normalize.py`)

Turns a messy title into structured facts:

```
"Amul Taaza Fresh Toned Milk, 500 ml Pouch"
  → brand="amul"
    quantity=500.0, unit="ml", base_qty=500.0 (ml)
    tokens={taaza, fresh, toned, milk}
```

Handles the formats these stores actually use: `500ml`, `500 ML`, `1 L`, `1kg`,
`250 gm`, `6 x 100 g` (→ 600 g), `12 pcs`, `1 dozen`, `500g + 100g free`.

### 3.3 Matcher (`app/matcher.py`)

The core algorithm. Two offers are the same product only if **all** hold:

1. **Same brand**, after alias normalization (`amul` == `amul india`).
2. **Same base quantity**, within 2%. This is a hard gate, not a score input —
   500 ml and 1 L are different products even though the titles are 90% identical.
   Getting this wrong is the classic failure mode of naive price comparison.
3. **Descriptor similarity ≥ 0.72**, using token-set ratio on the remaining words.
   This lets `toned milk pouch` match `homogenised toned milk`, while keeping
   `toned` apart from `full cream`.

Plus a **variant blocklist**: certain tokens (`toned`, `full cream`, `double toned`,
`slim`, `zero`, `sugar free`, `organic`, `spicy`, `unsalted`) must match exactly if
present on either side. Sugar-free and regular are never the same product, however
similar their names.

Offers that match nothing appear as single-store rows — that's real signal, because
"only Zepto has it" is worth knowing.

### 3.4 Unit price

The feature that makes the app actually useful. A 1 L pack at ₹66 beats two 500 ml
at ₹36 each, and no store will tell you that. Every offer gets `price_per_100`
in its base unit, and rows sort by it when you ask them to.

### 3.5 Cache (`app/cache.py`)

SQLite, two tables:

- `offer_cache` — keyed by `(store, query, geohash7)`, TTL 10 minutes. Geohash-7 is
  ~150 m, roughly one dark-store catchment.
- `price_history` — append-only, every offer ever seen. Costs nothing and gives you
  "cheapest it's been in 30 days" later.

TTL is deliberately generous. Quick-commerce prices move on promo cycles, not by the
minute, and the cache is what keeps your footprint small.

---

## 4. Data flow, one request

1. App sends `GET /search?q=milk&lat=17.44&lon=78.38`.
2. Backend geohashes the location to 7 chars.
3. For each of 4 stores: cache lookup. Hits return instantly.
4. Misses go out in parallel, each behind a per-store 1 req/sec semaphore.
5. Raw results → normalize → match → unit price.
6. Response: product rows, each with 1–4 store offers, cheapest first.
7. Everything written to cache and history.

Typical cold search: ~1.5 s. Warm: ~30 ms.

---

## 5. Deliberate non-goals

- **No accounts, no cart, no checkout.** The app deep-links you into the real store
  app to buy. Handling anyone's payment or login is a liability with no upside.
- **No Play Store.** Sideload the APK. Publishing turns a personal tool into a
  product that the retailers' legal teams can find.
- **No public internet exposure.** Tailscale, not a public domain.
- **No anti-bot evasion.** If a store blocks the backend, that store gets disabled.
  Escalating is where a gray area stops being gray.
- **No image hosting.** Hotlink thumbnails or show none.

---

## 6. Tech choices, briefly

| Layer | Choice | Why |
|---|---|---|
| Backend | Python + FastAPI | Async fan-out is native; you'll edit this occasionally |
| HTTP | httpx | Async, HTTP/2, sane timeouts |
| Fuzzy match | rapidfuzz | C-fast, no ML dependency to install |
| Storage | SQLite | Four users. Postgres would be costume jewellery |
| Client | Kotlin + Compose | Current-standard Android; least boilerplate |
| Client HTTP | Retrofit + Moshi | Boring, documented, works |
| Deploy | Docker Compose | One command, runs on a laptop or a ₹350/mo VPS |
| Access | Tailscale | Private network, no ports open, no auth to get wrong |

---

## 7. What will go wrong, and the plan

| Failure | Detection | Response |
|---|---|---|
| Endpoint shape changes | Adapter returns 0 results, health check flags it | Re-capture with `capture.py`, edit JSON recipe |
| Store starts blocking | 403s in logs | Disable that store in config. Do not escalate |
| Bad matches (wrong items grouped) | You see it | Add token to variant blocklist, or raise threshold |
| Missed matches (dupes shown) | You see it | Add brand alias, or lower threshold |
| Cache serving stale promos | Prices look wrong | Lower TTL; it's one config value |

The matcher thresholds are in `config.py` precisely because you *will* tune them
against real Hyderabad results. Expect to spend an evening on that.
