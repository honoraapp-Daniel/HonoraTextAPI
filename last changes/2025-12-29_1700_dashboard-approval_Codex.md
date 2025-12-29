# Change title
Preview + approval flow before Supabase upload

## Intent
Let users preview pipeline output (metadata, cover art, sample sections/paragraphs) and explicitly approve before uploading to Supabase.

## Method
- Added preview endpoint (/process_book_preview) that runs the pipeline without Supabase writes, returns metadata, cover art preview, and samples. Added commit endpoint (/process_book_upload) to finalize to Supabase using saved preview data. Kept existing /process_book unchanged.
- Added optional upload flag to generate_cover_image so preview mode skips Supabase uploads.
- Updated dashboard to generate a preview first, show file info, metadata, cover art, first 10 sections/paragraphs, and enable “Upload to Supabase” only after approval; live status now includes preview and upload steps.

## Reason
Developer requested a manual approval gate before data is written to Supabase, with visibility into sections, paragraphs, metadata, and cover art URLs.

## Files touched
- app/main.py
- app/cover_art.py
- app/static/dashboard.html
- last changes/2025-12-29_1700_dashboard-approval_Codex.md

## Tests
Not run (API/frontend flow change; manual verification recommended on Railway with a PDF).

## Agent signature
Codex
