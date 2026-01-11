# Honora System Architecture Documentation
## Updated: 2026-01-11

This document describes the complete data flow through the Honora system, from web scraping to iOS playback.

---

## Systemet Oversigt

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              HONORA SYSTEM                                  │
├─────────────────┬─────────────────────────────┬─────────────────────────────┤
│  WEB SCRAPER    │        V3 PIPELINE          │         TTS MODULE          │
│  (Port 3001)    │        (Port 8000)          │         (Port 8001)         │
├─────────────────┼─────────────────────────────┼─────────────────────────────┤
│ 1. Crawl site   │ 4. Upload JSON/PDF          │ 7. Split sections → segments│
│ 2. Extract HTML │ 5. Gemini processing        │ 8. Generate audio per seg   │
│ 3. Save JSON    │ 6. Create paragraphs/secs   │ 9. Concat → audio_groups    │
│                 │    + Supabase upload        │ 10. Upload to Supabase      │
└─────────────────┴─────────────────────────────┴─────────────────────────────┘
```

---

## 1. WEB SCRAPER (`HonoraWebScraper/`)

### Server: `src/server.js` (Port 3001)

| Linje | Funktion | Beskrivelse |
|-------|----------|-------------|
| 1-9 | Import | Indlæser express, cors, cheerio, og interne moduler |
| 14-21 | App setup | Opretter Express server med CORS og statiske filer |
| 24-42 | Log management | Gemmer og læser logs fra `logs.json` |
| 44-77 | SSE Events | Sender real-time progress via Server-Sent Events |
| 107-114 | `GET /api/categories` | Henter alle kategorier fra sacred-texts.com |
| 116-131 | `GET /api/books` | Henter alle bøger i en kategori |
| 162-203 | `POST /api/download/book` | **HOVEDFUNKTION** - Scraper en bog |

### Book Scraper: `src/bookScraper.js`

| Linje | Funktion | Beskrivelse |
|-------|----------|-------------|
| 11-13 | `delay(ms)` | Venter X millisekunder (undgår rate-limiting) |
| 15-31 | `normalizeWhitespace(text)` | Fjerner overskydende newlines, max 2 |
| 33-71 | `fetchUrl(url)` | Henter URL med retry-logik for 429 errors |
| 75-98 | `romanToNumber(roman)` | Konverterer romertal til arabiske tal |
| 99-156 | PREFATORY_TITLES | Liste over "Chapter 0" titler (introduction, preface, etc.) |
| 183-219 | `getContentType(title)` | Returnerer 'prefatory', 'chapter', 'book', 'appendix', 'treatise' |
| 230-291 | `cleanChapterTitle(rawTitle, index)` | Renser "Chapter I. Salaam" → "Chapter One - Salaam" |
| 293-322 | `cleanChapterContent(content, title)` | Fjerner duplikerede headers fra indhold |
| 324-498 | `getBookChapters(bookIndexUrl)` | **KRITISK** - Finder alle kapitler fra index-side. Returnerer `{chapters, parts, treatises}` |
| 556-694 | `fetchChapterContent(chapterUrl)` | Henter og renser kapitelindhold fra HTML |
| 696-1325 | `scrapeFullBook(bookUrl, progressCallback)` | **HOVEDFUNKTION** - Scraper hele bogen |

### scrapeFullBook Flow:

1. **Hent index-side** → Parse alle kapitel-links
2. **Loop gennem kapitler** → Hent HTML for hvert kapitel
3. **Parse indhold** → Brug cheerio til at finde `<p>`, `<h2>`, etc.
4. **Fjern navigation** → Skip "Next", "Previous", footnote-links
5. **Byg JSON** → Struktur med: `{ title, author, chapters: [...], book_nodes: [...] }`
6. **Return** → JSON-data + HTML til PDF

### Output JSON Format:

```json
{
  "title": "The Kybalion",
  "author": "Three Initiates",
  "sourceUrl": "https://sacred-texts.com/eso/kyb/index.htm",
  "chapterCount": 15,
  "chapters": [
    {
      "index": 0,
      "title": "Chapter 0 - Introduction",
      "content": "The full chapter text...",
      "content_type": "prefatory"
    },
    {
      "index": 1,
      "title": "Chapter One - The Principle of Mentalism",
      "content": "..."
    }
  ],
  "book_nodes": [
    {
      "node_type": "chapter",
      "source_title": "Chapter One - The Princip...",
      "display_title": "The Principle of Mentalism",
      "chapter_index": 1,
      "order_key": "0001"
    }
  ]
}
```

---

## 2. V3 PIPELINE (`app/pipeline_v3.py`)

### Tilgængelig via: `http://localhost:8000/v3`

