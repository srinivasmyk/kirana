"""
Store adapters.

RecipeAdapter is deliberately generic: a store is described by a JSON file, not
by Python. When Blinkit changes its response shape (it will), you re-capture the
request with tools/capture.py and edit one JSON file. No code, no redeploy of
anything but a restart.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

import httpx

from ..config import (
    MAX_RETRIES,
    REQUESTS_PER_SECOND_PER_STORE,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
)
from ..models import Location, RawOffer

log = logging.getLogger("kirana.adapter")


class RateLimiter:
    """One in flight per store, minimum gap between calls. Non-negotiable."""

    def __init__(self, rps: float):
        self._min_gap = 1.0 / rps if rps > 0 else 0.0
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            gap = time.monotonic() - self._last
            if gap < self._min_gap:
                await asyncio.sleep(self._min_gap - gap)
            self._last = time.monotonic()


class StoreAdapter(ABC):
    slug: str
    display_name: str

    @abstractmethod
    async def search(self, client: httpx.AsyncClient, query: str,
                     loc: Location) -> list[RawOffer]:
        ...


# --------------------------------------------------------------------------
# value extraction helpers
# --------------------------------------------------------------------------

_INDEX_RE = re.compile(r"^(.*?)\[(\d+)\]$")


def dig(obj: Any, path: str) -> Any:
    """
    Resolve a dotted path with optional list indices.
        "data.name.text"      -> obj["data"]["name"]["text"]
        "items[0].price"      -> obj["items"][0]["price"]
    Returns None instead of raising, because store responses are inconsistent
    and a missing field should degrade one offer, not the whole search.
    """
    if not path:
        return None
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        m = _INDEX_RE.match(part)
        idx = None
        if m:
            part, idx = m.group(1), int(m.group(2))
        if part:
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        if idx is not None:
            if isinstance(cur, list) and len(cur) > idx:
                cur = cur[idx]
            else:
                return None
    return cur


def dig_any(obj: Any, paths: Any) -> Any:
    """A field can list several candidate paths; first non-empty wins."""
    if paths is None:
        return None
    if isinstance(paths, str):
        paths = [paths]
    for p in paths:
        v = dig(obj, p)
        if v not in (None, "", [], {}):
            return v
    return None


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def to_price(value: Any) -> Optional[float]:
    """'₹1,234.50' / '1234' / 123450 (paise) -> float rupees."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUM_RE.search(str(value).replace(",", ""))
    return float(m.group()) if m else None


def collect_items(payload: Any, spec: Any) -> list[Any]:
    """
    items_path may be a single dotted path or a list of them. Stores often
    return results split across several sections; listing multiple paths
    merges them.
    """
    if isinstance(spec, str):
        spec = [spec]
    out: list[Any] = []
    for path in spec or []:
        node = dig(payload, path)
        if isinstance(node, list):
            out.extend(node)
        elif node is not None:
            out.append(node)
    return out


# --------------------------------------------------------------------------
# recipe adapter
# --------------------------------------------------------------------------

class RecipeAdapter(StoreAdapter):
    def __init__(self, recipe: dict):
        self.recipe = recipe
        self.slug = recipe["slug"]
        self.display_name = recipe.get("display_name", self.slug.title())
        self._limiter = RateLimiter(REQUESTS_PER_SECOND_PER_STORE)

    @classmethod
    def from_file(cls, path: Path) -> "RecipeAdapter":
        return cls(json.loads(path.read_text()))

    # -- request building --------------------------------------------------

    def _fill(self, template: Any, ctx: dict) -> Any:
        if isinstance(template, str):
            out = template
            for k, v in ctx.items():
                out = out.replace("{" + k + "}", str(v))
            return out
        if isinstance(template, dict):
            return {k: self._fill(v, ctx) for k, v in template.items()}
        if isinstance(template, list):
            return [self._fill(v, ctx) for v in template]
        return template

    async def search(self, client: httpx.AsyncClient, query: str,
                     loc: Location) -> list[RawOffer]:
        req = self.recipe["request"]
        ctx = {
            "query": httpx.URL(path="/").copy_with(params={"q": query}).params.get("q"),
            "query_raw": query,
            "lat": f"{loc.lat:.6f}",
            "lon": f"{loc.lon:.6f}",
        }

        url = self._fill(req["url"], ctx)
        headers = {"User-Agent": USER_AGENT, **self._fill(req.get("headers", {}), ctx)}
        cookies = self._fill(req.get("cookies", {}), ctx)
        params = self._fill(req.get("params", {}), ctx)
        body = self._fill(req.get("json_body"), ctx)
        method = req.get("method", "GET").upper()

        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES + 1):
            await self._limiter.wait()
            try:
                resp = await client.request(
                    method, url,
                    headers=headers, cookies=cookies,
                    params=params or None, json=body,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                if resp.status_code == 403:
                    # Being blocked is a signal to stop, not to try harder.
                    raise RuntimeError(
                        f"{self.slug}: 403 Forbidden — this store appears to be "
                        f"blocking the backend. Disable it in KIRANA_STORES."
                    )
                resp.raise_for_status()
                return self._parse(resp.json())
            except Exception as e:  # noqa: BLE001 — one store must not kill the search
                last_err = e
                if isinstance(e, RuntimeError) or attempt >= MAX_RETRIES:
                    break
                await asyncio.sleep(0.5)
        raise last_err or RuntimeError(f"{self.slug}: unknown failure")

    # -- response parsing --------------------------------------------------

    def _parse(self, payload: Any) -> list[RawOffer]:
        ex = self.recipe["extract"]
        fields = ex["fields"]
        deeplink_tpl = ex.get("deeplink_template")
        offers: list[RawOffer] = []

        for item in collect_items(payload, ex["items_path"]):
            title = dig_any(item, fields.get("title"))
            price = to_price(dig_any(item, fields.get("price")))
            if not title or price is None or price <= 0:
                continue

            mrp = to_price(dig_any(item, fields.get("mrp")))
            if mrp is not None and mrp < price:
                mrp = None  # some stores put the sale price in both fields

            stock_raw = dig_any(item, fields.get("in_stock"))
            in_stock = True
            if stock_raw is not None:
                if isinstance(stock_raw, bool):
                    in_stock = stock_raw
                elif isinstance(stock_raw, (int, float)):
                    in_stock = stock_raw > 0
                else:
                    in_stock = str(stock_raw).lower() not in (
                        "false", "0", "out_of_stock", "unavailable", "sold_out", "no")
            if ex.get("in_stock_invert"):
                in_stock = not in_stock

            pid = dig_any(item, fields.get("store_product_id"))
            deeplink = dig_any(item, fields.get("deeplink"))
            if not deeplink and deeplink_tpl and pid is not None:
                deeplink = deeplink_tpl.replace("{store_product_id}", str(pid))

            offers.append(RawOffer(
                store=self.slug,
                store_name=self.display_name,
                title=str(title).strip(),
                price=price,
                mrp=mrp,
                in_stock=in_stock,
                quantity_text=(lambda q: str(q) if q is not None else None)(
                    dig_any(item, fields.get("quantity_text"))),
                image_url=(lambda i: str(i) if i else None)(
                    dig_any(item, fields.get("image_url"))),
                deeplink=str(deeplink) if deeplink else None,
                store_product_id=str(pid) if pid is not None else None,
            ))

        log.info("%s: parsed %d offers", self.slug, len(offers))
        return offers
