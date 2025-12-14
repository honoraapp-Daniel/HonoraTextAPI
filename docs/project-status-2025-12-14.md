# Honora Book API - Project Status
**Date: 2025-12-14**

## ✅ Hvad vi har nu

| Endpoint | Status | Beskrivelse |
|----------|--------|-------------|
| `POST /extract_pdf` | ✅ Færdig | Upload PDF → extract tekst |
| `POST /create_book` | ✅ Færdig | Auto-detect titel, forfatter, sprog → Supabase |
| `POST /clean_book` | ✅ Færdig | GPT renser tekst til TTS |
| `POST /extract_chapters` | ✅ Færdig | Split i kapitler → Supabase |
| Custom Swagger UI | ✅ Færdig | Dark purple Honora branding |

---

## 🔧 Hvad vi mangler

| Feature | Estimat | Beskrivelse |
|---------|---------|-------------|
| `/chunk_chapters` | ~2 timer | Split kapitler i max 250-tegn sections → Supabase |
| Coqui TTS integration | ~3-4 timer | Send chunks til TTS API, modtag audio |
| Audio merging | ~1-2 timer | Kombiner chunk-audio til 1 MP3 per kapitel |
| Supabase Storage upload | ~1-2 timer | Upload MP3 til bucket, gem URL |
| `/process_book` (fuld pipeline) | ~2-3 timer | Ét endpoint der kører alt automatisk |
| Timestamp beregning | ~1 time | Beregn start_ms/end_ms for sections |

**Total estimat: ~10-14 timer**

---

## 📋 Prioriteret Rækkefølge

1. **`/chunk_chapters`** ← Start her (ingen ekstern dependency)
2. **Coqui TTS setup** ← Deploy til cloud med GPU
3. **TTS integration** ← Når Coqui er online
4. **Audio merge + upload**
5. **`/process_book`** ← Samle alt i ét endpoint
6. **App API endpoints** ← For at hente data i appen

---

## 🏗️ Supabase Struktur

```
books
├── id (UUID)
├── title, author, language
├── cover_art_url
└── play_time_seconds

chapters
├── id (UUID)
├── book_id → books.id
├── chapter_index, title
├── audio_url, duration_seconds

sections
├── id (UUID)
├── chapter_id → chapters.id
├── section_index
├── text_ref (max 250 tegn)
├── start_ms, end_ms

Storage: audio/{book_id}/chapter_X.mp3
```
