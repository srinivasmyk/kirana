#!/usr/bin/env python3
"""
capture.py — build a store recipe from a request you copied out of Chrome.

This is the tool you reach for when a store breaks. You never need to write
Python; you copy a request out of your browser and this figures out the rest.

HOW TO USE
  1. Open the store's website in Chrome, set your delivery address.
  2. Press F12 -> Network tab -> filter "Fetch/XHR".
  3. Search for something distinctive, like "amul".
  4. Find the request whose response contains the products (click through them
     and look at the Preview tab; it's usually called search / products / layout).
  5. Right-click it -> Copy -> Copy as cURL.
  6. Run:
         python tools/capture.py --slug blinkit --term amul --paste
     then paste, and press Ctrl-D (Ctrl-Z Enter on Windows).

It will replace your search term with {query_raw} and your coordinates with
{lat}/{lon}, replay the request, inspect the JSON, guess the extraction paths,
and write app/recipes/<slug>.json. Review the guesses — they are guesses.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Optional

RECIPE_DIR = Path(__file__).resolve().parent.parent / "app" / "recipes"

# key-name hints, best first
HINTS = {
    "title": ["name", "display_name", "desc", "product_name", "title", "text"],
    "price": ["offer_price", "selling_price", "sellingprice", "discounted_price",
              "sp", "normal_price", "price", "final_price"],
    "mrp": ["mrp", "strike_price", "list_price", "original_price", "max_price"],
    "quantity_text": ["pack_size", "packsize", "formattedpacksize", "variant",
                      "quantity", "unit", "weight", "w", "pack_desc"],
    "image_url": ["image_url", "image", "images", "img", "photo", "thumbnail"],
    "in_stock": ["in_stock", "instock", "available", "availability", "inventory",
                 "outofstock", "out_of_stock", "is_sold_out"],
    "store_product_id": ["product_id", "productid", "sku", "id", "pid"],
}


# ---------------------------------------------------------------- curl parsing

def parse_curl(text: str) -> dict:
    text = text.strip().replace("\\\n", " ").replace("^\n", " ").replace("\n", " ")
    tokens = shlex.split(text)
    if not tokens or tokens[0] != "curl":
        raise SystemExit("That doesn't look like a cURL command (should start with 'curl').")

    out = {"method": None, "url": None, "headers": {}, "cookies": {}, "body": None}
    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t in ("-X", "--request"):
            out["method"] = tokens[i + 1]; i += 2
        elif t in ("-H", "--header"):
            k, _, v = tokens[i + 1].partition(":")
            k, v = k.strip(), v.strip()
            if k.lower() == "cookie":
                for pair in v.split(";"):
                    ck, _, cv = pair.strip().partition("=")
                    if ck:
                        out["cookies"][ck] = cv
            elif k.lower() not in ("content-length", "host", "connection", "accept-encoding"):
                out["headers"][k] = v
            i += 2
        elif t in ("-b", "--cookie"):
            for pair in tokens[i + 1].split(";"):
                ck, _, cv = pair.strip().partition("=")
                if ck:
                    out["cookies"][ck] = cv
            i += 2
        elif t in ("-d", "--data", "--data-raw", "--data-binary"):
            out["body"] = tokens[i + 1]; i += 2
        elif t.startswith("-"):
            i += 1  # --compressed, -k, etc.
        else:
            if out["url"] is None:
                out["url"] = t
            i += 1

    if not out["url"]:
        raise SystemExit("Couldn't find a URL in that cURL command.")
    out["method"] = out["method"] or ("POST" if out["body"] else "GET")
    return out


def templatize(value: str, term: str, lat: Optional[str], lon: Optional[str]) -> str:
    """Swap the literal search term and coordinates for placeholders."""
    if term:
        value = re.sub(re.escape(term), "{query_raw}", value, flags=re.I)
    if lat:
        value = value.replace(lat, "{lat}")
    if lon:
        value = value.replace(lon, "{lon}")
    return value


def apply_templates(curl: dict, term: str, lat, lon) -> dict:
    curl["url"] = templatize(curl["url"], term, lat, lon)
    curl["headers"] = {k: templatize(v, term, lat, lon) for k, v in curl["headers"].items()}
    curl["cookies"] = {k: templatize(v, term, lat, lon) for k, v in curl["cookies"].items()}
    if curl["body"]:
        curl["body"] = templatize(curl["body"], term, lat, lon)
    return curl


# ------------------------------------------------------------- json inspection

def walk(node: Any, path: str = "", depth: int = 0):
    if depth > 8:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else k, depth + 1)
    elif isinstance(node, list):
        yield path, node
        if node:
            yield from walk(node[0], f"{path}[0]", depth + 1)


def find_item_arrays(payload: Any) -> list[tuple[str, list]]:
    """Candidate product arrays: lists of dicts that mention a price-ish key."""
    out = []
    for path, node in walk(payload):
        if not isinstance(node, list) or len(node) < 2:
            continue
        if not isinstance(node[0], dict):
            continue
        blob = json.dumps(node[0]).lower()
        score = sum(1 for h in ("price", "mrp", "name", "sku", "product") if h in blob)
        if score >= 2:
            out.append((path, node, score * 100 + len(node)))
    out.sort(key=lambda x: -x[2])
    return [(p, n) for p, n, _ in out]


def leaf_paths(obj: Any, prefix: str = "", depth: int = 0) -> list[tuple[str, Any]]:
    if depth > 6:
        return []
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                out += leaf_paths(v, p, depth + 1)
            else:
                out.append((p, v))
    elif isinstance(obj, list) and obj:
        out += leaf_paths(obj[0], f"{prefix}[0]", depth + 1)
    return out


def guess_fields(sample: dict) -> dict:
    leaves = leaf_paths(sample)
    guesses: dict[str, list[str]] = {}
    for field, hints in HINTS.items():
        scored = []
        for path, value in leaves:
            last = path.split(".")[-1].split("[")[0].lower()
            for rank, hint in enumerate(hints):
                if last == hint:
                    bonus = 0
                    if field in ("price", "mrp") and isinstance(value, (int, float)):
                        bonus = -5
                    if field == "title" and isinstance(value, str) and len(value) > 5:
                        bonus = -5
                    if field == "image_url" and isinstance(value, str) and "http" in str(value):
                        bonus = -5
                    scored.append((rank + bonus, path))
                    break
                if hint in last:
                    scored.append((rank + 20, path))
                    break
        scored.sort()
        if scored:
            guesses[field] = [p for _, p in scored[:3]]
    return guesses


# ---------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description="Build a Kirana store recipe from a cURL command.")
    ap.add_argument("--slug", required=True, help="blinkit | zepto | instamart | bigbasket | ...")
    ap.add_argument("--name", help="Display name, e.g. 'Swiggy Instamart'")
    ap.add_argument("--term", required=True, help="The word you searched for in the browser")
    ap.add_argument("--lat", help="Latitude as it literally appears in the request")
    ap.add_argument("--lon", help="Longitude as it literally appears in the request")
    ap.add_argument("--paste", action="store_true", help="Read the cURL from stdin")
    ap.add_argument("--file", help="Read the cURL from a file instead")
    ap.add_argument("--no-replay", action="store_true", help="Skip the live test call")
    args = ap.parse_args()

    if args.file:
        raw = Path(args.file).read_text()
    elif args.paste:
        print("Paste the cURL command, then Ctrl-D (Ctrl-Z Enter on Windows):\n", file=sys.stderr)
        raw = sys.stdin.read()
    else:
        raise SystemExit("Use --paste or --file.")

    curl = apply_templates(parse_curl(raw), args.term, args.lat, args.lon)

    recipe = {
        "slug": args.slug,
        "display_name": args.name or args.slug.title(),
        "enabled": True,
        "request": {
            "method": curl["method"],
            "url": curl["url"],
            "headers": curl["headers"],
            "cookies": curl["cookies"],
        },
        "extract": {"items_path": [], "fields": {}},
    }
    if curl["body"]:
        try:
            recipe["request"]["json_body"] = json.loads(curl["body"])
        except json.JSONDecodeError:
            recipe["request"]["raw_body"] = curl["body"]

    if not args.no_replay:
        import httpx
        print("Replaying the request to inspect the response...", file=sys.stderr)
        ctx = {"query_raw": args.term, "query": args.term,
               "lat": args.lat or "0", "lon": args.lon or "0"}

        def fill(v):
            if isinstance(v, str):
                for k, val in ctx.items():
                    v = v.replace("{" + k + "}", val)
                return v
            if isinstance(v, dict):
                return {k: fill(x) for k, x in v.items()}
            return v

        try:
            r = httpx.request(
                recipe["request"]["method"], fill(recipe["request"]["url"]),
                headers=fill(recipe["request"]["headers"]),
                cookies=fill(recipe["request"]["cookies"]),
                json=recipe["request"].get("json_body"),
                timeout=15, follow_redirects=True,
            )
            print(f"HTTP {r.status_code}, {len(r.content)} bytes", file=sys.stderr)
            payload = r.json()
            Path(f"/tmp/{args.slug}_response.json").write_text(json.dumps(payload, indent=2)[:2_000_000])
            print(f"Full response saved to /tmp/{args.slug}_response.json", file=sys.stderr)

            candidates = find_item_arrays(payload)
            if candidates:
                print("\nCandidate product arrays found:", file=sys.stderr)
                for path, node in candidates[:5]:
                    print(f"  {path}   ({len(node)} items)", file=sys.stderr)
                best_path, best_items = candidates[0]
                recipe["extract"]["items_path"] = [best_path]
                recipe["extract"]["fields"] = guess_fields(best_items[0])
                print(f"\nUsing '{best_path}'. Guessed fields:", file=sys.stderr)
                for k, v in recipe["extract"]["fields"].items():
                    val = best_items[0]
                    print(f"  {k:18} -> {v[0]}", file=sys.stderr)
            else:
                print("\nNo obvious product array. Open the saved JSON and set "
                      "items_path by hand.", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"Replay failed: {e}\nRecipe still written; fill extract paths manually.",
                  file=sys.stderr)

    RECIPE_DIR.mkdir(parents=True, exist_ok=True)
    out = RECIPE_DIR / f"{args.slug}.json"
    out.write_text(json.dumps(recipe, indent=2))
    print(f"\nWrote {out}", file=sys.stderr)
    print("Review the extract paths, then restart the backend and try a search.", file=sys.stderr)
    if recipe["request"].get("cookies"):
        print(
            "\n  NOTE: this file now contains your live session cookies for "
            f"{args.slug}.\n  It is git-ignored. Never commit it, paste it in a "
            "chat, or share it.\n",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
