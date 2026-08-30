"""
These use the title formats the four stores actually emit. When you tune
MATCH_THRESHOLD, run these first — they'll tell you if you broke something.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.matcher import build_rows          # noqa: E402
from app.models import RawOffer             # noqa: E402
from app.normalize import normalize, parse_quantity, price_per_100  # noqa: E402


def offer(store, title, price, mrp=None, qty=None):
    return RawOffer(store=store, store_name=store.title(), title=title,
                    price=price, mrp=mrp, quantity_text=qty)


# ---------------------------------------------------------------- quantities

def test_parses_the_formats_these_stores_use():
    assert parse_quantity("500 ml")[2:] == (500.0, "ml")
    assert parse_quantity("1 L")[2:] == (1000.0, "ml")
    assert parse_quantity("1.5l")[2:] == (1500.0, "ml")
    assert parse_quantity("250gm")[2:] == (250.0, "g")
    assert parse_quantity("1 kg")[2:] == (1000.0, "g")
    assert parse_quantity("6 x 100 g")[2:] == (600.0, "g")
    assert parse_quantity("6x200ml")[2:] == (1200.0, "ml")
    assert parse_quantity("500 g + 100 g free")[2:] == (600.0, "g")
    assert parse_quantity("12 pcs")[2:] == (12.0, "pc")
    assert parse_quantity("1 dozen")[2:] == (12.0, "pc")


def test_separate_quantity_field_wins_over_title():
    p = normalize("Amul Taaza Toned Milk", quantity_text="500 ml")
    assert p.base_quantity == 500.0 and p.base_unit == "ml"


def test_unit_price_is_comparable_across_pack_sizes():
    small = price_per_100(36.0, 500.0, "ml")    # 500ml @ 36
    large = price_per_100(66.0, 1000.0, "ml")   # 1L   @ 66
    assert large < small          # the litre really is cheaper per ml
    assert small == 7.2 and large == 6.6


# ------------------------------------------------------------------ matching

def test_same_product_across_four_stores_becomes_one_row():
    rows = build_rows([
        offer("blinkit",   "Amul Taaza Toned Fresh Milk", 27.0, qty="500 ml"),
        offer("zepto",     "Amul Taaza Homogenised Toned Milk 500ml", 28.0),
        offer("instamart", "Amul Taaza Toned Milk Pouch", 27.5, qty="500 ml"),
        offer("bigbasket", "Amul Taaza Fresh Toned Milk, 500 ml Pouch", 29.0),
    ])
    assert len(rows) == 1, [r.display_name for r in rows]
    r = rows[0]
    assert r.stores_available == 4
    assert r.best_price == 27.0 and r.best_store == "blinkit"
    assert r.max_saving == 2.0


def test_different_sizes_never_merge():
    rows = build_rows([
        offer("blinkit", "Amul Taaza Toned Milk 500 ml", 27.0),
        offer("zepto",   "Amul Taaza Toned Milk 1 L", 66.0),
    ])
    assert len(rows) == 2


def test_variants_never_merge():
    rows = build_rows([
        offer("blinkit", "Amul Gold Full Cream Milk 500 ml", 35.0),
        offer("zepto",   "Amul Taaza Toned Milk 500 ml", 27.0),
    ])
    assert len(rows) == 2


def test_sugar_free_stays_separate():
    rows = build_rows([
        offer("blinkit", "Coca Cola Zero Sugar 750 ml", 45.0),
        offer("zepto",   "Coca Cola 750 ml", 45.0),
    ])
    assert len(rows) == 2


def test_different_brands_never_merge():
    rows = build_rows([
        offer("blinkit", "Amul Toned Milk 500 ml", 27.0),
        offer("zepto",   "Heritage Toned Milk 500 ml", 26.0),
    ])
    assert len(rows) == 2


def test_two_results_from_one_store_stay_separate():
    rows = build_rows([
        offer("zepto", "Amul Butter 100 g", 58.0),
        offer("zepto", "Amul Butter 100 g", 58.0),
    ])
    assert len(rows) == 2   # same store twice is two products, not a match


def test_single_store_items_still_appear():
    rows = build_rows([
        offer("blinkit", "Amul Taaza Toned Milk 500 ml", 27.0),
        offer("zepto",   "Amul Taaza Toned Milk 500 ml", 28.0),
        offer("zepto",   "Epigamia Greek Yogurt Mango 90 g", 45.0),
    ])
    names = {r.display_name for r in rows}
    assert any("Epigamia" in n for n in names)
    assert len(rows) == 2


def test_out_of_stock_sorts_last_and_ignores_best_price():
    rows = build_rows([
        offer("blinkit", "Amul Taaza Toned Milk 500 ml", 20.0),
        offer("zepto",   "Amul Taaza Toned Milk 500 ml", 28.0),
    ])
    rows[0].offers  # sanity
    oos = RawOffer(store="blinkit", store_name="Blinkit",
                   title="Amul Taaza Toned Milk 500 ml", price=20.0, in_stock=False)
    rows = build_rows([oos, offer("zepto", "Amul Taaza Toned Milk 500 ml", 28.0)])
    r = rows[0]
    assert r.offers[0].store == "zepto"      # in-stock first
    assert r.best_price == 28.0              # don't advertise a price you can't buy


def test_discount_percentage():
    rows = build_rows([offer("blinkit", "Amul Butter 100 g", 50.0, mrp=62.0)])
    assert rows[0].offers[0].discount_pct == 19


def test_bogus_mrp_below_price_is_dropped():
    rows = build_rows([offer("blinkit", "Amul Butter 100 g", 62.0, mrp=50.0)])
    assert rows[0].offers[0].mrp is None
