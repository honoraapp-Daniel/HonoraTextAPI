# Change title
Normalize chapter display titles to Arabic numerals

## Intent
Ensure chapter titles use numeric labels (1, 2, 3…) for display while keeping original titles for matching, reducing misnumbering issues in the pipeline/UI.

## Method
Added a normalize_chapter_title helper in extract_chapters_smart to convert word/roman numerals to Arabic and format as "Chapter N: Title"; stored as display_title while preserving the original title for text extraction. Updated chapter objects and Supabase writes to use display_title for the stored title.

## Reason
Chapter numbering appeared inconsistent (roman/word forms). Normalizing to Arabic numerals improves clarity without risking text matching.

## Files touched
- app/chapters.py
- last changes/2025-12-30_1426_chapter-title-normalization_Codex.md

## Tests
Not run (logic/scalar change); validate on next pipeline run and UI.

## Agent signature
Codex
