# Kapitel-for-Kapitel Pipeline - Implementation Plan

> **Version:** 1.0  
> **Dato:** 2025-12-30  
> **Projekt:** HonoraTextAPI  
> **Status:** 🔶 AFVENTER GODKENDELSE

## 📋 Oversigt

Denne plan beskriver en komplet omstrukturering af PDF-pipeline til en **kapitel-for-kapitel** arkitektur med:
- **Marker API** til PDF extraction
- **Nano Banana** til cover art
- **To outputs:** Sections (TTS) + Paragraphs (time sync)
- **Dashboard** med editing og re-processing

---

## 🎯 Mål

1. **Konsistens:** Samme resultat uanset PDF-formatering
2. **Fejlfri:** Validering på hvert trin, mulighed for re-processing
3. **Brugervenlig:** Dashboard med live preview og redigering
4. **Skalerbar:** Kapitel-for-kapitel = bedre fejlhåndtering

---

## 🏗️ Ny Arkitektur

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DASHBOARD VIEW                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  [UPLOAD PDF]                                                       │
│       ↓                                                             │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ METADATA PREVIEW                                            │   │
│  │ ┌─────────┐  Titel: The Kybalion                            │   │
│  │ │ Cover   │  Forfatter: Three Initiates                     │   │
│  │ │ Art     │  Sprog: English                                 │   │
│  │ │ Preview │  Kategori: Spirituality                         │   │
│  │ └─────────┘  Synopsis: "An exploration of..."               │   │
│  │                                            [✓ Godkend]      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│       ↓                                                             │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ KAPITLER (15 fundet)                          [Godkend Alle]│   │
│  │ ┌─────────────────────────────────────────────────────────┐ │   │
│  │ │ ☑ Kapitel 1: The Hermetic Philosophy      [✓] [↻] [✎]  │ │   │
│  │ │   → 45 sections, 32 paragraphs                          │ │   │
│  │ │   Preview: "The lips of wisdom are closed..."           │ │   │
│  │ ├─────────────────────────────────────────────────────────┤ │   │
│  │ │ ☑ Kapitel 2: The Seven Hermetic Principles [✓] [↻] [✎]  │ │   │
│  │ │   → 52 sections, 38 paragraphs                          │ │   │
│  │ ├─────────────────────────────────────────────────────────┤ │   │
│  │ │ ⏳ Kapitel 3: Mental Transmutation          [Processing] │ │   │
│  │ └─────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────┘   │
│       ↓                                                             │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  ENDELIG GODKENDELSE                                        │   │
│  │  ✓ Metadata komplet      ✓ 15/15 kapitler godkendt         │   │
│  │  ✓ Cover art genereret   ✓ 967 sections, 661 paragraphs    │   │
│  │                                                             │   │
│  │             [ 🚀 UPLOAD TIL SUPABASE ]                      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Database Schema Ændringer

### Ny tabel: `processing_jobs`
```sql
CREATE TABLE processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Status
    status TEXT DEFAULT 'pending', -- pending, extracting, metadata, chapters, processing, complete, failed
    current_phase TEXT,
    current_chapter INT,
    total_chapters INT,
    
    -- Temporary data (før upload)
    pdf_file_path TEXT,
    markdown_text TEXT,
    metadata JSONB,          -- {title, author, synopsis, category, ...}
    cover_art_urls JSONB,    -- {url_1x1, url_16x9}
    chapters JSONB,          -- [{index, title, start_line, end_line, status, sections, paragraphs}]
    
    -- Error tracking
    error_message TEXT,
    error_chapter INT
);
```

### Ny tabel: `chapter_previews`
```sql
CREATE TABLE chapter_previews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES processing_jobs(id) ON DELETE CASCADE,
    chapter_index INT,
    
    -- Content
    title TEXT,
    raw_text TEXT,           -- Fra Marker
    cleaned_text TEXT,       -- Efter GPT cleaning
    
    -- Outputs (editable)
    sections JSONB,          -- [{index, text}]
    paragraphs JSONB,        -- [{index, text}]
    
    -- Status
    status TEXT DEFAULT 'pending', -- pending, processing, ready, approved, rejected
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 📁 Nye Filer / Ændringer

### Ny fil: `app/marker.py`
Marker API integration til PDF → Markdown

```python
"""
Marker API integration for PDF to Markdown conversion.
Uses Datalab.to API for high-quality PDF extraction.
"""
import os
import requests
import time

