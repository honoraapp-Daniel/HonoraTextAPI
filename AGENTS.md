# AGENTS  Honora Book API

Purpose
- Keep agents aligned on Honora Book API work; read before every task to avoid miscommunication.

What Honora Book API Is
- Cloud FastAPI service on Railway powering the Honora audiobook pipeline.
- Converts uploaded PDFs into structured book data, cleaned text, and cover art; TTS/audio pipeline is upcoming.
- Pipeline steps: POST /extract_pdf -> /create_book -> /clean_book -> /extract_chapters -> /chunk_chapters -> /create_paragraphs -> /process_book (unified) -> (future /generate_audio merge/upload).
- Persists metadata, chapters, sections, and paragraphs to Supabase; uploads cover art (and future audio) to Supabase Storage.

Tech Stack
- FastAPI (Python) hosted on Railway.
- Supabase Postgres + Storage (books, chapters, sections, paragraphs, cover art, audio TBD).
- OpenAI GPT-4.1 for metadata + cleaning; DALL-E 3 for cover art.
- PyMuPDF for PDF extraction; Pillow for image post-processing (text overlay issue on Railway).
- Future TTS: ElevenLabs or Coqui XTTS plus audio merge.
- DB migrations live in docs/supabase-*-migration.sql.

Current Status (keep fresh)
- If this section is stale, update it as part of your change. Otherwise, read the latest status file in docs/ (e.g., project-status-YYYY-MM-DD.md) before proceeding.
- Latest known (2025-12-20): endpoints complete (/extract_pdf, /create_book, /clean_book, /extract_chapters, /chunk_chapters, /create_paragraphs, /process_book), metadata fields live, cover art works but text overlay fails on Railway fonts, pipeline tested on The Kybalion (119 pages: 15 chapters, 967 sections, 661 paragraphs, ~8 minutes), pending TTS audio endpoint/merge/upload, timestamps, custom voice training, and long-book timeout handling.

Do-Not-Touch (needs explicit approval)
- Supabase production schema/data, service keys, storage buckets.
- Railway environment variables, deployment settings, dependency upgrades (requirements.txt).
- Destructive changes in HonoraWebScraper_Kopi/ or other unrelated folders; do not revert user changes.

Core Rules
- Every change must be explained (intent, method, reason) so the other agent can follow.
- Read this file before work; if unclear, ask the developer.
- Check the latest entry in last changes/ to see recent modifications by other agents or models.
- State snapshot first (template below); if anything is missing, stop and ask.
- Plan -> change -> test -> fix loop.
- Developer decides; ask when uncertain.
- Push to GitHub after every change and state when it is done; if blocked, inform the developer immediately.
- Respect Do-Not-Touch items.

State Snapshot Template
- AGENTS.md read: yes (YYYY-MM-DD HH:MM)
- Working tree status: clean/dirty
- Open files: ...
- Intent: ...
- Risks/dependencies: ...

Walkthroughs (mandatory)
- After each change, add a file under last changes/.
- Include: Change title, Intent, Method, Reason, Files touched, Tests (ran?/why not), Agent signature (Codex or Claude).
- Filename: YYYY-MM-DD_HHMM_<short-title>_<agent>.md.

Conflict Handling
- If there is any conflict or unexpected change in the same file, stop and ask the developer.

Testing
- Developer usually runs tests; agent must report whether tests were run and why/why not.

Git Discipline
- Commit when needed to preserve work, but always push the changes to GitHub after each change (default branch unless otherwise specified) and announce completion. No shortcut command defined for this repo.

References
- docs/system-architecture-2025-12-14.md (flows, env vars).
- docs/project-status-2025-12-20.md (status, issues, pending work).
