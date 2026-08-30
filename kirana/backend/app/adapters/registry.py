from __future__ import annotations

import logging

from ..config import ENABLED_STORES, RECIPE_DIR
from .base import RecipeAdapter, StoreAdapter

log = logging.getLogger("kirana.registry")


def load_adapters() -> list[StoreAdapter]:
    """
    Loads every *.json recipe in app/recipes and keeps the ones listed in
    ENABLED_STORES. A recipe with "enabled": false is skipped — that is your
    kill switch for a store that starts blocking you.
    """
    adapters: list[StoreAdapter] = []
    if not RECIPE_DIR.exists():
        log.error("No recipe directory at %s", RECIPE_DIR)
        return adapters

    for path in sorted(RECIPE_DIR.glob("*.json")):
        # *.example.json are the committed skeletons with placeholder values.
        # Your real recipes (written by capture.py) contain live session
        # cookies, are git-ignored, and are the only ones ever loaded.
        if path.name.endswith(".example.json"):
            continue
        try:
            adapter = RecipeAdapter.from_file(path)
        except Exception as e:  # noqa: BLE001
            log.error("Bad recipe %s: %s", path.name, e)
            continue
        if adapter.recipe.get("enabled") is False:
            log.info("Skipping %s (disabled in recipe)", adapter.slug)
            continue
        if adapter.slug not in ENABLED_STORES:
            log.info("Skipping %s (not in KIRANA_STORES)", adapter.slug)
            continue
        adapters.append(adapter)
        log.info("Loaded adapter: %s", adapter.slug)

    if not adapters:
        log.warning(
            "No adapters loaded. Run tools/capture.py to create recipes — see "
            "SETUP.md section 3."
        )
    return adapters
