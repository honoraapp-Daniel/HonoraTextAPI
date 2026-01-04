# V3 Pipeline - Honora Text API

## Oversigt

V3 Pipeline er den nyeste version af Honoras bogprocesseringssystem. Den bruger **Gemini 2.0 Flash** til al tekstbehandling og **Imagen 4.0** til cover art generering.

### Hvad V3 gør

1. **Upload** → Modtager PDF eller JSON fil fra scraperen
2. **Extract** → Ekstraherer kapitler fra filen
3. **Process** → Gemini opretter paragraphs og sections per kapitel
4. **Generate** → Gemini genererer metadata, synopsis, quote + Imagen laver cover art
5. **Upload** → Alt uploades til Supabase med korrekte relationer

---

## Arkitektur

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Upload    │────▶│   Extract   │────▶│   Process   │
│  PDF/JSON   │     │  Chapters   │     │  Gemini AI  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                    ┌─────────────┐     ┌──────▼──────┐
                    │   Upload    │◀────│  Generate   │
                    │  Supabase   │     │ Cover+Meta  │
                    └─────────────┘     └─────────────┘
```

---

## Filer

| Fil | Beskrivelse |
|-----|-------------|
| `app/pipeline_v3.py` | Hovedpipeline med alle faser |
| `app/glm_processor.py` | Gemini prompts for paragraphs/sections |
| `app/cover_art.py` | Nano Banana cover art generering |
| `app/metadata.py` | Metadata ekstraktion med Gemini |
| `templates/v3_dashboard.html` | Web dashboard UI |

---

## Sådan starter du V3

### 1. Start API serveren

```bash
cd /Users/cuwatyarecords/Desktop/HonoraTextAPI
export $(cat .env | xargs)
python3 -m uvicorn app.main:app --reload --port 8000
```

### 2. Åbn Dashboard

Gå til: **http://localhost:8000/v3**

### 3. Workflow

1. **Upload** en JSON-fil fra scraperen (eller PDF)
2. Tryk **"▶️ Run Pipeline"**
3. Vent på processing (se progress)
4. Gennemse metadata og cover art
5. Tryk **"📤 Upload to Supabase"**

---

## API Endpoints

| Endpoint | Metode | Beskrivelse |
|----------|--------|-------------|
| `/v3` | GET | Dashboard UI |
| `/v3/upload` | POST | Upload fil og opret job |
| `/v3/run/{job_id}` | POST | Kør pipeline |
| `/v3/status/{job_id}` | GET | Hent job status |
| `/v3/job/{job_id}` | GET | Hent fuld job data |
| `/v3/upload-supabase/{job_id}` | POST | Upload til Supabase |

---

## Metadata der genereres

| Felt | Kilde | Supabase Tabel |
|------|-------|----------------|
| title | JSON/PDF | books |
| author | Gemini | books + authors (M2M) |
| publishing_year | Gemini | books |
| publisher | Gemini | publishers (FK) |
| language | Gemini | languages (FK) |
| original_language | Gemini | languages (FK) |
| category | Gemini | categories (FK) |
| synopsis | Gemini | books |
| book_of_the_day_quote | Gemini | books |
| cover_art_url | Imagen | books |
| cover_art_url_16x9 | Imagen | books |

---

## Prompts

### Paragraph Prompt (STRENGE REGLER - v2.0)

**Regel 1: Paragraph 0 = Kapiteltitel**
- Paragraph 0 er ALTID kapitlets titel (f.eks. "I. Apprentice" eller "Chapter One: The Beginning")
- Bogens titel (f.eks. "Morals and Dogma") må ALDRIG være Paragraph 0

**Regel 2: Minimum ordantal**
- Normale paragraphs SKAL indeholde minimum **20-30 ord** (ca. 3-4 linjer)
- Enkeltlinjer som "It adds insolency to power." flettes automatisk sammen
- Undtagelser: Overskrifter, citater ("..."), digte, dialog

**Regel 3: Lister holdes sammen**
- A., B., C. lister → én paragraph
- 1., 2., 3. lister → én paragraph
- Undtagelse: Lister med 10+ punkter deles i 2

**Regel 4: Tal til ord**
- Konverterer alle tal til ord

**Regel 5: Fjern støj**
- Sidetal, filstørrelser, navigation, metadata

**Regel 6: Post-processing validering**
- Korte paragraphs flettes automatisk efter Gemini-output
- Output: `[PARAGRAPH]` markers

### Section Prompt (TTS)
- Maks 250-300 tegn per sektion
- Output: `[SECTION]` markers

### Batch Processing (Store Bøger)
- Hver **5. kapitel** refreshes Gemini-konteksten
- Forhindrer kvalitetsforringelse ved 35+ kapitler
- Automatisk statistik-logging per kapitel

### Cover Art Prompt
- Premium bogcover design
- Flat art med blurred background
- Titel og forfatter integreret i design

---

## Omkostning

**Per bog (20 kapitler):**
- Gemini: ~$0.012
- Imagen: ~$0.040
- **Total: ~$0.05 (~35 øre)**

---

## TODO - Næste skridt

### Højprioritet
- [ ] **Test med flere bøger** - Verificer stabilitet
- [ ] **Fejlhåndtering** - Bedre retry-logik ved API fejl
- [ ] **Batch processing** - Mulighed for at køre flere bøger
- [ ] **Progress tracking** - Bedre real-time feedback under processing

### Forbedringer
- [ ] **Cover art kvalitet** - Finjuster prompt hvis nødvendigt
- [ ] **Section længder** - Verificer alle sections er under 300 tegn
- [ ] **Publisher lookup** - Evt. manuel override i dashboard
- [ ] **PDF support** - Test Marker API integration

### Nye features
- [ ] **Auto-scraper integration** - Direkte fra scraper til V3
- [ ] **Kø-system** - Process flere bøger automatisk
- [ ] **TTS integration** - Direkte til audio generering

---

## Environment Variables

```bash
GEMINI_API_KEY=xxx          # Google Gemini API
SUPABASE_URL=xxx            # Supabase project URL
SUPABASE_SERVICE_ROLE_KEY=xxx  # Supabase admin key
MARKER_API_KEY=xxx          # PDF til markdown (datalab.to)
```

---

*Sidst opdateret: 3. januar 2026*