MARKER_API_URL = "https://www.datalab.to/api/v1/marker"

def extract_pdf_to_markdown(pdf_path: str) -> dict:
    """
    Converts PDF to structured Markdown using Marker API.
    
    Returns:
        {
            "markdown": "# Chapter 1\n\nThe text...",
            "metadata": {"pages": 119, ...},
            "images": {...}
        }
    """
    api_key = os.getenv("DATALAB_API_KEY")
    if not api_key:
        raise RuntimeError("DATALAB_API_KEY must be set")
    
    # Upload PDF and get markdown
    with open(pdf_path, "rb") as f:
        response = requests.post(
            MARKER_API_URL,
            headers={"X-Api-Key": api_key},
            files={"file": f},
            data={"output_format": "markdown"}
        )
    
    if response.status_code != 200:
        raise Exception(f"Marker API error: {response.text}")
    
    return response.json()
```

---

### Ny fil: `app/pipeline_v2.py`
Kapitel-for-kapitel pipeline logik

```python
"""
Version 2 Pipeline: Chapter-by-chapter processing with preview/approval.
"""

# Phase 1: Extract PDF
async def phase_extract_pdf(job_id: str, pdf_path: str):
    """Extract PDF to Markdown using Marker API."""
    pass

# Phase 2: Extract Metadata + Cover Art
async def phase_metadata(job_id: str):
    """Extract metadata with GPT and generate cover art with Nano Banana."""
    pass

# Phase 3: Detect Chapters
async def phase_detect_chapters(job_id: str):
    """Use GPT to detect chapter boundaries from Markdown headers."""
    pass

# Phase 4: Process Single Chapter
async def phase_process_chapter(job_id: str, chapter_index: int):
    """
    Process one chapter:
    1. Extract text from markdown
    2. Clean with GPT
    3. Create sections (max 250 chars for TTS)
    4. Create paragraphs (natural flow for time sync)
    """
    pass

# Phase 5: Commit to Supabase
async def phase_commit_to_supabase(job_id: str):
    """Upload approved preview data to production tables."""
    pass
```

---

### Modificeret: `app/main.py`
Nye API endpoints

```python
# ============================================
# PIPELINE V2 ENDPOINTS (Chapter-by-Chapter)
# ============================================

@app.post("/v2/upload")
async def v2_upload_pdf(file: UploadFile):
    """
    Start new processing job.
    Returns job_id for tracking.
    """
    pass

@app.get("/v2/job/{job_id}")
async def v2_get_job_status(job_id: str):
    """
    Get full job status including:
    - Current phase
    - Metadata preview
    - Chapter list with status
    """
    pass

@app.post("/v2/job/{job_id}/approve-metadata")
async def v2_approve_metadata(job_id: str):
    """Approve metadata and start chapter detection."""
    pass

@app.post("/v2/job/{job_id}/process-chapter/{chapter_index}")
async def v2_process_chapter(job_id: str, chapter_index: int):
    """Process a single chapter."""
    pass

@app.post("/v2/job/{job_id}/reprocess-chapter/{chapter_index}")
async def v2_reprocess_chapter(job_id: str, chapter_index: int):
    """Re-process a chapter that had errors."""
    pass

@app.put("/v2/job/{job_id}/chapter/{chapter_index}")
async def v2_edit_chapter(job_id: str, chapter_index: int, payload: dict):
    """
    Edit chapter content manually.
    payload: {sections: [...], paragraphs: [...]}
    """
    pass

@app.post("/v2/job/{job_id}/approve-chapter/{chapter_index}")
async def v2_approve_chapter(job_id: str, chapter_index: int):
    """Approve a processed chapter."""
    pass

@app.post("/v2/job/{job_id}/commit")
async def v2_commit_to_supabase(job_id: str):
    """Final commit: Upload all approved data to Supabase."""
    pass
