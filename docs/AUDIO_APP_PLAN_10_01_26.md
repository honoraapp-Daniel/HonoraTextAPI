# Honora Audio App 2.0 - Implementation Plan (10.01.26)

Dette dokument bruges til at spore fremdriften af transformationen af Honora Data Test appen til en robust lydbogs-applet.

## 📅 Status Oversigt

- **Dato:** 10. januar 2026
- **Status:** Igangsat
- **Fokus:** Fase 1A - Stabil Audio Engine

---

## 🚀 Fase 1A: Stabil Audio Engine (Fundamentet)
_Mål: En afspiller der håndterer den virkelige verdens kaos (opkald, netværkshiccups, skærmsluk)._

- [x] **1. Audio Session Lifecycle**
    - [x] Konfigurer `AVAudioSession` (.playback / .moviePlayback)
    - [x] Håndter `interruptionNotification` (Opkald/Alarm pause/resume)
    - [x] Håndter `routeChangeNotification` (Høretelefoner ud/ind)
- [x] **2. Remote Command Center**
    - [x] Integration med Lock Screen controls (Play, Pause, Skip)
    - [ ] Integration med Control Center
- [x] **3. State Machine & Events**
    - [x] Implementer robuste states (.idle, .loading, .playing, .paused, .buffering, .failed)
    - [x] Implementer Event Emitters/Publishers (Time update, track finished, errors)
- [x] **4. Playback Controls**
    - [x] Hastighedskontrol (0.75x - 2.0x)
    - [x] Intelligent Skip (-15s / +30s)

## 💾 Fase 2: Robust State & Persistence
_Mål: Appen må aldrig glemme hvor brugeren er, selv ved crash eller system dræbning._

- [x] **1. Data Model (`CurrentListenState`)**
    - [x] Structure til `bookId`, `chapterId`, `paragraphId`, `position`, `timestamp`
- [x] **2. Persistence Engine**
    - [x] Gem til `UserDefaults` / Disk
    - [x] Implementer Throttling (Gem kun hver X sekund)
    - [x] Implementer "Force Save" triggers (Pause, Backgrounding)
- [ ] **3. Rehydration**
    - [ ] Indlæs state ved app launch
    - [ ] UI visualisering af "Fortsæt hvor du slap"

## 🧠 Fase 1B: Intelligent Queue & Netværk
_Mål: Binde paragraphs sammen til en flydende "bog" oplevelse._

- [x] **1. Queue System**
    - [x] Playlist logic (Next/Previous paragraph)
    - [x] Auto-advance logic
    - [x] "End of Chapter" logic (Auto-stop for now)
- [ ] **2. Preload & Buffering**
    - [ ] Auto-fetch næste kapitel data ved lav resterende tid
    - [ ] Pre-buffer næste audio track (AVPlayerItem pre-roll)
- [ ] **3. Error Handling & Retry**
    - [ ] Network failure detection
    - [ ] Auto-retry med backoff
    - [ ] Graceful UI ved persistent fejl

## 🎨 Fase 3: UI Redesign (Simplicitet)
_Mål: Et rent, fokuseret interface._

- [ ] **1. Context-aware Reader**
    - [ ] Auto-scroll til aktiv paragraph
    - [ ] Visuel highlighting af aktiv sætning
    - [ ] Håndtering af manuel bruger-scroll (pause autoscroll)
- [x] **2. Home Screen Redesign**
    - [x] "Continue Reading" Hero Card
    - [x] Simpelt biblioteks-grid
- [ ] **3. Book Detail Redesign**
    - [ ] Forenklet layout uden tabs
    - [ ] Stor "PLAY" knap (Resume/Start)

## 🎵 Fase 4: Global Mini-Player
_Mål: Adgang til afspilleren fra hele appen._

- [x] **1. UI Implementation**
    - [x] Persistent bar over tab-bar
    - [x] Global adgang via ZStack overlay
- [ ] **2. Gestures**
    - [ ] Swipe-to-expand/collapse logic

---

## 📝 Noter & Ændringer undervejs
*Ingen endnu*
