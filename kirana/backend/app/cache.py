"""
SQLite cache keyed by (store, query, geohash). Also an append-only price
history table — it costs nothing and makes "cheapest in 30 days" possible later.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Optional

from .config import CACHE_TTL_SECONDS, DB_PATH, GEOHASH_PRECISION
from .models import RawOffer

_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat: float, lon: float, precision: int = GEOHASH_PRECISION) -> str:
    """Standard geohash. Precision 7 is roughly 150 m — one dark store's area."""
    lat_lo, lat_hi, lon_lo, lon_hi = -90.0, 90.0, -180.0, 180.0
    out, bit, ch, even = [], 0, 0, True
    while len(out) < precision:
        if even:
            mid = (lon_lo + lon_hi) / 2
            if lon > mid:
                ch = (ch << 1) | 1
                lon_lo = mid
            else:
                ch <<= 1
                lon_hi = mid
        else:
            mid = (lat_lo + lat_hi) / 2
            if lat > mid:
                ch = (ch << 1) | 1
                lat_lo = mid
            else:
                ch <<= 1
                lat_hi = mid
        even = not even
        bit += 1
        if bit == 5:
            out.append(_B32[ch])
            bit, ch = 0, 0
    return "".join(out)


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS offer_cache (
                store TEXT, query TEXT, geo TEXT,
                payload TEXT NOT NULL, fetched_at REAL NOT NULL,
                PRIMARY KEY (store, query, geo)
            );
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store TEXT, title TEXT, geo TEXT,
                price REAL, mrp REAL, in_stock INTEGER, seen_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_hist
                ON price_history (store, title, seen_at);
            CREATE TABLE IF NOT EXISTS store_health (
                store TEXT PRIMARY KEY, last_ok REAL, last_error TEXT,
                consecutive_failures INTEGER DEFAULT 0
            );
            """
        )


def get_cached(store: str, query: str, geo: str) -> Optional[list[RawOffer]]:
    with _conn() as c:
        row = c.execute(
            "SELECT payload, fetched_at FROM offer_cache "
            "WHERE store=? AND query=? AND geo=?",
            (store, query.lower().strip(), geo),
        ).fetchone()
    if not row:
        return None
    payload, fetched_at = row
    if time.time() - fetched_at > CACHE_TTL_SECONDS:
        return None
    return [RawOffer(**d) for d in json.loads(payload)]


def put_cached(store: str, query: str, geo: str, offers: list[RawOffer]) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO offer_cache VALUES (?,?,?,?,?)",
            (store, query.lower().strip(), geo,
             json.dumps([o.model_dump() for o in offers]), time.time()),
        )
        now = time.time()
        c.executemany(
            "INSERT INTO price_history (store,title,geo,price,mrp,in_stock,seen_at) "
            "VALUES (?,?,?,?,?,?,?)",
            [(o.store, o.title, geo, o.price, o.mrp, int(o.in_stock), now)
             for o in offers],
        )


def record_health(store: str, ok: bool, error: str = "") -> None:
    with _conn() as c:
        if ok:
            c.execute(
                "INSERT INTO store_health (store,last_ok,last_error,consecutive_failures) "
                "VALUES (?,?,'',0) ON CONFLICT(store) DO UPDATE SET "
                "last_ok=excluded.last_ok, last_error='', consecutive_failures=0",
                (store, time.time()),
            )
        else:
            c.execute(
                "INSERT INTO store_health (store,last_ok,last_error,consecutive_failures) "
                "VALUES (?,NULL,?,1) ON CONFLICT(store) DO UPDATE SET "
                "last_error=excluded.last_error, "
                "consecutive_failures=store_health.consecutive_failures+1",
                (store, error[:400]),
            )


def health_snapshot() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT store,last_ok,last_error,consecutive_failures FROM store_health"
        ).fetchall()
    return [
        {"store": r[0], "last_ok": r[1], "last_error": r[2], "consecutive_failures": r[3]}
        for r in rows
    ]
