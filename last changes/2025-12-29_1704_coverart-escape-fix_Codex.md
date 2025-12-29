# Change title
Fix cover_art syntax escape issue

## Intent
Resolve deployment SyntaxError from stray escaped f-strings in cover_art.py.

## Method
Cleaned print/log lines in app/cover_art.py to remove backslash escapes left in f-strings and strings, restoring valid Python syntax.

## Reason
Railway logs showed `SyntaxError: unexpected character after line continuation character` due to escaped quotes in cover_art.py introduced in preview-mode changes.

## Files touched
- app/cover_art.py
- last changes/2025-12-29_1704_coverart-escape-fix_Codex.md

## Tests
Not run (syntax-only fix); expect app to start cleanly.

## Agent signature
Codex
