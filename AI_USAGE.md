# AI Usage Reflection

## Tools used

- **GitHub Copilot (Claude)** — iterative code refinements and debugging.
- **ChatGPT (GPT-5)** — brainstorming column-splitting strategy and initial regex drafts.

Both tools were used as assistants; all architectural decisions and algorithm design were mine.

## My key contributions

1. **Statistical header detection** — replaced AI's hardcoded `KNOWN_SECTIONS` with font-size analysis via `Counter`. Most common size = body text; ALL-CAPS lines ≥1.5 pt larger = header. Makes the extractor generalizable to any menu PDF without manual config.

2. **Character-level PDF extraction** — `extract_text()` destroyed multi-column layout. I grouped `page.chars` by Y-coordinate (3 px tolerance) and split sub-columns at horizontal gaps >15 pt. Tested `extract_words()` first but it loses gap-size info needed for sub-column detection.

3. **Drink-list expansion** — `split_drink_items()` detects ≥2 `NAME $PRICE` patterns and emits each as a separate entry. Correctly expands DRAFT BEER (16), BOTTLES & CANS (12), WINES (5), COCKTAILS (8).

4. **Embedded sub-item truncation** — `_split_embedded_subitem()` detects lowercase→ALL-CAPS+$PRICE transitions in descriptions and truncates at the boundary.

5. **Regex engineering** — added `|X` for placeholder prices, `\(\)` for names like `RED BULL (WATERMELON)`, `\u2019` for curly apostrophes, non-greedy `*?` in `DRINK_ITEM_RE` to prevent over-matching.

6. **Sauce/chicken post-processing** — sauces and rubs output as `{sauce_id, category, sauce_name}` without price/description. Chicken section items get `subcategory` field assigned via side-by-side sub-column position alternation.

## Assumptions

Two-column PDF layout; headers use larger font (≥1.5 pt); dish names ALL-CAPS (≤60 chars); prices `$XX`/`$XX.XX`/`$X`.

## Edge cases handled

Price on separate line, multi-line descriptions, footer/legal noise filtering (`NOISE_RE`), side-by-side sub-columns, concatenated item lists, curly quotes, embedded sub-items, disclaimer contamination.

## Known gaps

- Mixed-case dish names missed (would need bold/font-weight analysis).
- Prices kept as strings for fidelity.

## Validation

Spot-checked all sections against PDF, confirmed category counts (16 draft beers, 12 bottles & cans, 5 wines), verified edge-case items. Final output: 90+ dishes + 15 sauces/rubs across 15+ categories.