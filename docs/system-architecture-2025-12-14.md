# Honora System Architecture
**Date: 2025-12-14**

## 🔌 Services Overview

| Service | Rolle | URL |
|---------|-------|-----|
| **Railway** | Hoster HonoraTextAPI (FastAPI) | honoratextapi-production.up.railway.app |
| **Supabase** | Database + Storage | dwhimlmsygzpwxvlnucb.supabase.co |
| **OpenAI** | GPT-4 text cleaning | api.openai.com |
| **Coqui TTS** | Text-to-Speech (GPU cloud) | *TBD - ikke deployet endnu* |
| **GitHub** | Kode repository | github.com/honoraapp-Daniel |

---

## 🔄 Service Communication Flow

```
┌──────────────────────────────────────────────────────────────┐
│                         USER / APP                            │
└──────────────────────────────────────────────────────────────┘
                              │
                              │ 1. Upload PDF
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    RAILWAY (FastAPI)                          │
│                    HonoraTextAPI                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ /extract_pdf → /create_book → /clean_book →             │ │
│  │ /extract_chapters → /chunk_chapters → TTS → Upload      │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
         │              │                │              │
         │              │                │              │
         │ 2. Clean     │ 3. Store       │ 4. Generate  │ 5. Upload
         │    Text      │    Data        │    Audio     │    MP3
         ▼              ▼                ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│   OPENAI     │ │   SUPABASE   │ │  COQUI TTS   │ │   SUPABASE   │
│   GPT-4      │ │   Database   │ │  (GPU Cloud) │ │   Storage    │
│              │ │              │ │              │ │              │
│ Text cleanup │ │ books        │ │ voice_id →   │ │ audio/       │
│ for TTS      │ │ chapters     │ │ MP3 chunks   │ │ book_id/     │
│              │ │ sections     │ │              │ │ chapter.mp3  │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
```

---

## 📊 Data Flow Sequence

```
1. USER uploads PDF
        ↓
2. RAILWAY extracts text from PDF
        ↓
3. RAILWAY → OPENAI: Clean text for TTS
        ↓
4. RAILWAY → SUPABASE: Create book + chapters
        ↓
5. RAILWAY chunks text (max 250 chars)
        ↓
6. RAILWAY → SUPABASE: Save sections with text
        ↓
7. RAILWAY → COQUI TTS: Generate audio per chunk
        ↓
8. RAILWAY merges audio chunks → 1 MP3/chapter
        ↓
9. RAILWAY → SUPABASE STORAGE: Upload MP3 files
        ↓
10. RAILWAY → SUPABASE: Update chapters with audio_url
        ↓
11. RAILWAY → USER: Return book_id + chapters w/ URLs
```

---

## 📱 App Data Fetching

```
HONORA APP
    │
    ├── GET books → Supabase
    │
    ├── GET chapters?book_id=X → Supabase
    │
    ├── GET sections?chapter_id=X → Supabase
    │
    └── STREAM audio → Supabase Storage (audio_url)
```

---

## 🔑 Environment Variables

| Service | Variable | Used By |
|---------|----------|---------|
| OpenAI | `OPENAI_API_KEY` | Railway |
| Supabase | `SUPABASE_URL` | Railway |
| Supabase | `SUPABASE_SERVICE_ROLE_KEY` | Railway |
| Coqui TTS | `COQUI_TTS_URL` | Railway (TBD) |
| Coqui TTS | `COQUI_API_KEY` | Railway (TBD) |
