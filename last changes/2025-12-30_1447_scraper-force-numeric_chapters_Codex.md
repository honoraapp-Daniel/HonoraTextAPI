# Change title
Scraper: force numeric chapter labels (convert words/roman)

## Intent
Ensure scraped chapters are always labeled with Arabic numerals; only word/roman numerals are converted, digits are preserved.

## Method
Refined cleanChapterTitle to parse chapter tokens: keep digits, convert word/roman to numbers via word map + romanToNumber, and preserve remainder as title. Updated cleanChapterContent matching to accept numeric/word/roman prefixes. Removed unused number-to-word logic.

## Reason
Chapters still appeared with word numerals; this forces numeric labels consistently.

## Files touched
- HonoraWebScraper/src/bookScraper.js
- last changes/2025-12-30_1447_scraper-force-numeric_chapters_Codex.md

## Tests
Not run (scraper logic change); verify on next scrape.

## Agent signature
Codex
