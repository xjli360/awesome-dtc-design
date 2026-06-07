#!/usr/bin/env python3
"""
Build the public collection artifacts from the generated DESIGN.md files.

Outputs:
  INDEX.md          full, browsable index of every brand, grouped by category
  data/brands.csv   slug,category,brand_name,url for every completed brand
  _state/_featured.md     (dev) featured-brand bullets, for hand-assembling README
  _state/_categories.md   (dev) marquee-category <details> blocks, for README

Source of truth (first that exists):
  _state/selected.csv   author-side metadata for the full 3,000-brand universe
  data/brands.csv       committed metadata for the completed collection
"""

import csv
import re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DESIGN_DIR = ROOT / "design-md"
SELECTED = ROOT / "_state" / "selected.csv"
BRANDS_CSV = ROOT / "data" / "brands.csv"
INDEX = ROOT / "INDEX.md"
FEAT_OUT = ROOT / "_state" / "_featured.md"
CATS_OUT = ROOT / "_state" / "_categories.md"

DESC_RE = re.compile(r"^description:\s*(.+?)(?=\n[a-z_-]+:|\n---|\n## )", re.MULTILINE | re.DOTALL)

# Instantly-recognizable names to spotlight on the README front page.
# Any slug not present in the collection is silently skipped.
FEATURED = [
    "glossier", "aesop", "the-ordinary", "ordinary", "drunk-elephant", "fenty-beauty",
    "rare-beauty", "merit", "kosas", "saie", "tower-28", "youth-to-the-people",
    "summer-fridays", "topicals", "starface", "caraway", "our-place", "hexclad",
    "made-in", "great-jones", "smithey", "material-kitchen", "brooklinen", "parachute",
    "buffy", "casper", "cozy-earth", "quince", "saatva", "hay", "muuto", "blueland",
    "ritual", "hims", "peloton", "dyson", "roborock", "eufy", "coyuchi", "jones-road",
    "milk-makeup", "ilia-beauty",
]

# Marquee consumer-DTC categories to surface in the README "browse by category"
# section. The long tail (tech, gaming, music, books, ...) lives in INDEX.md.
MARQUEE_CATS = [
    "Skincare", "Makeup", "Haircare", "Body Care", "Bath", "Fragrance", "Oral Care",
    "Men's Grooming", "Cookware", "Kitchen Tools", "Dinnerware", "Bedding", "Decor",
    "Furniture", "Candles & Scent", "Vitamins & Supplements",
]

