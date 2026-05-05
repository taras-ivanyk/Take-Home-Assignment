# Menu PDF → JSON Extractor

Extracts dishes from a two-column restaurant menu PDF and outputs structured JSON.

Auto-detects section headers via font-size analysis (no hardcoded list) and splits concatenated drink/item lists (e.g. `MILLER LITE $X COORS LIGHT $X`) into individual entries.

## Requirements

- Python 3.12+
- See `requirements.txt`

## Install

```bash
# Create a virtual environment
python3 -m venv .venv               # on Windows: python -m venv .venv
source .venv/bin/activate           # on Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Run

```bash
python extract_menu.py path/to/menu.pdf output/menu.json
```

Default paths (if no arguments are provided):

- Input: `espn_bet.pdf`
- Output: `output/menu.json`

Example:

```bash
python extract_menu.py espn_bet.pdf output/menu.json
```

## How it works

1. **Character-level extraction** — each PDF page is split vertically in half, and characters are collected per column with their coordinates and font size (via `pdfplumber`).
2. **Line assembly** — characters are grouped into lines by their vertical position, sorted left-to-right, and joined into text using gap-based spacing heuristics. Large horizontal gaps are treated as sub-column breaks.
3. **Header detection** — the most common rounded font size is taken as the "body" size. Any ALL-CAPS line with a noticeably larger font and no price is flagged as a section header.
4. **Dish parsing (state machine)** — headers update the current category; ALL-CAPS lines start a new dish; everything else is appended to the current dish's description.
5. **Post-processing**:
   - descriptions that contain embedded sub-items are trimmed,
   - concatenated drink/item lists (e.g. `MILLER LITE $5 COORS $6`) are expanded into separate `Dish` entries under the parent name.
6. **Output** — a JSON array of dishes with `dish_id`, `category`, `dish_name`, `price`, and `description`.

## Output example

```json
{
  "dish_id": "001",
  "category": "BURGERS",
  "dish_name": "ALL AMERICAN BURGER",
  "price": "\$17",
  "description": "7 oz. steakburger, choice of cheese, lettuce, tomato, onion, pickles, brioche bun"
}
```

Items without a listed price have `"price": null`.

## Project structure

```
.
├── extract_menu.py       # main script
├── requirements.txt      # Python dependencies
├── README.md             # this file
├── AI_USAGE.md           # reflection on AI tool usage
├── next_steps.txt        # quick-start instructions
└── output/
    └── menu.json         # generated output
```

## Known gaps / next steps

- Dish-name detection relies on ALL-CAPS styling; items with mixed-case names would be missed. Could be improved with bold/font-weight analysis via `page.chars`.
- Header detection assumes headers are visibly larger than body text. Menus where all text is the same size would need an alternative heuristic.
- Prices are kept as strings (`"$17"`, `"$X"`) for fidelity; converting to numeric values would be a trivial post-processing step.
- The noise filter is tuned for this specific menu (footer keywords like "gratuity", "consuming raw", "espn"). Extend `NOISE_PATTERNS` for other menus.