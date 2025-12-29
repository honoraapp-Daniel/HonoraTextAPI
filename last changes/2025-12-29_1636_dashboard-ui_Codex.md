# Change title
Dashboard UI for /process_book

## Intent
Provide a simple dark dashboard to upload a PDF and run the full pipeline via /process_book, with visible progress and step status on the Railway domain.

## Method
Added a dashboard route in app/main.py serving a new static page. Built app/static/dashboard.html with glassy dark styling, file upload form, optimistic progress bar, step tracker tied to steps_completed from the API response, and result summary display. The page posts directly to /process_book on the same host.

## Reason
Developer requested a basic UI to launch the auto pipeline, track progress, and notify when finished.

## Files touched
- app/main.py
- app/static/dashboard.html
- last changes/2025-12-29_1636_dashboard-ui_Codex.md

## Tests
Not run (frontend/static change only).

## Agent signature
Codex
