# Change title
Scraper: preserve numeric chapter labels, convert only words/roman

## Intent
Ensure scraped chapter titles keep existing numbers; only words or roman numerals are converted to Arabic digits.

## Method
Updated cleanChapterTitle in HonoraWebScraper/src/bookScraper.js to parse the chapter number token: keep digits as-is, convert roman/word forms to numbers, and fall back to index. The remainder of the title is preserved.

## Reason
Scraper was still emitting word-based chapter numbers; requirement is to keep numeric labels unless source uses words/roman numerals.

## Files touched
- HonoraWebScraper/src/bookScraper.js
- last changes/2025-12-30_1438_scraper-keep-numeric-chapters_Codex.md

## Tests
Not run (scraper logic change); verify on next scrape.

## Agent signature
Codex
