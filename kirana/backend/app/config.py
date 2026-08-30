"""
Every knob you are likely to turn lives in this file.

You will end up editing MATCH_THRESHOLD and VARIANT_TOKENS once you see real
results for your neighbourhood. That is expected, not a sign anything is broken.
"""
import os
from pathlib import Path

# --- API ---------------------------------------------------------------
API_KEY = os.getenv("KIRANA_API_KEY", "change-me")
DB_PATH = Path(os.getenv("KIRANA_DB", "/data/kirana.sqlite3"))
RECIPE_DIR = Path(__file__).parent / "recipes"

# --- Which stores are live --------------------------------------------
# Remove a slug here to disable a store instantly, no code change, no redeploy
# beyond a restart. This is your kill switch if a store starts blocking you.
ENABLED_STORES = [
    s.strip()
    for s in os.getenv("KIRANA_STORES", "blinkit,zepto,instamart,bigbasket").split(",")
    if s.strip()
]

# --- Politeness -------------------------------------------------------
# Do not raise these. They are the difference between "a person shopping" and
# "a bot", both technically and ethically.
REQUESTS_PER_SECOND_PER_STORE = 1.0
REQUEST_TIMEOUT_SECONDS = 8.0
MAX_RETRIES = 1
CACHE_TTL_SECONDS = 600          # 10 min
GEOHASH_PRECISION = 7            # ~150 m, roughly one dark-store catchment

USER_AGENT = os.getenv(
    "KIRANA_UA",
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36",
)

# --- Matching ---------------------------------------------------------
# Descriptor similarity required to call two offers the same product.
# Too low  -> unrelated things get merged (bad, and hard to notice)
# Too high -> the same product shows as 4 separate rows (obvious, less harmful)
# Start conservative. 0.72 is a good opening bid.
MATCH_THRESHOLD = float(os.getenv("KIRANA_MATCH_THRESHOLD", "0.72"))

# Two offers must have quantities within this fraction to ever match.
# This is a hard gate. 500ml and 1L are different products.
QUANTITY_TOLERANCE = 0.02

# If any of these words appears on one side, it must appear on the other.
# This is what stops "sugar free" matching "regular".
VARIANT_TOKENS = {
    "toned", "double", "slim", "skimmed", "fullcream", "full", "cream",
    "sugarfree", "diet", "zero", "lite", "light",
    "organic", "natural",
    "spicy", "hot", "sweet", "salted", "unsalted", "plain",
    "brown", "white", "red", "green", "black",
    "refined", "cold", "pressed", "filtered", "raw",
    "small", "medium", "large", "jumbo",
}

# Brands the stores spell differently. Left side is what you might see,
# right side is the canonical form.
BRAND_ALIASES = {
    "amul india": "amul",
    "mother dairy": "motherdairy",
    "tata sampann": "tata",
    "tata consumer": "tata",
    "aashirvaad": "ashirvaad",
    "britannia industries": "britannia",
    "id fresh": "idfresh",
    "id fresh food": "idfresh",
    "fortune": "fortune",
    "b natural": "bnatural",
    "too yumm": "tooyumm",
    "the whole truth": "wholetruth",
    "24 mantra": "24mantra",
    "24 mantra organic": "24mantra",
}

# Marketing noise that carries no product meaning. Stripped before matching.
STOPWORDS = {
    "pack", "packet", "pouch", "bottle", "box", "tin", "can", "jar", "combo",
    "fresh", "premium", "special", "quality", "best", "new", "offer", "value",
    "of", "the", "and", "with", "for", "in", "by", "a", "an",
    "buy", "get", "free", "save", "mrp", "rs", "inr",
}