# High-level domains for the README overview table. Order matters (first match wins
# only for exact category names listed here; everything else rolls up to "More").
THEME_MAP = {
    "Beauty & Personal Care": [
        "Skincare", "Makeup", "Haircare", "Body Care", "Bath", "Bath/Shower",
        "Fragrance", "Men's Grooming", "Oral Care", "Feminine Care",
    ],
    "Health & Wellness": [
        "Vitamins & Supplements", "Wellness", "Women's Health", "Men's Health",
        "OTC/Wellness", "Tools/Devices", "Elderly Care",
    ],
    "Kitchen & Cookware": [
        "Cookware", "Kitchen Tools", "Dinnerware", "Small Kitchen Appliances",
        "Espresso Machines", "Grills/BBQ", "Pizza ovens", "Microwaves/Toaster Ovens",
        "Ranges/Cooktops/Ovens",
    ],
    "Home & Living": [
        "Bedding", "Decor", "Furniture", "Office Chairs", "Desks", "Organization",
        "Cleaning Supplies", "Laundry Products", "Vacuums", "Robotic Cleaners",
        "Air Purifiers", "Water Filtration/Dispensers", "Refrigerators", "Dishwashers",
        "Washers/Dryers", "HVAC/Portable AC/Heaters", "Smart Home & Appliances",
        "Candles & Scent", "Office Storage & Filing", "Office Specialty",
    ],
    "Outdoor & Garden": [
        "Outdoor furniture", "Outdoor", "Outdoor Apparel", "Outdoor Accessories",
        "Camping & Hiking Gear", "Hunting & Fishing", "Patio dining",
        "Fire pits/outdoor heaters", "Outdoor lighting", "Garden tools",
        "Lawn care equipment/mowers", "Seeds/plants nurseries", "Urban gardening",
        "Greenhouses/raised beds", "Pools/hot tubs/swim spas", "Planters/Pots",
        "Garden decor", "Outdoor rugs/textiles", "Wooden",
    ],
    "Sport & Fitness": [
        "Fitness & Gym", "Cycling", "Running", "Yoga", "Climbing", "Watersports",
        "Winter Sports", "Team Sports",
    ],
    "Baby & Kids": [
        "Baby Care", "Baby Clothing", "Baby/Infant", "Baby Toys", "Nursery Furniture",
        "Nursery Decor", "Strollers", "Carriers", "Feeding", "Educational", "STEM",
    ],
    "Stationery & Desk": [
        "Stationery & Paper", "Notebooks & Journals", "Pens & Writing",
        "Desk Accessories & Organizers", "Planners", "Paper Goods",
        "Labels & Markers & Highlighters", "Whiteboards & Cork boards",
        "Specialty Paper & Cards", "Monitor Arms & Stands", "Shredders & Calculators",
        "Printing services (DTC)", "Printer & Ink", "Arts & Crafts",
    ],
    "Tech & Computing": [
        "Cell Phones & Accessories", "Keyboards", "Mice", "Laptops",
        "Desktops/PCs/Builders", "Monitors", "Networking", "Docking stations/hubs",
        "Storage/SSDs", "Cables/Adapters", "Cooling/PC Parts", "Graphics Tablets",
        "Webcams", "Laptop Bags", "Measurement & Test Instruments",
        "Lab Equipment & Supplies", "Accessories",
    ],
    "Gaming & Collectibles": [
        "Board Games", "Card Games", "Tabletop RPG", "Trading Cards", "Controllers",
        "Gaming Chairs", "Gaming Desks", "VR Hardware", "Retro Game Retailer",
        "Arcade Maker", "AAA Publisher Store", "Indie Studio Merch", "Puzzles",
        "Action Figures", "Plush", "Collectibles", "Gear/Playmats",
    ],
    "Music & Instruments": [
        "Independent Record Store - US", "Independent Record Store - UK/EU",
        "Independent Record Store - Asia/Other", "Record Label with Shop",
        "Audiophile/Hi-Res Label", "Vinyl Pressing Plant", "DJ Gear",
        "Studio Monitors", "Wind Instruments", "Orchestral", "Ukuleles",
        "Audiobook DTC",
    ],
    "Books & Media": [
        "Independent Bookstore", "Specialty Bookstore", "Children's Bookstore",
        "Used/Rare Bookseller", "Comic Book Store", "Small Press Publisher",
        "Academic/University Press", "Zine/Art Book Publisher", "Book Subscription Box",
        "Movies & TV", "Niche Genre Store", "Import Shop",
    ],
}


_DANGLING = re.compile(r"[\s—,;:]+(?:of|and|with|in|on|to|a|an|the|that|by|as|for|from)"
                       r"\s*([.!?])\s*$", re.IGNORECASE)


def _polish(s: str) -> str:
    s = re.sub(r"\s*—\s*([.!?])", r"\1", s)   # trailing dash before period
    s = _DANGLING.sub(r"\1", s)                # drop dangling preposition+period
    s = re.sub(r"\s*—\s*$", "", s).strip(" —,;:")
    return s


def first_sentence(text: str) -> str:
    text = text.strip().replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"`[^`]+`", "", text)        # strip inline-code tokens
    text = re.sub(r"\{[^}]+\}", "", text)       # strip token refs
    text = re.sub(r"\([^)]*\b(?:meta|theme-color|token|var)\b[^)]*\)", "", text)  # stripped-token parens
    text = re.sub(r"\(\s*\)", "", text)         # collapse empty parens left behind
    text = re.sub(r"\s*—\s*—\s*", " — ", text)  # collapse doubled em-dash
    text = re.sub(r"\s+([,.;:])", r"\1", text)  # tighten punctuation
    text = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"^(.{40,180}?[.!?])\s", text)
    out = m.group(1).strip() if m else ((text[:180].rstrip() + "…") if text else "")
    return _polish(out)


def read_hook(slug: str) -> str:
    p = DESIGN_DIR / slug / "DESIGN.md"
    if not p.exists():
        return ""
    m = DESC_RE.search(p.read_text(encoding="utf-8"))
    return first_sentence(m.group(1)) if m else ""


