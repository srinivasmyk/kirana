from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .adapters import load_adapters
from .adapters.base import StoreAdapter
from .cache import geohash, get_cached, health_snapshot, init_db, put_cached, record_health
from .config import API_KEY
from .matcher import build_rows
from .models import Location, RawOffer, SearchResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("kirana")

STATE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    STATE["adapters"] = load_adapters()
    # HTTP/2 matters here — these sites serve it, and matching the browser's
    # protocol makes the request look less anomalous. But a missing 'h2' should
    # degrade to HTTP/1.1, not stop the server booting.
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    try:
        STATE["client"] = httpx.AsyncClient(follow_redirects=True, http2=True, limits=limits)
    except ImportError:
        log.warning("h2 not installed; falling back to HTTP/1.1. "
                    "Run: pip install 'httpx[http2]'")
        STATE["client"] = httpx.AsyncClient(follow_redirects=True, limits=limits)
    log.info("Kirana up with %d store(s)", len(STATE["adapters"]))
    yield
    await STATE["client"].aclose()


app = FastAPI(title="Kirana", version="1.0", lifespan=lifespan)


def _session_token() -> str:
    """
    Derived from the API key, so rotating the key logs everyone out. It's a
    constant rather than a per-session value: fine here, because the tailnet is
    the real perimeter and this is just stopping a stray browser tab. Don't
    reuse this pattern on the public internet.
    """
    return hmac.new(API_KEY.encode(), b"kirana-session-v1", hashlib.sha256).hexdigest()


def require_key(
    x_api_key: str = Header(default=""),
    kirana_session: str = Cookie(default=""),
) -> None:
    """
    Two ways in: the header (for curl and the Android app) or the session cookie
    (for the web app). The browser must never hold the API key in JavaScript —
    anything in JS is visible in DevTools — so the cookie is HttpOnly and set
    server-side at login.
    """
    if hmac.compare_digest(x_api_key, API_KEY):
        return
    if kirana_session and hmac.compare_digest(kirana_session, _session_token()):
        return
    raise HTTPException(status_code=401, detail="Sign in first")


class LoginBody(BaseModel):
    password: str


@app.post("/login")
async def login(body: LoginBody) -> JSONResponse:
    if not hmac.compare_digest(body.password, API_KEY):
        # Deliberately vague, and deliberately slow-ish, though at four users
        # brute force isn't the threat model.
        raise HTTPException(status_code=401, detail="Wrong password")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        "kirana_session", _session_token(),
        httponly=True, samesite="lax", max_age=60 * 60 * 24 * 365,
    )
    return resp


@app.post("/logout")
async def logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("kirana_session")
    return resp


@app.get("/me")
async def me(kirana_session: str = Cookie(default="")) -> dict:
    """Lets the page decide whether to show the login screen or the search box."""
    return {
        "authed": bool(kirana_session)
        and hmac.compare_digest(kirana_session, _session_token())
    }


async def _fetch_store(adapter: StoreAdapter, query: str, loc: Location,
                       geo: str) -> tuple[str, list[RawOffer], str, bool]:
    """Returns (slug, offers, error, was_cached). Never raises."""
    cached = get_cached(adapter.slug, query, geo)
    if cached is not None:
        return adapter.slug, cached, "", True
    try:
        offers = await adapter.search(STATE["client"], query, loc)
        put_cached(adapter.slug, query, geo, offers)
        record_health(adapter.slug, ok=True)
        return adapter.slug, offers, "", False
    except Exception as e:  # noqa: BLE001
        # One store failing must never take down the search. This is the whole
        # reason the fan-out is structured this way.
        log.warning("%s failed: %s", adapter.slug, e)
        record_health(adapter.slug, ok=False, error=str(e))
        return adapter.slug, [], str(e), False


@app.get("/search", response_model=SearchResponse, dependencies=[Depends(require_key)])
async def search(
    q: str = Query(..., min_length=2, max_length=64),
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    limit: int = Query(40, ge=1, le=100),
) -> SearchResponse:
    started = time.monotonic()
    loc = Location(lat=lat, lon=lon)
    geo = geohash(lat, lon)
    adapters: list[StoreAdapter] = STATE["adapters"]

    if not adapters:
        raise HTTPException(503, "No store adapters loaded. See SETUP.md step 3.")

    results = await asyncio.gather(
        *(_fetch_store(a, q, loc, geo) for a in adapters)
    )

    all_offers: list[RawOffer] = []
    degraded, cached_from = [], []
    for slug, offers, err, was_cached in results:
        all_offers.extend(offers)
        if err or not offers:
            degraded.append(slug)
        if was_cached:
            cached_from.append(slug)

    rows = build_rows(all_offers)[:limit]

    return SearchResponse(
        query=q,
        location=loc,
        products=rows,
        stores_queried=[a.slug for a in adapters],
        stores_degraded=degraded,
        cached_stores=cached_from,
        took_ms=int((time.monotonic() - started) * 1000),
    )


@app.get("/health")
async def health() -> dict:
    """Unauthenticated on purpose so you can curl it from anywhere on the tailnet."""
    return {
        "status": "ok",
        "adapters": [a.slug for a in STATE.get("adapters", [])],
        "stores": health_snapshot(),
    }


# --------------------------------------------------------------------------
# Web app
#
# Served from the same origin as the API. That is deliberate: same origin means
# no CORS configuration to get wrong, one container to deploy, and one URL to
# give your friends. Mounted last so it can never shadow /search or /login.
# --------------------------------------------------------------------------
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

if WEB_DIR.exists():
    @app.get("/sw.js", include_in_schema=False)
    async def service_worker():
        # Must be served from the root path or it can only control /web/*.
        return FileResponse(WEB_DIR / "sw.js", media_type="application/javascript")

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
else:
    log.warning("No web/ directory found; API-only mode.")
