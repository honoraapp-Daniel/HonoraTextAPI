---
description: Start alle Honora dashboards (Pipeline V3, TTS Dashboard, Web Scraper)
---

# 🚀 Tænd Dashboards

Dette dokument beskriver hvordan du starter de forskellige Honora dashboards.

---

## 1. Pipeline V3 Dashboard

**URL:** http://localhost:8000/v3  
**Også tilgængelig:**
- http://localhost:8000/ (V1 Dashboard)
- http://localhost:8000/v2 (V2 Dashboard)
- http://localhost:8000/v2/editor (Chapter Editor)
- http://localhost:8000/docs (API Docs)

**Kommando:**
```bash
cd /Users/cuwatyarecords/Desktop/HonoraTextAPI
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Beskrivelse:** FastAPI-baseret pipeline til at behandle bøger fra PDF/JSON til Supabase. Inkluderer metadata-ekstraktion, kapitler, sektioner, afsnit og cover art.

---

## 2. TTS Dashboard (Multi-Engine)

**URL:** http://127.0.0.1:5001

**Kommando:**
```bash
cd /Users/cuwatyarecords/Desktop/HonoraTextAPI/HonoraLocalTTS
python3 tts_dashboard.py
```

**Beskrivelse:** Text-to-Speech dashboard med flere engines:
- ✅ **Piper** - Hurtig lokal TTS (gratis, ~10x hurtigere end XTTS)
- ✅ **XTTS-Local** - Voice cloning i høj kvalitet (gratis, langsom)
- ✅ **XTTS-RunPod** - GPU-accelereret (~$0.20/time)
- ✅ **XTTS-Replicate** - GPU via Replicate (~$0.015/kørsel)

**Features:**
- Vælg bøger og kapitler fra Supabase
- Generer TTS for paragraffer
- Upload automatisk til Supabase storage
- 3 parallelle workers

---

## 3. Web Scraper Dashboard

**URL:** http://localhost:3001

**Kommando:**
```bash
cd /Users/cuwatyarecords/Desktop/HonoraTextAPI/HonoraWebScraper
node src/server.js
```

**Beskrivelse:** Web scraper til at downloade bøger fra sacred-texts.com. Understøtter:
- Kategori-browser
- Enkelt-bog download
- Hele kategori download
- Automatisk PDF + JSON generering
- Mapping Editor til manuel struktur-korrektion

---

## Hurtig Reference

| Dashboard | Port | Start Kommando |
|-----------|------|----------------|
| Pipeline V3 | 8000 | `python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` |
| TTS Dashboard | 5001 | `python3 tts_dashboard.py` |
| Web Scraper | 3001 | `node src/server.js` |

---

## Start Alle (én terminal per dashboard)

**Terminal 1 - Pipeline:**
```bash
cd /Users/cuwatyarecords/Desktop/HonoraTextAPI && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 - TTS:**
```bash
cd /Users/cuwatyarecords/Desktop/HonoraTextAPI/HonoraLocalTTS && python3 tts_dashboard.py
```

**Terminal 3 - Scraper:**
```bash
cd /Users/cuwatyarecords/Desktop/HonoraTextAPI/HonoraWebScraper && node src/server.js
```
