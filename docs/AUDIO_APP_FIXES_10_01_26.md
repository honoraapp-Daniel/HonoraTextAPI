# Honora Audio App 2.0 - Rettelser & Forbedringer (10.01.26)

Dette dokument indeholder de identificerede fejl og mangler fra audit af implementeringen.

## 📅 Status Oversigt

- **Dato:** 10. januar 2026
- **Type:** Audit Rettelser
- **Prioritet:** Kritiske fejl først, derefter UX forbedringer

---

## 🔴 Høj Prioritet (App-Breaking)

### 1. Fix App Entry Point Duplikering
**Problem:** `Honora_Data_TestApp.swift` og `ContentView.swift` opretter begge samme layout. ContentView bruges ikke, og BooksListView får ikke korrekt padding.

**Rettelse:**
- [ ] Opdater `Honora_Data_TestApp.swift` til at bruge `ContentView()`
- [ ] Sikre at `.padding(.bottom, 80)` anvendes korrekt på main content

**Filer:**
- `Honora_Data_TestApp.swift`
- `ContentView.swift`

---

### 2. Implementer Resume/Rehydration
**Problem:** Når appen genåbnes, vises MiniPlayer med gemt state, men play-knappen gør ingenting fordi `playerItem` er `nil`.

**Rettelse:**
- [ ] Tilføj `resumeFromPersistedState()` funktion til `AudioPlayerManager`
- [ ] Funktionen skal:
  - Læse `PersistenceManager.currentState`
  - Hente paragraphs fra Supabase baseret på `chapterId`/`paragraphId`
  - Finde korrekt paragraph index
  - Kalde `play()` med korrekt `startIndex`
  - Søge til gemt `positionSeconds`
- [ ] Kald `resumeFromPersistedState()` fra MiniPlayer når state er `.idle` men persistence eksisterer

**Filer:**
- `AudioPlayerManager.swift`
- `MiniPlayerView.swift`
- `SupabaseManager.swift` (evt. ny fetch funktion)

---

### 3. Fix MiniPlayer SafeArea Layout
**Problem:** `.ignoresSafeArea` er på forkert niveau, og parent giver ikke padding. MiniPlayer kan overlappe Home Indicator.

**Rettelse:**
- [ ] Flyt safe area håndtering til `ContentView` niveau
- [ ] Sikre at MiniPlayer har korrekt højde inkl. safe area
- [ ] Test på iPhone med Home Indicator

**Filer:**
- `ContentView.swift`
- `MiniPlayerView.swift`

---

## 🟠 Medium Prioritet (UX Issues)

### 4. MiniPlayer Cover Art
**Problem:** Cover art URL eksisterer i state men vises aldrig - kun grå placeholder.

**Rettelse:**
- [ ] Erstat TODO kommentar med faktisk `AsyncImage` implementation
- [ ] Håndter loading og failure states

**Fil:** `MiniPlayerView.swift` (linje 32-35)

---

### 5. Lock Screen Now Playing Opdatering
**Problem:** `ElapsedPlaybackTime` opdateres kun ved track load, ikke løbende. Lock Screen progress bar er forkert.

**Rettelse:**
- [ ] Tilføj Now Playing opdatering i `startProgressObserver()` timer
- [ ] Opdater mindst hver 1-5 sekund (ikke hver 0.5s for performance)

**Fil:** `AudioPlayerManager.swift`

---

### 6. Konfigurer Remote Command Skip Intervaller
**Problem:** Skip kommandoer bruger system defaults i stedet for 15s/30s.

**Rettelse:**
- [ ] Tilføj i `setupRemoteCommands()`:
```swift
commandCenter.skipBackwardCommand.preferredIntervals = [15]
commandCenter.skipForwardCommand.preferredIntervals = [30]
```

**Fil:** `AudioPlayerManager.swift`

---

## 🟡 Lav Prioritet (Nice-to-Have)

### 7. Kapitel-niveau Progress i Contents List
**Problem:** Progress bar i Contents listen viser paragraph progress, ikke kapitel progress.

**Rettelse:**
- [ ] Track totalt antal paragraphs i kapitel
- [ ] Beregn progress som `currentParagraphIndex / totalParagraphs`
- [ ] Alternativt: Vis kun "Playing" indikator uden progress bar

**Fil:** `BookDetailView.swift`

---

### 8. Swipe-to-Expand Player
**Problem:** Planlagt feature, ikke implementeret.

**Rettelse:**
- [ ] Implementer full-screen player view
- [ ] Tilføj gesture recognizer til MiniPlayer
- [ ] Animeret overgang

**Filer:**
- `MiniPlayerView.swift`
- Ny: `FullPlayerView.swift`

---

## 📋 Tjekliste - Rækkefølge

```
[x] 1. Fix App Entry Point ✅
[x] 2. Fix MiniPlayer SafeArea ✅
[x] 3. Implementer Resume/Rehydration ✅
[x] 4. MiniPlayer Cover Art ✅
[x] 5. Lock Screen Now Playing ✅
[x] 6. Skip Intervaller ✅
[ ] 7. Kapitel Progress (optional)
[ ] 8. Swipe Player (optional)
```

---

## 📝 Noter
- Punkt 1-3 skal fikses før appen er brugbar
- Punkt 4-6 er vigtige for professionel finish
- Punkt 7-8 kan vente til næste iteration
