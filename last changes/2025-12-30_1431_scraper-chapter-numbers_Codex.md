# Change title
Scraper: use numeric chapter titles

## Intent
Make scraped chapter titles use Arabic numerals (1, 2, 3) instead of word numerals to align with downstream pipeline/UI expectations.

## Method
Updated HonoraWebScraper/src/bookScraper.js `cleanChapterTitle` to format titles as `Chapter <number> - <title>` (numeric index) rather than word numbers. Adjusted matching in `cleanChapterContent` to look for numeric chapter headers.

## Reason
Pipeline/UI showed inconsistent chapter numbering; scraper should emit numeric chapter labels to reduce misalignment.

## Files touched
- HonoraWebScraper/src/bookScraper.js
- last changes/2025-12-30_1431_scraper-chapter-numbers_Codex.md

## Tests
Not run (scraper/front-end change); verify on next scrape run.

## Agent signature
Codex