| Linje | Funktion | Beskrivelse |
|-------|----------|-------------|
| 34-64 | `clean_display_title(title)` | Fjerner "Chapter X -" prefix fra titler |
| 67-114 | `load_mapping_file(json_file_path)` | Læser `_mapping.json` eller embedded mapping |
| 117-176 | `apply_mapping_to_chapters(chapters, mapping)` | Applicerer manuelle overrides fra Mapping Editor |
| 187-193 | `get_v3_job_state(job_id)` | Læser job-state fra disk |
| 196-200 | `save_v3_job_state(job_id, state)` | Gemmer job-state til disk |
| 203-225 | `create_v3_job(file_path, file_type)` | Opretter nyt job med UUID |
| 228-268 | `update_v3_job_metadata(job_id, updates)` | Opdaterer metadata (titel, forfatter, synopsis) |

### Phase 1: Chapter Extraction

| Linje | Funktion | Beskrivelse |
|-------|----------|-------------|
| 275-430 | `v3_extract_chapters(job_id)` | **KRITISK** - Ekstraher kapitler fra JSON/PDF |
| 293-349 | JSON mode | Læser `chapters` array fra JSON, checker både `content` AND `text` keys |
| 351-387 | PDF mode | Bruger Marker API til PDF → Markdown konvertering |
| 389-400 | Apply mapping | Læser `manual_mapping` og overskriver titles/types |

### Phase 2: Gemini Processing

| Linje | Funktion | Beskrivelse |
|-------|----------|-------------|
| 441-511 | `v3_process_chapters(job_id)` | **KRITISK** - Kører alle kapitler gennem Gemini |
| 458-485 | Batch processing | Hver 5 kapitler "refreshes" Gemini context |
| 471-485 | Per-chapter | Kalder `process_full_chapter()` for paragraphs + sections |

### Phase 3: Metadata & Cover Art

| Linje | Funktion | Beskrivelse |
|-------|----------|-------------|
| 519-595 | `v3_generate_metadata_and_cover(job_id)` | Genererer synopsis, category og cover art |
| 535-560 | Gemini | Bruger Gemini til at generere synopsis fra kapitelindhold |
| 565-590 | Nano Banana | Genererer cover art via Nano Banana API |

### Phase 4: TTS Audio Generation

| Linje | Funktion | Beskrivelse |
|-------|----------|-------------|
| 602-768 | `v3_generate_tts_audio(job_id, engine, voice)` | **TTS-First v3.1** - Genererer audio |
| 630-650 | Segment processing | Merger korte sections, splitter lange |
| 655-700 | Audio generation | Genererer audio per segment via RunPod/Local |
| 705-750 | Grouping | Grupperer segments til ~35 sekunder audio_groups |
| 755-765 | Concat | Sammensætter audio_groups til M4A filer |

### Phase 5: Supabase Upload

| Linje | Funktion | Beskrivelse |
|-------|----------|-------------|
| 771-869 | `v3_upload_audio_to_supabase(job_id)` | Uploader alt til Supabase |
| 790-810 | Create build | Opretter `chapter_build` med atomic `canonical_version` |
| 815-840 | Upload groups | Uploader `audio_groups` og `tts_segments` |
| 845-865 | Create spans | Opretter `paragraph_spans` for O(1) iOS rendering |

---

## 3. GEMINI PROCESSOR (`app/glm_processor.py`)

| Linje | Funktion | Beskrivelse |
|-------|----------|-------------|
| 22-31 | `get_gemini_model()` | Lazy-initialiserer Gemini client |
| 140-150 | `call_gemini(prompt)` | Sender prompt til Gemini API |
| 158-187 | `is_heading_or_special(text)` | Checker om tekst er overskrift (tilladt at være kort) |
| 190-250 | `validate_and_merge_paragraphs(paragraphs)` | Merger korte paragraphs (<20 ord) |
| 253-308 | `process_chapter_paragraphs(text, title)` | **KRITISK** - Opretter paragraphs med Gemini |
| 311-355 | `process_chapter_sections(text)` | Opretter TTS sections (250-300 chars) |
| 381-406 | `process_full_chapter(title, text)` | **HOVEDFUNKTION** - Kombinerer paragraphs + sections |

### Paragraph Prompt (linje 280-300):

```
Du er en tekstformateringsassistent. Del følgende tekst i naturlige afsnit...
- Bevar PRÆCIS den originale tekst
- Indsæt kun [PARAGRAPH] tags
- Ingen ændringer i indholdet
```

### Section Prompt (linje 330-345):

```
Du er en TTS-formateringsassistent. Del teksten i sektioner på 250-300 tegn...
- Break ved sætningslut
- Indsæt [SECTION] tags
```

---