def load_rows():
    src = SELECTED if SELECTED.exists() else BRANDS_CSV
    with src.open(newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f)]


def theme_for(cat: str) -> str:
    for theme, cats in THEME_MAP.items():
        if cat in cats:
            return theme
    return "More"


def anchor(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main():
    rows = load_rows()
    completed = []
    for r in rows:
        slug = r["slug"]
        if (DESIGN_DIR / slug / "DESIGN.md").exists():
            r["hook"] = read_hook(slug)
            completed.append(r)

    completed.sort(key=lambda r: r["brand_name"].lower())
    by_cat = defaultdict(list)
    for r in completed:
        by_cat[r["category"]].append(r)
    cat_order = sorted(by_cat.keys(), key=lambda c: (-len(by_cat[c]), c.lower()))
    total, ncats = len(completed), len(by_cat)

    # ---- data/brands.csv (committed, public metadata) ----
    BRANDS_CSV.parent.mkdir(exist_ok=True)
    with BRANDS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["slug", "category", "brand_name", "url"])
        for r in completed:
            w.writerow([r["slug"], r["category"], r["brand_name"], r.get("url", "")])

    # ---- INDEX.md (full collection) ----
    L = []
    L.append("# Full Collection Index")
    L.append("")
    L.append("[← Back to README](./README.md)")
    L.append("")
    L.append(f"**{total:,} brands · {ncats} categories.** Every generated design system, "
             "grouped by category. Auto-generated by [`scripts/build_index.py`](./scripts/build_index.py).")
    L.append("")
    L.append("**Jump to a category:**")
    L.append("")
    L.append(" · ".join(f"[{c}](#{anchor(c)}-{len(by_cat[c])})" for c in cat_order))
    L.append("")
    for c in cat_order:
        items = by_cat[c]
        L.append(f"## {c} ({len(items)})")
        L.append("")
        for r in items:
            hook = r.get("hook") or ""
            line = f"- [**{r['brand_name']}**](./design-md/{r['slug']}/DESIGN.md)"
            if hook:
                line += f" — {hook}"
            L.append(line)
        L.append("")
    INDEX.write_text("\n".join(L), encoding="utf-8")

    # ---- _state/_featured.md (dev helper for README) ----
    seen = set()
    fl = ["<!-- featured bullets for README -->", ""]
    for slug in FEATURED:
        if slug in seen or not (DESIGN_DIR / slug / "DESIGN.md").exists():
            continue
        seen.add(slug)
        r = next((x for x in completed if x["slug"] == slug), None)
        if not r:
            continue
        fl.append(f"- [**{r['brand_name']}**](./design-md/{slug}/DESIGN.md) — {r.get('hook','')}")
    FEAT_OUT.write_text("\n".join(fl), encoding="utf-8")

    # ---- _state/_categories.md (dev helper for README) ----
    cl = ["<!-- marquee category <details> blocks for README -->", ""]
    for c in MARQUEE_CATS:
        items = by_cat.get(c, [])
        if not items:
            continue
        cl.append(f"<details>")
        cl.append(f"<summary><b>{c}</b> &nbsp;<code>{len(items)}</code></summary>")
        cl.append("")
        for r in items:
            cl.append(f"- [**{r['brand_name']}**](./design-md/{r['slug']}/DESIGN.md) — {r.get('hook','')}")
        cl.append("")
        cl.append("</details>")
        cl.append("")
    CATS_OUT.write_text("\n".join(cl), encoding="utf-8")

    # ---- console: theme rollup + stats ----
    theme_counts = defaultdict(int)
    theme_cats = defaultdict(set)
    for c in by_cat:
        t = theme_for(c)
        theme_counts[t] += len(by_cat[c])
        theme_cats[t].add(c)
    print(f"INDEX.md written: {total:,} brands, {ncats} categories")
    print(f"data/brands.csv written: {total:,} rows")
    print("\nTheme rollup (for README overview table):")
    for t in sorted(theme_counts, key=lambda x: -theme_counts[x]):
        print(f"  {theme_counts[t]:4}  {t:24}  ({len(theme_cats[t])} categories)")
    print(f"\nFeatured bullets -> {FEAT_OUT}")
    print(f"Marquee categories -> {CATS_OUT}")


if __name__ == "__main__":
    main()
