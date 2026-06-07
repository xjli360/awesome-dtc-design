#!/usr/bin/env python3
"""
Select ~3000 DTC sites from ALL-SITES.csv with proportional category coverage.

Scoring within each category:
  +2 if `style` is non-empty (curated design note → likely well-built)
  +1 if `main_products` is non-empty
  +1 if `platform` is one of Shopify / Custom / Headless (signals modern stack)
  +1 if URL looks canonical (https, no random subdomain)

Within each category we keep ceil(N * target_ratio) sites, sorted by score desc.
"""

import csv
import math
import re
import unicodedata
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "ALL-SITES.csv"
OUT_SELECTED = ROOT / "_state" / "selected.csv"
OUT_QUEUE = ROOT / "_state" / "queue.txt"
TARGET = 3000


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"&", " and ", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"^the-", "", s)
    return s or "unnamed"


CANONICAL_PLATFORMS = {"shopify", "custom", "headless", "woocommerce", "bigcommerce"}


def score_row(row: dict) -> int:
    s = 0
    if (row.get("style") or "").strip():
        s += 2
    if (row.get("main_products") or "").strip():
        s += 1
    plat = (row.get("platform") or "").strip().lower()
    if plat in CANONICAL_PLATFORMS:
        s += 1
    url = (row.get("url") or "").strip()
    if url.startswith("https://") and "://www." not in url[:15] or url.startswith("https://www."):
        s += 1
    return s


def load_rows():
    rows = []
    with SRC.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, r in enumerate(reader):
            r = {k: (v or "").strip() for k, v in r.items() if k}
            if not r.get("url") or not r.get("brand_name") or not r.get("category"):
                continue
            r["_orig_idx"] = i
            r["_score"] = score_row(r)
            rows.append(r)
    return rows


def select(rows):
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    total = len(rows)
    ratio = TARGET / total

    selected = []
    for cat, items in by_cat.items():
        items.sort(key=lambda r: (-r["_score"], r["_orig_idx"]))
        keep_n = max(1, math.ceil(len(items) * ratio))
        keep_n = min(keep_n, len(items))
        selected.extend(items[:keep_n])
    # If oversampled, trim lowest scores until we hit TARGET (rare)
    if len(selected) > TARGET:
        selected.sort(key=lambda r: (-r["_score"], r["_orig_idx"]))
        selected = selected[:TARGET]
    return selected


def main():
    rows = load_rows()
    selected = select(rows)

    # Assign unique slugs (de-dupe collisions by appending category prefix)
    used = {}
    final = []
    for r in selected:
        base = slugify(r["brand_name"])
        slug = base
        n = 2
        while slug in used:
            slug = f"{base}-{slugify(r['category'])[:8]}-{n}" if n == 2 else f"{base}-{n}"
            n += 1
        used[slug] = True
        r["slug"] = slug
        final.append(r)

    OUT_SELECTED.parent.mkdir(parents=True, exist_ok=True)
    with OUT_SELECTED.open("w", newline="", encoding="utf-8") as f:
        fieldnames = ["slug", "category", "brand_name", "url", "platform",
                      "style", "main_products", "notes", "_score"]
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in final:
            w.writerow(r)

    with OUT_QUEUE.open("w", encoding="utf-8") as f:
        for r in final:
            f.write(f"{r['slug']}\t{r['brand_name']}\t{r['url']}\t{r['category']}\n")

    print(f"Total source rows: {len(rows)}")
    print(f"Categories: {len({r['category'] for r in rows})}")
    print(f"Selected: {len(final)}")
    print(f"Output: {OUT_SELECTED}")
    print(f"Queue:  {OUT_QUEUE}")


if __name__ == "__main__":
    main()
