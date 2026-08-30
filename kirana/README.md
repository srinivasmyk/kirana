# Kirana

Personal quick-commerce price comparison for Blinkit, Zepto, Swiggy Instamart
and BigBasket. Web app (installable to your home screen) + self-hosted backend.
An Android client is included but optional.

One search shows you the same product across all four stores, with the real
per-100ml/per-100g unit price so you can tell whether the bigger pack is
actually cheaper.

**Read in this order:**

1. **SETUP.md** — steps 1–3: backend, coordinates, store recipes. Start here.
2. **WEBAPP.md** — steps 4–6: password, HTTPS, home screen. The web app.
3. **ARCHITECTURE.md** — how it works and why it's built this way.

## Layout

```
backend/
  app/
    main.py          FastAPI: /search and /health
    matcher.py       cross-store product matching (the interesting part)
    normalize.py     title -> brand, quantity, unit
    cache.py         SQLite cache + price history
    config.py        every knob you'll want to turn
    adapters/        recipe-driven store clients
    recipes/         one JSON per store — edit these when a store breaks
  web/
    index.html       the whole web app - no build step, edit and reload
    sw.js            service worker (shell only, never caches prices)
  tools/capture.py   turns a browser request into a recipe
  tests/             run these after touching matching
android/               optional native client, same API
```

## Scope

Personal use, a handful of people, self-hosted, not published. See the end of
SETUP.md for why that boundary matters and what the alternative looks like if
you ever outgrow it.
