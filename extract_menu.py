"""
Menu PDF → JSON extractor
Takes a two-column restaurant menu PDF and outputs structured JSON.

Auto-detects section headers via font-size analysis (no hardcoded list).
Splits concatenated drink/item lists (e.g. "MILLER LITE $X COORS LIGHT $X")
into individual entries.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path

import pdfplumber


### Regex patterns
# Price: $17, $17.50, or placeholder $X
PRICE_RE = re.compile(r"\$\s?(?:\d+(?:\.\d{1,2})?|X)")

# Dish-name line: ALL-CAPS text, optionally followed by a price
DISH_NAME_RE = re.compile(
    r"^([A-Z0-9&'\u2019\-\.\(\)\s]{3,})(?:\s+(\$\s?(?:\d+(?:\.\d{1,2})?|X)))?\s*$"
)

# Pattern for finding individual items inside concatenated drink/item lists
# Matches: UPPERCASE NAME  $PRICE
DRINK_ITEM_RE = re.compile(
    r"([A-Z0-9][A-Z0-9&'\u2019\-\.\(\)\s]*?)\s+(\$(?:\d+(?:\.\d{1,2})?|X))"
)

# Lines to always ignore (footers, legal text, etc.)
NOISE_PATTERNS = [
    r"consuming raw",
    r"gratuity",
    r"espn",
    r"foodborne illness",
    r"^\s*$",
]
NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.IGNORECASE)


### Data model 
@dataclass
class Dish:
    dish_id: str
    category: str
    dish_name: str
    price: str | None
    description: str
    subcategory: str | None = None


@dataclass
class Sauce:
    sauce_id: str
    category: str
    sauce_name: str


@dataclass
class LineInfo:
    """A line of extracted text together with its dominant font size."""
    text: str
    font_size: float


### Helpers
def normalize_ws(text: str) -> str:
    """Collapse repeated whitespace and strip."""
    return re.sub(r"\s+", " ", text).strip()


def split_name_price(line: str) -> tuple[str, str | None]:
    """'ALL AMERICAN BURGER $17' -> ('ALL AMERICAN BURGER', '$17')"""
    m = PRICE_RE.search(line)
    if m:
        price = m.group().replace(" ", "")
        name = line[: m.start()].strip()
        return normalize_ws(name), price
    return normalize_ws(line), None


def looks_like_dish_name(line: str) -> bool:
    """Heuristic: ALL-CAPS, reasonably short, matches dish-name regex."""
    s = normalize_ws(line)
    if not s or not DISH_NAME_RE.match(s):
        return False
    return len(s) <= 60


def split_drink_items(text: str) -> list[tuple[str, str, str]]:
    """
    Split a concatenated drink/item list into individual entries.

    'MILLER LITE $X COORS LIGHT $X'
        -> [('MILLER LITE', '$X', ''), ('COORS LIGHT', '$X', '')]

    'DILLINOIS $X miller lite, pickle brine CHI-LADA $X modelo especial'
        -> [('DILLINOIS', '$X', 'miller lite, pickle brine'),
            ('CHI-LADA', '$X', 'modelo especial')]

    Returns empty list if fewer than 2 items found (i.e. not a list).
    """
    matches = list(DRINK_ITEM_RE.finditer(text))
    if len(matches) < 2:
        return []
    items: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        name = normalize_ws(m.group(1))
        price = m.group(2).replace(" ", "")
        desc_start = m.end()
        desc_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        desc = normalize_ws(text[desc_start:desc_end])
        items.append((name, price, desc))
    return items


# PDF extraction with font metadata
def extract_lines_with_fonts(pdf_path: Path) -> list[LineInfo]:
    """
    Extract text from a two-column PDF, preserving per-line font size.
    Each page is split at the horizontal midpoint; left column is read
    top-to-bottom, then the right column.
    """
    results: list[LineInfo] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            mid_x = page.width / 2
            for bbox in [
                (0, 0, mid_x, page.height),
                (mid_x, 0, page.width, page.height),
            ]:
                col = page.within_bbox(bbox)
                chars = col.chars
                if not chars:
                    continue

                # Group characters into lines by vertical position (top)
                buckets: dict[float, list[dict]] = {}
                for ch in chars:
                    y = round(ch["top"], 0)
                    placed = False
                    for ey in list(buckets):
                        if abs(ey - y) < 3:
                            buckets[ey].append(ch)
                            placed = True
                            break
                    if not placed:
                        buckets[y] = [ch]

                for y in sorted(buckets):
                    line_chars = sorted(buckets[y], key=lambda c: c["x0"])

                    SUB_COL_GAP = 15
                    segments: list[list[dict]] = [[]]
                    for idx, c in enumerate(line_chars):
                        if idx > 0:
                            gap = c["x0"] - line_chars[idx - 1]["x1"]
                            if gap > SUB_COL_GAP:
                                segments.append([])
                        segments[-1].append(c)

                    for seg in segments:
                        # Build text with small-gap spacing
                        parts: list[str] = []
                        for idx, c in enumerate(seg):
                            if idx > 0:
                                gap = c["x0"] - seg[idx - 1]["x1"]
                                avg_w = seg[idx - 1]["x1"] - seg[idx - 1]["x0"]
                                if gap > max(avg_w * 0.6, 2):
                                    parts.append(" ")
                            parts.append(c["text"])
                        text = "".join(parts).strip()

                        if not text or NOISE_RE.search(text):
                            continue

                        visible = [c for c in seg if c["text"].strip()]
                        if not visible:
                            continue

                        avg_size = sum(c["size"] for c in visible) / len(visible)
                        results.append(LineInfo(text=text, font_size=round(avg_size, 1)))

    return results


def find_header_indices(lines: list[LineInfo]) -> set[int]:
    """
    Identify section-header lines by font size.
    Any ALL-CAPS line whose font size is noticeably larger than the most
    common (body) font size is treated as a category header.
    """
    if not lines:
        return set()

    # Most-common rounded font size = body text
    size_counts = Counter(round(li.font_size) for li in lines)
    body_size = size_counts.most_common(1)[0][0]

    headers: set[int] = set()
    for i, li in enumerate(lines):
        text = normalize_ws(li.text)
        if (
            li.font_size >= body_size + 1.5
            and text == text.upper()
            and len(text) <= 50
            and not PRICE_RE.search(text)
        ):
            headers.add(i)

    return headers


def _split_embedded_subitem(d: Dish) -> Dish:
    """
    If a description contains an embedded sub-item (ALL-CAPS name
    with a price appearing after lowercase description text),
    truncate the description before that sub-item.
    """
    desc = d.description
    if not desc:
        return d

    for i in range(1, len(desc) - 5):
        if desc[i] == " " and desc[i - 1].islower():
            rest = desc[i + 1 :]
            # Check if rest starts with a potential sub-item
            m = re.match(
                r'[“”"]*[A-Z][A-Z0-9 &.\x27\u2019\u201c\u201d"-]{2,}[“”"]*\s+\$(?:\d+(?:\.\d{1,2})?|X)',
                rest,
            )
            if m:
                clean_desc = normalize_ws(desc[:i])
                return Dish(
                    dish_id=d.dish_id,
                    category=d.category,
                    dish_name=d.dish_name,
                    price=d.price,
                    description=clean_desc,
                )
    return d


### Parsing
def parse_dishes(lines: list[LineInfo], header_indices: set[int]) -> list[Dish]:
    """
    Two-pass parser:
      1. State machine walks lines; font-detected headers set the current
         category, ALL-CAPS dish-name lines start a new dish, everything
         else is appended to the current description.
      2. Post-process: descriptions that contain concatenated item lists
         (e.g. beer menus) are expanded into individual Dish entries,
         using the parent dish_name as their sub-category.
    """
    raw: list[Dish] = []
    category: str | None = None
    current: dict | None = None
    seq = 0

    def flush():
        nonlocal current
        if current and current["dish_name"]:
            current["description"] = normalize_ws(current["description"])
            raw.append(Dish(**current))
        current = None

    for i, li in enumerate(lines):
        clean = normalize_ws(li.text)

        # Section header 
        if i in header_indices:
            flush()
            category = clean.upper()
            continue

        # Dish name
        if category and looks_like_dish_name(clean):
            flush()
            name, price = split_name_price(clean)
            seq += 1
            current = {
                "dish_id": f"{seq:03d}",
                "category": category,
                "dish_name": name,
                "price": price,
                "description": "",
            }
            continue

        # Description / price continuation
        if current is not None:
            if current["price"] is None and PRICE_RE.fullmatch(clean):
                current["price"] = clean.replace(" ", "")
            else:
                current["description"] += " " + clean

    flush()

    # Post-process: clean descriptions and expand lists
    expanded: list[Dish] = []
    counter = 0
    for d in raw:
    
        d = _split_embedded_subitem(d)

        items = split_drink_items(d.description)
        if items:
            sub_cat = d.dish_name or d.category
            for name, price, desc in items:
                counter += 1
                expanded.append(Dish(
                    dish_id=f"{counter:03d}",
                    category=sub_cat,
                    dish_name=name,
                    price=price,
                    description=desc,
                ))
        else:
            counter += 1
            expanded.append(Dish(
                dish_id=f"{counter:03d}",
                category=d.category,
                dish_name=d.dish_name,
                price=d.price,
                description=d.description,
            ))

    return expanded


# Category constants for post-processing
_CHICKEN_CAT = "AIN\u2019T NO THING BUT A CHICKEN\u2026"


def postprocess_output(dishes: list[Dish]) -> list[dict]:
    """
    Convert parsed Dish list into final output dicts:
    - Sauces/rubs use {sauce_id, category, sauce_name} (no price/description).
    - Chicken section gets subcategory field; sub-header items are removed.
    """
    # Chicken: identify sub-headers and assign subcategories
    chicken_markers: list[Dish] = []
    chicken_priced: list[Dish] = []
    marker_ids: set[str] = set()

    for d in dishes:
        if d.category == _CHICKEN_CAT:
            if d.price is None and not d.description:
                chicken_markers.append(d)
                marker_ids.add(d.dish_id)
            else:
                chicken_priced.append(d)

    if len(chicken_markers) >= 2:
        for idx, item in enumerate(chicken_priced):
            item.subcategory = chicken_markers[idx % len(chicken_markers)].dish_name

    # Sauces
    rubs_marker_id: str | None = None
    for d in dishes:
        if d.category == "SIGNATURE SAUCES" and d.dish_name == "SIGNATURE RUBS":
            rubs_marker_id = d.dish_id
            break

    # Build output
    result: list[dict] = []
    dish_seq = 0
    sauce_seq = 0
    past_rubs = False

    for d in dishes:
        if d.dish_id in marker_ids:
            continue

        if d.dish_id == rubs_marker_id:
            past_rubs = True
            continue

        # Sauce/rub items
        if d.category == "SIGNATURE SAUCES":
            sauce_seq += 1
            result.append({
                "sauce_id": f"{sauce_seq:03d}",
                "category": "SIGNATURE RUBS" if past_rubs else "SIGNATURE SAUCES",
                "sauce_name": d.dish_name,
            })
            continue

        # Regular dish
        dish_seq += 1
        entry: dict = {
            "dish_id": f"{dish_seq:03d}",
            "category": d.category,
        }
        if d.subcategory:
            entry["subcategory"] = d.subcategory
        entry["dish_name"] = d.dish_name
        entry["price"] = d.price
        entry["description"] = d.description
        result.append(entry)

    return result


def main(pdf_path: str, out_path: str = "output/menu.json") -> None:
    pdf = Path(pdf_path)
    if not pdf.exists():
        sys.exit(f"PDF not found: {pdf}")

    lines = extract_lines_with_fonts(pdf)
    headers = find_header_indices(lines)
    dishes = parse_dishes(lines, headers)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    output = postprocess_output(dishes)
    n_dishes = sum(1 for o in output if "dish_id" in o)
    n_sauces = sum(1 for o in output if "sauce_id" in o)
    out.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"✓ Extracted {n_dishes} dishes + {n_sauces} sauces → {out}")
    print(f"  (detected {len(headers)} section headers by font size)")


if __name__ == "__main__":
    pdf_arg = sys.argv[1] if len(sys.argv) > 1 else "espn_bet.pdf"
    out_arg = sys.argv[2] if len(sys.argv) > 2 else "output/menu.json"
    main(pdf_arg, out_arg)