```

---

### Modificeret: `app/static/dashboard.html`
Ny dashboard UI

**Hovedsektioner:**
1. **Upload sektion** - Drag & drop PDF
2. **Metadata preview** - Redigerbar metadata + cover art
3. **Kapitel liste** - Status, preview, approve/reject/edit buttons
4. **Kapitel editor** - Modal til redigering af sections/paragraphs
5. **Final upload** - Commit knap når alt er godkendt

---

## 🔄 Processing Flow

### Trin 1: Upload PDF
```
User → Upload PDF → Marker API → Markdown output → Gem i processing_jobs
```

### Trin 2: Metadata Extraction
```
Markdown (første 10%) → GPT-4o → {title, author, synopsis, category}
                       ↓
               Nano Banana → Cover art (16:9 → crop)
                       ↓
               Vis i dashboard → User godkender
```

### Trin 3: Kapitel Detection
```
Markdown headers → GPT-4o → [{index, title, start_line, end_line}]
                          ↓
                  Vis liste i dashboard
```

### Trin 4: Kapitel Processing (for hvert kapitel)
```
Kapitel tekst → GPT-4o-mini (cleaning) → Renset tekst
                                        ↓
                        GPT-4o-mini (sections) → Max 250 chars chunks
                                        ↓
                        GPT-4o-mini (paragraphs) → Natural flow
                                        ↓
                        Gem i chapter_previews
                                        ↓
                        Vis preview i dashboard
                                        ↓
                        User: Godkend / Afvis / Rediger
```

### Trin 5: Commit
```
Alle kapitler godkendt → [UPLOAD] knap
                                ↓
                        Create book record
                        Create chapters
                        Create sections (fra preview)
                        Create paragraphs (fra preview)
                        Upload cover art
                                ↓
                        ✅ Færdig!
```

---

## 📐 Sections vs Paragraphs Logic

### Sections (for TTS - max 250 chars)
```python
def create_tts_sections(text: str) -> list[str]:
    """
    Split text into TTS-optimal chunks:
    - Max 250 characters
    - Split at sentence boundaries (.)
    - Never break mid-sentence
    - Section 0 = Chapter title
    """
    sections = []
    
    # Section 0: Title
    title, remaining = extract_chapter_header(text)
    if title:
        sections.append(title)
    
    # Split remaining by sentences
    sentences = split_into_sentences(remaining)
    
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= 250:
            current = (current + " " + sentence).strip()
        else:
            if current:
                sections.append(current)
            current = sentence
    
    if current:
        sections.append(current)
    
    return sections
```

### Paragraphs (for time sync - natural flow)
```python
def create_display_paragraphs(text: str) -> list[str]:
    """
    Split text into natural paragraphs:
    - 150-350 characters (mobile optimal)
    - Semantic boundaries (topic changes)
    - Respect existing paragraph breaks
    - GPT-assisted splitting
    """
    # Use existing split_into_paragraphs_gpt()
    return split_into_paragraphs_gpt(text)
