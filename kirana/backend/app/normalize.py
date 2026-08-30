"""
Turns "Amul Taaza Fresh Toned Milk, 500 ml Pouch" into structured facts.

Everything downstream depends on getting quantity right, so that parser handles
the formats these four stores actually emit, including multipacks and the
"500g + 100g free" promo format.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .config import BRAND_ALIASES, STOPWORDS

# unit spelling -> (base unit, multiplier to base)
UNITS: dict[str, tuple[str, float]] = {
    "ml": ("ml", 1.0), "milliliter": ("ml", 1.0), "millilitre": ("ml", 1.0),
    "l": ("ml", 1000.0), "lt": ("ml", 1000.0), "ltr": ("ml", 1000.0),
    "litre": ("ml", 1000.0), "liter": ("ml", 1000.0),
    "g": ("g", 1.0), "gm": ("g", 1.0), "gms": ("g", 1.0),
    "gram": ("g", 1.0), "grams": ("g", 1.0),
    "kg": ("g", 1000.0), "kgs": ("g", 1000.0), "kilogram": ("g", 1000.0),
    "mg": ("g", 0.001),
    "pc": ("pc", 1.0), "pcs": ("pc", 1.0), "piece": ("pc", 1.0),
    "pieces": ("pc", 1.0), "unit": ("pc", 1.0), "units": ("pc", 1.0),
    "n": ("pc", 1.0), "no": ("pc", 1.0), "nos": ("pc", 1.0),
    "dozen": ("pc", 12.0),
}

_UNIT_ALT = "|".join(sorted(UNITS, key=len, reverse=True))

# "6 x 100 g"  /  "6x100g"  /  "2 X 1 L"
_MULTI_RE = re.compile(
    rf"(?<!\d)(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*({_UNIT_ALT})\b", re.I
)
# "500 ml"  /  "1.5L"  /  "250gm"
_SIMPLE_RE = re.compile(rf"(?<![\w.])(\d+(?:\.\d+)?)\s*({_UNIT_ALT})\b", re.I)
# "500 g + 100 g free"
_BONUS_RE = re.compile(
    rf"(\d+(?:\.\d+)?)\s*({_UNIT_ALT})\s*\+\s*(\d+(?:\.\d+)?)\s*({_UNIT_ALT})", re.I
)

_SORTED_BRANDS = sorted(BRAND_ALIASES, key=len, reverse=True)


@dataclass
class Parsed:
    raw_title: str
    brand: Optional[str] = None
    quantity: Optional[float] = None       # in display unit
    unit: Optional[str] = None             # display unit as written
    base_quantity: Optional[float] = None  # ml / g / pc
    base_unit: Optional[str] = None
    tokens: set[str] = field(default_factory=set)   # descriptor words
    quantity_label: Optional[str] = None            # "500 ml"


def _clean(text: str) -> str:
    text = text.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^\w.+×x]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_quantity(text: str) -> tuple[Optional[float], Optional[str], Optional[float], Optional[str]]:
    """Returns (display_qty, display_unit, base_qty, base_unit)."""
    if not text:
        return None, None, None, None
    t = text.lower()

    # "500g + 100g free" -> 600 g, but only when units agree
    m = _BONUS_RE.search(t)
    if m:
        a_val, a_unit, b_val, b_unit = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4)
        ba, ma = UNITS[a_unit]
        bb, mb = UNITS[b_unit]
        if ba == bb:
            total_base = a_val * ma + b_val * mb
            return total_base, ba, total_base, ba

    # "6 x 100 g" -> 600 g
    m = _MULTI_RE.search(t)
    if m:
        count, val, unit = int(m.group(1)), float(m.group(2)), m.group(3)
        base_unit, mult = UNITS[unit]
        base = count * val * mult
        return count * val, unit, base, base_unit

    # plain "500 ml" — if several appear, the largest is almost always the
    # pack size and the rest are nutrition blurb ("per 100g")
    best = None
    for m in _SIMPLE_RE.finditer(t):
        val, unit = float(m.group(1)), m.group(2)
        base_unit, mult = UNITS[unit]
        base = val * mult
        if best is None or base > best[2]:
            best = (val, unit, base, base_unit)
    if best:
        return best

    # bare "12" with no unit, as in "Eggs 12"
    m = re.search(r"(?<![\w.])(\d{1,3})\s*$", t.strip())
    if m:
        n = float(m.group(1))
        if 1 <= n <= 100:
            return n, "pc", n, "pc"
    return None, None, None, None


def _label(qty: Optional[float], unit: Optional[str]) -> Optional[str]:
    if qty is None or unit is None:
        return None
    q = int(qty) if float(qty).is_integer() else round(qty, 2)
    return f"{q} {unit}"


def extract_brand(cleaned: str) -> Optional[str]:
    """Brand is the leading token(s). Multi-word aliases are checked first."""
    for alias in _SORTED_BRANDS:
        if cleaned.startswith(alias + " ") or cleaned == alias:
            return BRAND_ALIASES[alias]
    first = cleaned.split(" ", 1)[0] if cleaned else ""
    if not first or first.isdigit() or first in STOPWORDS:
        return None
    return BRAND_ALIASES.get(first, first)


def normalize(title: str, quantity_text: Optional[str] = None) -> Parsed:
    p = Parsed(raw_title=title)
    cleaned = _clean(title)

    # Stores that give quantity in a separate field are more reliable than
    # anything scraped out of a title, so prefer it.
    qty, unit, base, base_unit = (None, None, None, None)
    if quantity_text:
        qty, unit, base, base_unit = parse_quantity(quantity_text)
    if base is None:
        qty, unit, base, base_unit = parse_quantity(cleaned)

    p.quantity, p.unit, p.base_quantity, p.base_unit = qty, unit, base, base_unit
    p.quantity_label = _label(qty, unit)
    p.brand = extract_brand(cleaned)

    # Descriptor tokens = everything that isn't the brand, a number, a unit,
    # or marketing noise. This is what fuzzy matching runs on.
    toks = set()
    for tok in cleaned.split():
        tok = tok.strip(".")
        if not tok or tok.isdigit():
            continue
        if tok in UNITS or tok in STOPWORDS:
            continue
        if re.fullmatch(rf"\d+(\.\d+)?({_UNIT_ALT})", tok, re.I):
            continue
        if p.brand and tok == p.brand:
            continue
        if len(tok) < 2:
            continue
        toks.add(tok)
    p.tokens = toks
    return p


def price_per_100(price: float, base_qty: Optional[float], base_unit: Optional[str]) -> Optional[float]:
    """₹ per 100 ml / 100 g, or ₹ per piece. The number that actually matters."""
    if not base_qty or base_qty <= 0 or not base_unit:
        return None
    if base_unit == "pc":
        return round(price / base_qty, 2)
    return round(price * 100.0 / base_qty, 2)
