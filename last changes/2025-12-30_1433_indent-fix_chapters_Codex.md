# Change title
Fix indentation error in write_chapters_to_supabase

## Intent
Restore valid Python indentation to allow the API to start on Railway.

## Method
Corrected the insert_data block indentation inside write_chapters_to_supabase in app/chapters.py so it aligns with the loop.

## Reason
Railway crashed with `IndentationError: unexpected indent` at line ~572 in app/chapters.py.

## Files touched
- app/chapters.py
- last changes/2025-12-30_1433_indent-fix_chapters_Codex.md

## Tests
Not run (syntax-only fix). Expect app to start cleanly.

## Agent signature
Codex