```

---

## 🖥️ Dashboard UI Features

### 1. Progress Tracking
- Real-time status updates via SSE eller polling
- Progress bar for overall job
- Per-chapter status indicators

### 2. Chapter Preview Card
```
┌─────────────────────────────────────────────────────────────────┐
│ Kapitel 3: Mental Transmutation                      ✓ Godkendt│
├─────────────────────────────────────────────────────────────────┤
│ Sections: 45  │  Paragraphs: 32  │  Chars: 12,450              │
├─────────────────────────────────────────────────────────────────┤
│ Preview:                                                        │
│ "Mind (as well as metals and elements) may be transmuted,      │
│ from state to state; degree to degree; condition to            │
│ condition; pole to pole; vibration to vibration."              │
├─────────────────────────────────────────────────────────────────┤
│ [👁️ Vis Sections] [👁️ Vis Paragraphs] [✎ Rediger] [↻ Generer] │
└─────────────────────────────────────────────────────────────────┘
```

### 3. Edit Modal
```
┌─────────────────────────────────────────────────────────────────┐
│ Rediger Kapitel 3: Mental Transmutation            [X] Luk     │
├─────────────────────────────────────────────────────────────────┤
│ ┌───────────────────────────────────────────────────────────┐  │
│ │ SECTIONS (TTS)                                     [+ Ny] │  │
│ │ ┌─────────────────────────────────────────────────────┐   │  │
│ │ │ 0: Chapter Three. Mental Transmutation.            │   │  │
│ │ │    [chars: 42]                           [✎] [🗑️]  │   │  │
│ │ ├─────────────────────────────────────────────────────┤   │  │
│ │ │ 1: Mind as well as metals and elements may be...   │   │  │
│ │ │    [chars: 187]                          [✎] [🗑️]  │   │  │
│ │ └─────────────────────────────────────────────────────┘   │  │
│ └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│ ┌───────────────────────────────────────────────────────────┐  │
│ │ PARAGRAPHS (Display)                               [+ Ny] │  │
│ │ ┌─────────────────────────────────────────────────────┐   │  │
│ │ │ 0: Chapter Three. Mental Transmutation.            │   │  │
│ │ │    [chars: 42]                           [✎] [🗑️]  │   │  │
│ │ └─────────────────────────────────────────────────────┘   │  │
│ └───────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                    [Annuller]  [💾 Gem Ændringer]               │
└─────────────────────────────────────────────────────────────────┘
```

---

## ⚙️ Environment Variables

Nye variabler der skal tilføjes:

```env
# Marker API (Datalab)
DATALAB_API_KEY=your_datalab_api_key

# Eksisterende (uændret)
OPENAI_API_KEY=...
KIE_API_KEY=...
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
```

---

## 📋 Implementation Rækkefølge

### Fase 1: Backend Foundation (2-3 timer)
1. [ ] Opret `processing_jobs` og `chapter_previews` tabeller i Supabase
2. [ ] Opret `app/marker.py` med Datalab API integration
3. [ ] Opret `app/pipeline_v2.py` med grundstruktur

### Fase 2: Core Pipeline (3-4 timer)
4. [ ] Implementer `phase_extract_pdf()` - Marker integration
5. [ ] Implementer `phase_metadata()` - GPT + Nano Banana
6. [ ] Implementer `phase_detect_chapters()` - Kapitel detection
7. [ ] Implementer `phase_process_chapter()` - Sections + Paragraphs
8. [ ] Implementer `phase_commit_to_supabase()` - Final upload

### Fase 3: API Endpoints (2 timer)
9. [ ] Tilføj alle `/v2/` endpoints til `main.py`
10. [ ] Test endpoints med Swagger UI

### Fase 4: Dashboard UI (3-4 timer)
11. [ ] Redesign `dashboard.html` med ny struktur
12. [ ] Implementer upload + metadata preview
13. [ ] Implementer kapitel liste med status
14. [ ] Implementer kapitel editor modal
15. [ ] Implementer final commit flow

### Fase 5: Testing & Polish (1-2 timer)
16. [ ] Test med 2-3 forskellige PDF'er
17. [ ] Fix edge cases
18. [ ] Deploy til Railway

**Estimeret total tid: 11-15 timer**

---

## 🔒 Verification Plan

### Automated Tests
```bash
# Test Marker API
curl -X POST /v2/upload -F "file=@test.pdf"

# Test chapter processing
curl -X POST /v2/job/{id}/process-chapter/1

# Test commit
curl -X POST /v2/job/{id}/commit
```

### Manual Verification
1. Upload PDF → Check Markdown quality
2. Verify metadata extraction accuracy
3. Verify chapter splitting matches ToC
4. Check section lengths (all ≤ 250 chars)
5. Verify paragraphs follow natural flow
6. Test edit + save functionality
7. Test re-process functionality
8. Verify final Supabase data matches preview

---

## 💡 Fremtidige Udvidelser

1. **Batch processing** - Queue multiple PDFs
2. **Templates** - Save section/paragraph rules per genre
3. **AI tuning** - Feedback loop til at forbedre GPT prompts
4. **Audio preview** - Test TTS direkte i dashboard
5. **Diff view** - Vis ændringer ved re-processing

---

> **Næste skridt:** Godkend denne plan, så starter vi implementation af Fase 1.
