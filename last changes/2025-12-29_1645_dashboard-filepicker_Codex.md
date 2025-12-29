# Change title
Dashboard file picker feedback & gating

## Intent
Show which PDF is selected and gate the pipeline start button until a PDF is chosen.

## Method
Updated app/static/dashboard.html to display the selected file name and size, initialize the Start button as disabled, and enable it only when a PDF is selected. Added file change handler to update status text and file info. Submit handler now re-disables the button if no file remains selected after completion.

## Reason
User asked for visible confirmation of the uploaded PDF and to prevent starting the pipeline without a file.

## Files touched
- app/static/dashboard.html
- last changes/2025-12-29_1645_dashboard-filepicker_Codex.md

## Tests
Not run (frontend/static change only).

## Agent signature
Codex