## 4. AUDIO SEGMENTS (`app/audio_segments.py`)

### TTS-First v3.1 Arkitektur

| Linje | Funktion | Beskrivelse |
|-------|----------|-------------|
| 35-41 | `normalize_text(text)` | NFKC normalization for text_normalized |
| 44-74 | `create_chapter_build(chapter_id, segments)` | Opretter `chapter_build` via Supabase RPC |
| 81-108 | `merge_short_segments(sections)` | Merger sections < 60 chars |
| 111-146 | `split_at_sentences(text, max_chars)` | Splitter ved sætningsslut |
| 149-164 | `clamp_long_segments(merged)` | Splitter sections > 420 chars |
| 167-184 | `process_segments(raw_sections)` | **HOVEDFUNKTION** - Full segment pipeline |
| 191-213 | `get_audio_duration_ms(audio_path)` | Læser duration via ffprobe |
| 220-267 | `group_segments(segments)` | Grupperer til ~35 sek audio_groups |
| 274-325 | `concat_group_audio(group, output_dir)` | Konkatenerer segment-audio til M4A |
| 332-359 | `upload_group_audio(local_path, chapter_id, group_index)` | Uploader til Supabase Storage |
| 362-417 | `save_groups_to_supabase(chapter_id, build_id, groups)` | Gemmer audio_groups + tts_segments |
| 420-437 | `update_chapter_audio_version(chapter_id, build_id)` | Sætter `audio_version = "v2"` |
| 440-509 | `generate_paragraph_spans(chapter_id, build_id, paragraphs, segments)` | Opretter paragraph → segment mapping |

### Segment Processing Flow:

```
Raw Sections ["text1", "text2", ...]
    ↓
merge_short_segments()  → Merger < 60 chars
    ↓
clamp_long_segments()   → Splitter > 420 chars
    ↓
Assign segment_index    → 0, 1, 2, ...
    ↓
Add text_normalized     → NFKC + collapse whitespace
    ↓
Final Segments [{index, text, text_normalized, duration_ms}, ...]
```

### Audio Grouping Flow:

```
Segments med duration_ms
    ↓
group_segments()        → Target ~35 sekunder per gruppe
    ↓
concat_group_audio()    → FFmpeg decode → concat → AAC encode
    ↓
upload_group_audio()    → Supabase Storage bucket
    ↓
save_groups_to_supabase()  → audio_groups + tts_segments tables
```

---

## 5. SUPABASE DATA MODEL

### Tabeller:

| Tabel | Formål |
|-------|--------|
| `books` | Bog metadata (title, author, cover_art_url) |
| `chapters` | Kapitler (book_id, chapter_index, title) |
| `paragraphs` | Display paragraphs (chapter_id, paragraph_index, text) |
| `sections` | Legacy TTS chunks (deprecated, erstattet af tts_segments) |
| `chapter_builds` | TTS builds med `canonical_version` |
| `tts_segments` | Audio segments (build_id, segment_index, text, text_normalized) |
| `audio_groups` | Concatenated audio (~35 sek) med `start_time_ms` |
| `paragraph_spans` | Links paragraph → segment range (start_segment, end_segment) |

### TTS-First v3.1 RPC Functions:

| RPC | Formål |
|-----|--------|
| `create_chapter_build(chapter_id, canonical_text)` | Atomic build creation med version |
| `get_chapter_with_spans(chapter_id)` | Return alt til iOS: paragraphs, segments, spans, groups |

---

## 6. FEJLFINDING

### Common Errors:

| Fejl | Årsag | Løsning |
|------|-------|---------|
| `Missing required configuration` | `.env` ikke loaded | Check at `load_dotenv()` kaldes i `config.py` |
| `chapters = 0` i JSON | Bruger kun `content` key | Nu checker vi både `content` OG `text` |
| `NoneType has no attribute 'split'` | Gemini returnerer None | Check API key og retry logic |
| `429 Too Many Requests` | Rate limiting | Scraper har retry-logik med exponential backoff |
| `cover art generation failed` | Nano Banana limit | Fortsætter uden cover art (optional) |

### Debug Logs:

- Web Scraper: `HonoraWebScraper/logs.json`
- V3 Pipeline: Terminal output + `data/v3_jobs/{job_id}.json`
- TTS Dashboard: Terminal output

---

## 7. PORT OVERSIGT

| Port | Service | Start Kommando |
|------|---------|----------------|
| 3001 | Web Scraper | `node HonoraWebScraper/src/server.js` |
| 8000 | V3 Pipeline API | `python3 -m uvicorn app.main:app --reload` |
| 8001 | TTS Dashboard | `python3 tts_dashboard.py` |

---

*Sidst opdateret: 2026-01-11*
