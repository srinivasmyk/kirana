"""
Cross-store product matching. This is the heart of the app.

Strategy: bucket first, then score. Bucketing by (brand, rounded base quantity)
makes the comparison cheap and, more importantly, makes it *correct* — quantity
is a hard gate, not a soft signal, because 500 ml and 1 L are different products
no matter how similar their titles look.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from rapidfuzz import fuzz

from .config import MATCH_THRESHOLD, QUANTITY_TOLERANCE, VARIANT_TOKENS
from .models import Offer, ProductRow, RawOffer
from .normalize import Parsed, normalize, price_per_100


def _to_offer(raw: RawOffer, p: Parsed) -> Offer:
    # Some stores put the sale price in the MRP field too. An "MRP" at or below
    # the price is meaningless, and showing it would imply a discount that
    # doesn't exist — so drop it here, where every offer passes through.
    mrp = raw.mrp if (raw.mrp and raw.mrp > raw.price > 0) else None
    discount = None
    if mrp:
        discount = int(round((mrp - raw.price) / mrp * 100))
    return Offer(
        store=raw.store,
        store_name=raw.store_name,
        title=raw.title,
        price=raw.price,
        mrp=mrp,
        discount_pct=discount,
        in_stock=raw.in_stock,
        image_url=raw.image_url,
        deeplink=raw.deeplink,
        brand=p.brand,
        quantity=p.quantity,
        unit=p.unit,
        base_quantity=p.base_quantity,
        base_unit=p.base_unit,
        price_per_100=price_per_100(raw.price, p.base_quantity, p.base_unit),
    )


def _variant_signature(tokens: set[str]) -> frozenset[str]:
    """The variant-defining words present. Must match exactly between offers."""
    return frozenset(t for t in tokens if t in VARIANT_TOKENS)


def _quantities_agree(a: Parsed, b: Parsed) -> bool:
    if a.base_quantity is None or b.base_quantity is None:
        # If neither side declares a quantity, allow the match and let the
        # descriptor score decide. If exactly one declares, don't guess.
        return a.base_quantity is None and b.base_quantity is None
    if a.base_unit != b.base_unit:
        return False
    hi = max(a.base_quantity, b.base_quantity)
    return hi > 0 and abs(a.base_quantity - b.base_quantity) / hi <= QUANTITY_TOLERANCE


def similarity(a: Parsed, b: Parsed) -> float:
    """0..1 descriptor similarity, gated on variant words."""
    if _variant_signature(a.tokens) != _variant_signature(b.tokens):
        return 0.0
    if not a.tokens or not b.tokens:
        return 0.0
    sa, sb = " ".join(sorted(a.tokens)), " ".join(sorted(b.tokens))
    token_set = fuzz.token_set_ratio(sa, sb) / 100.0
    # Jaccard punishes one side having lots of extra words; averaging the two
    # keeps "milk" from matching "milk chocolate drink powder".
    jacc = len(a.tokens & b.tokens) / len(a.tokens | b.tokens)
    return 0.6 * token_set + 0.4 * jacc


def _bucket_key(p: Parsed) -> tuple:
    """Cheap pre-filter. Quantity rounded to 1% so near-equal sizes collide."""
    if p.base_quantity is None:
        return (p.brand, None, None)
    return (p.brand, p.base_unit, round(p.base_quantity / max(p.base_quantity * 0.01, 1e-9)))


def _pick_display(cluster: list[tuple[Offer, Parsed]]) -> tuple[str, Optional[str]]:
    """Shortest title tends to be the cleanest. Pick an image from any store."""
    offers = sorted(cluster, key=lambda c: len(c[0].title))
    name = offers[0][0].title
    image = next((o.image_url for o, _ in cluster if o.image_url), None)
    return name, image


def build_rows(raws: list[RawOffer]) -> list[ProductRow]:
    parsed: list[tuple[Offer, Parsed]] = []
    for r in raws:
        if r.price is None or r.price <= 0:
            continue
        p = normalize(r.title, r.quantity_text)
        parsed.append((_to_offer(r, p), p))

    buckets: dict[tuple, list[tuple[Offer, Parsed]]] = defaultdict(list)
    for item in parsed:
        buckets[_bucket_key(item[1])].append(item)

    clusters: list[list[tuple[Offer, Parsed]]] = []
    for items in buckets.values():
        # Greedy agglomeration within the bucket. Buckets are small (single
        # digits, usually), so O(n²) here is free and easier to reason about
        # than anything cleverer.
        local: list[list[tuple[Offer, Parsed]]] = []
        for offer, p in items:
            placed = False
            for cluster in local:
                # One offer per store per cluster — two Zepto results are two
                # different products, not a match.
                if any(o.store == offer.store for o, _ in cluster):
                    continue
                if all(
                    _quantities_agree(p, q) and similarity(p, q) >= MATCH_THRESHOLD
                    for _, q in cluster
                ):
                    cluster.append((offer, p))
                    placed = True
                    break
            if not placed:
                local.append([(offer, p)])
        clusters.extend(local)

    rows: list[ProductRow] = []
    for cluster in clusters:
        offers = [o for o, _ in cluster]
        # In stock first, then by unit price when we have it, else by price.
        offers.sort(key=lambda o: (not o.in_stock, o.price_per_100 or 1e9, o.price))
        live = [o for o in offers if o.in_stock] or offers
        best = min(live, key=lambda o: o.price)
        worst = max(live, key=lambda o: o.price)
        name, image = _pick_display(cluster)
        p0 = cluster[0][1]
        rows.append(
            ProductRow(
                display_name=name,
                brand=p0.brand,
                quantity_label=p0.quantity_label,
                image_url=image,
                offers=offers,
                best_price=best.price,
                best_store=best.store,
                max_saving=round(worst.price - best.price, 2),
                stores_available=len([o for o in offers if o.in_stock]),
            )
        )

    # Rows covering more stores are more useful, then the biggest savings,
    # then cheapest. A row from one store is still shown — "only Zepto has it"
    # is a real answer.
    rows.sort(key=lambda r: (-r.stores_available, -r.max_saving, r.best_price))
    return rows
