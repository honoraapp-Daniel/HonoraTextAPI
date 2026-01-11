# TTS Segment & Group Architecture v3.1

## 📚 Oversigt

Den nye segment/group arkitektur erstatter den gamle paragraph-baserede TTS med en mere effektiv og fleksibel løsning:

**Gamle arkitektur:**
- 1 paragraph = 1 audio fil
- Mange små requests = langsom
- Ingen god resume-funktion

**Nye arkitektur (v3.1):**
- Segments: 60-420 tegn (optimalt for voice clone kvalitet)
- Groups: ~35 sekunder af sammensatte segments
- O(1) resume via `start_time_ms`
- Færre, større audio filer

---

## 🗄️ Database Schema

### Tabeller

```sql
-- TTS Segments (individuelle tekst-blokke)
CREATE TABLE tts_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id UUID REFERENCES chapters(id),
    segment_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    paragraph_id UUID REFERENCES paragraphs(id),  -- for highlighting
    duration_ms INTEGER,
    group_id UUID,  -- Filled after grouping
    offset_in_group_ms INTEGER
);

-- Audio Groups (sammensatte audio filer)
CREATE TABLE audio_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id UUID REFERENCES chapters(id),
    group_index INTEGER NOT NULL,
    audio_url TEXT NOT NULL,  -- Supabase Storage URL
    duration_ms INTEGER NOT NULL,
    start_time_ms INTEGER NOT NULL,  -- For O(1) resume
    start_segment_index INTEGER NOT NULL,
    end_segment_index INTEGER NOT NULL
);

-- User Audio Progress
CREATE TABLE user_audio_progress (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id),
    book_id UUID REFERENCES books(id),
    chapter_id UUID REFERENCES chapters(id),
    chapter_time_ms INTEGER NOT NULL DEFAULT 0,
    speed REAL DEFAULT 1.0,
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 🔧 Pipeline Integration

### Nye funktioner i `pipeline_v3.py`:

#### `v3_generate_tts_audio(job_id, engine, voice, language)`
```python
# Genererer TTS audio:
# 1. Merger korte sections (<60 tegn)
# 2. Splitter lange sections (>420 tegn) ved sætningsgrænser
# 3. Genererer TTS for hvert segment
# 4. Måler faktisk audio duration
# 5. Grupperer segments til ~35 sek groups
# 6. Concatenerer group audio med FFmpeg
```

#### `v3_upload_audio_to_supabase(job_id)`
```python
# Uploader genereret audio:
# 1. Uploader group audio filer til Supabase Storage
# 2. Indsætter tts_segments records
# 3. Indsætter audio_groups records
# 4. Opdaterer chapter.audio_version = 'v2'
```

---

## 📦 Modulet: `audio_segments.py`

### Konstanter
```python
MIN_CHARS = 60           # Minimum segment længde
MAX_CHARS = 420          # Maximum segment længde
MIN_WORDS = 3            # Minimum ord-antal
TARGET_GROUP_DURATION_MS = 35000  # 35 sek per group
```

### Funktioner

| Funktion | Beskrivelse |
|----------|-------------|
| `process_segments(sections)` | Merger/clamper sections → segments |
| `merge_short_segments(sections)` | Merger korte tekster |
| `clamp_long_segments(merged)` | Splitter lange tekster |
| `get_audio_duration_ms(path)` | Læser faktisk duration via ffprobe |
| `group_segments(segments)` | Grupperer til ~35 sek |
| `concat_group_audio(group, dir)` | FFmpeg concat → M4A |
| `upload_group_audio(path, chapter_id, idx)` | → Supabase Storage |
| `save_groups_to_supabase(...)` | Indsætter i DB tabeller |

---

## 🔄 Workflow

### Typisk pipeline flow:

```
1. v3_extract_chapters(job_id)
   └── Extracter kapitler fra JSON/PDF

2. v3_process_chapters(job_id)
   └── GLM processor: paragraphs + sections

3. v3_generate_metadata_and_cover(job_id)
   └── Cover art + metadata (parallel med #2)

4. v3_upload_to_supabase(job_id)
   └── Uploader bog, nodes, kapitler, paragraphs
   └── Gemmer db_chapter_id i state

5. v3_generate_tts_audio(job_id, engine="runpod")
   └── Genererer TTS for alle segments
   └── Concatenerer til groups

6. v3_upload_audio_to_supabase(job_id)
   └── Uploader audio til Storage
   └── Gemmer tts_segments + audio_groups
```

---

## 📱 iOS Integration

### RPC Function: `get_chapter_manifest_v3`
```sql
CREATE OR REPLACE FUNCTION get_chapter_manifest_v3(p_chapter_id UUID)
RETURNS JSONB AS $$
BEGIN
    RETURN jsonb_build_object(
        'groups', (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'id', ag.id,
                    'audio_url', ag.audio_url,
                    'duration_ms', ag.duration_ms,
                    'start_time_ms', ag.start_time_ms,
                    'segment_range', ARRAY[ag.start_segment_index, ag.end_segment_index]
                )
                ORDER BY ag.group_index
            )
            FROM audio_groups ag
            WHERE ag.chapter_id = p_chapter_id
        ),
        'total_duration_ms', (
            SELECT COALESCE(SUM(duration_ms), 0)
            FROM audio_groups
            WHERE chapter_id = p_chapter_id
        )
    );
END;
$$ LANGUAGE plpgsql;
```

### Swift Resume Logic
```swift
// Binary search for O(log n) resume
func findGroupForTime(targetMs: Int, groups: [AudioGroup]) -> Int {
    var lo = 0, hi = groups.count - 1
    while lo < hi {
        let mid = (lo + hi + 1) / 2
        if groups[mid].startTimeMs <= targetMs {
            lo = mid
        } else {
            hi = mid - 1
        }
    }
    return lo
}
```

---

## 🚀 Next Steps

1. ✅ SQL migration kørt i Supabase
2. ✅ audio_segments.py integreret i pipeline_v3.py
3. ⏳ Test med reel TTS generation
4. ⏳ Tilføj iOS player der bruger nye RPC functions
5. ⏳ Implementer user_audio_progress tracking

---

## 📝 Changelog

**v3.1 (11.01.26)**
- Integreret audio_segments.py i pipeline_v3.py
- Tilføjet v3_generate_tts_audio() funktion
- Tilføjet v3_upload_audio_to_supabase() funktion
- Gemmer db_chapter_id for TTS linking
- Understøtter runpod, local, og piper TTS engines
