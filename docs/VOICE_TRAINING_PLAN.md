# Honora Voice Training Plan — FINAL

> **Version:** 1.0  
> **Oprettet:** 2026-01-10  
> **Status:** Klar til eksekvering

---

## Kerneprincip

> **Ingen infrastruktur før stemmen er bevist.**
> 
> En god stemme kørt fra terminal > dashboard til en dårlig stemme.

---

## Phase A: Bevis Stemmen (Quality Proof)

**Mål:** Én trænet model der klarer en 5-minutters audiobook-passage uden hørbare artefakter.

### A1: Data Foundation

#### Audio Requirements

| Teknisk krav | Værdi |
|--------------|-------|
| Sample rate | 44.1kHz eller 48kHz |
| Bit depth | 16-bit minimum, 24-bit foretrukket |
| Format | WAV (ikke MP3/AAC) |
| Støjgulv | < -50dB |
| Rum | Lydbehandlet (ingen reverb) |

#### Data Tiers

| Tier | Mængde | Kvalitet | Anvendelse |
|------|--------|----------|------------|
| **PoC** | 15-30 min | "Lyder som personen" | Teknisk validering |
| **MVP** | 2-4 timer | Konsistent, men begrænset prosodi | Test på korte passager |
| **Production** | 8-15 timer | Fuld prosodisk kontrol | Audiobook-produktion |

**DISTINKTION:**
- PoC beviser at fine-tuning virker teknisk
- MVP beviser at stemmen kan bruges til korte sektioner
- Production er kravet for at shippe

#### Datakvalitet > Datamængde

**10 timers dårlig data < 3 timers perfekt data**

Krav til perfekt data:
- Ingen baggrundsstøj
- Konsistent mikrofonafstand
- **Kontrolleret narrativ oplæsning:** Jævnt tempo, neutral intonation, tydelig artikulation. Ikke podcast-snak (for uformelt, variabelt tempo). Ikke teatralsk voice acting (for ekspressivt, inkonsistent). Egnet til 30+ minutters kontinuerlig lytning uden træthed.
- Varieret sætningsstruktur (ikke kun korte eller kun lange)
- Ingen editering-artefakter

---

### A2: Træning (Minimal Viable)

#### Fast konfiguration

```yaml
# Phase A: Fixed config - ingen tweaking
base_model: xtts_v2
learning_rate: 2e-5          # Start her, juster KUN hvis divergens
batch_size: 4                # A100: 8, A40: 4
max_epochs: 100              # Brug early stopping, ikke fixed epochs
eval_steps: 500              # Evaluer hver 500 step
warmup_steps: 200
gradient_accumulation: 2
```

#### Early Stopping Protocol

**Stop træning når:**
1. Eval loss stiger 3 gange i træk
2. Eval loss plateau i 10 evalueringer
3. Max epochs nået

**Gem checkpoint ved:**
- Laveste eval loss (best_loss.pt)
- Hver 5000 steps (checkpoint_{step}.pt)

#### Eval Set Design

```
eval_set/
├── short_sentences/ (20 stk, 5-15 ord)
│   ├── declarative.txt
│   ├── questions.txt
│   └── exclamations.txt
├── complex_elements/ (15 stk)
│   ├── numbers.txt        # "In 1847, the population reached 2.3 million"
│   ├── abbreviations.txt  # "Dr. Smith met Prof. Johnson at MIT"
│   └── quotes.txt         # He said, "This cannot continue."
└── long_passages/ (5 stk, 100-200 ord)
    └── narrative.txt      # Actual audiobook excerpts
```

---

### A3: Evaluering (Go/No-Go)

**Test 1: Technical Sanity**
```bash
python evaluate.py --model best_loss.pt --eval-dir eval_set/
```

Automatisk check:
- [ ] Alle filer genereret uden crash
- [ ] Ingen samples > 30 sekunder for korte sætninger (tempo-check)
- [ ] Ingen samples < 2 sekunder for lange passager (completion-check)

**Test 2: Manual Listening**

| Sample Type | Hvad lytter du efter | Pass-kriterie |
|-------------|---------------------|----------------|
| Short sentences | Naturlig intonation, korrekt ordlyd | 18/20 acceptable |
| Numbers/dates | Korrekt udtale af tal | 12/15 korrekte |
| Quotes | Prosodisk skift for citater | 10/15 hørbart skift |
| Long passages | Ingen robotic drift, naturlige pauser | Alle 5 lyttelige hele vejen |

**Test 3: Audiobook Passage**

Generér 5 minutters sammenhængende tekst fra reel bog.

| Kriterie | Fail | Pass |
|----------|------|------|
| Forståelighed | Ord som ikke kan skelnes | Alt forståeligt |
| Prosodi | Monoton hele vejen | Naturlig variation |
| Artefakter | Klik, pop, unaturlige pauser | Ingen hørbare |
| Tempo-stabilitet | Speeder op/ned abrupt | Jævnt |

---

### A4: Phase A Afslutning

**GO-kriterie for Phase B:**
```
□ Test 1: Alle tekniske checks bestået
□ Test 2: Mindst 75% pass rate på hver kategori
□ Test 3: 5-min passage subjektivt "god nok til intern test"
```

**NO-GO handlinger:**
- Hvis Test 2 < 50%: Data kvalitetsproblem → indsaml bedre data
- Hvis Test 3 fails på artefakter: Hyperparameter problem → justér og retrain
- Hvis stemmen lyder forkert: Forkert base model → overvej anden tilgang

---

## Phase B: Skaler Kvalitet

**Forudsætning:** Phase A GO opnået.

**Mål:** Produktions-klar stemme der kan bære 10+ timers audiobooks.

### B1: Data Expansion

Baseret på Phase A fejl, indsaml mere data for:

| Svaghed identificeret | Data-type at tilføje |
|----------------------|----------------------|
| Ustabilt tempo | Lange, jævnt tempo passager |
| Dårlige tal | Specifik tal-fokuseret data |
| Monoton narrativ | Emotionel variation |
| Citater flade | Dialog-træning |

---

### B2: Iterativ Træning

```
Loop:
  1. Træn med udvidet data
  2. Kør A3 evalueringsprotokol
  3. Identificér svage punkter
  4. Indsaml målrettet data
  5. Gentag indtil pass ELLER stop-regel aktiveres
```

#### Checkpoint Selection Protocol

**BRUG IKKE bare "best loss"**

For audiobooks:
1. Gem top-3 checkpoints efter loss
2. Generér samme 5-min passage med alle 3
3. Vælg det der lyder bedst (subjektivt)

Loss ≠ lydbillede. Laveste loss kan være overfittet.

---

### B3: Audiobook-Specifikke Tests

#### Narrationsregler

| Element | Regel | Test |
|---------|-------|------|
| **Kapitler** | Kort pause før kapiteltitel, tydeligt tempo | "Chapter 7. The Discovery" |
| **Årstal** | Udtales fuldt: "Eighteen forty-seven" | "In 1847, the war began" |
| **Tal** | Store tal: naturlig opdeling | "2,347,891 votes" → "two million, three hundred..." |
| **Forkortelser** | Konsistent: enten ful udtale eller forkortelse | "Dr." → Doctor vs "Dr." |
| **Citater** | Prosodisk skift, ikke bare pause | He said, "This is wrong." |
| **Tempo** | Beskrivende passager: lidt langsommere, action: hurtigere | Subjektiv vurdering |
| **Pauser** | Se retningslinjer nedenfor | Subjektiv vurdering |

#### Pausetiming (retningslinjer, ikke constraints)

Følgende værdier er **lytte-referencer** til evaluering, ikke model-constraints:

| Interpunktionstegn | Reference-interval |
|---------------------|-------------------|
| Periode | 400-600ms |
| Komma | 200-300ms |
| Paragraf-skift | 800-1000ms |

**Anvendelse:**
- Brug disse som huskeregler når du lytter efter unaturlige pauser
- Modellen styrer pauser via tekststruktur og prosodisk læring
- Menneskelig vurdering af "lyder naturligt" vægter højere end ms-målinger
- Hvis pauser lyder forkerte, er løsningen bedre data — ikke justering af tal

---

### B4: Stop Rule (obligatorisk)

**Phase B iteration SKAL stoppe hvis:**

1. **Datamængde-grænse:** +50% mere træningsdata giver ikke målbar forbedring i Test 2 pass-rate
2. **Gentagelsesmønster:** Samme svagheder (fx dårlige tal, flad prosodi) gentager sig over 3 træningsruns trods målrettet data
3. **Ressourcegrænse:** Mere end 5 fulde træningsiterations uden at nå GO-kriterie

**Ved Stop Rule aktivering → gå til afsluttende beslutningspunkt**

---

### B5: Phase B Afslutning

**GO-kriterie for Phase C:**
```
□ 30-min komplet kapitel genereret uden artefakter
□ Alle narrationsregler demonstrerbart opfyldt
□ Kapitel lyder professionelt ved blindtest
```

---

## Phase C: Produktisering

**Forudsætning:** Phase B GO opnået.

**Mål:** Integrér i Honora pipeline med versionering.

### C1: Model Export

- Simpel model-versionering i Supabase
- Integration med eksisterende TTS dashboard
- One-click switching mellem stock XTTS og custom voice

### C2: Production Integration

```python
class HonoraCustomVoiceEngine(TTSEngine):
    """Honora's trained custom voice"""
    
    def __init__(self):
        self.model_path = "models/honora_voice_v1.pt"
```

### C3: Versionering

| Version | Træningsdata | Status |
|---------|--------------|--------|
| v0.1 | PoC | Bevis |
| v1.0 | MVP | Test |
| v2.0 | Production | Live |

---

## Afsluttende Beslutningspunkt

**Efter Phase B (eller ved Stop Rule aktivering):**

| Beslutning | Kriterie | Handling |
|------------|----------|----------|
| **SHIP** | GO-kriterie opfyldt | → Phase C → Production |
| **ITERATE** | Fremgang synlig, men ikke nok | → Mere data, gentrain (max 2 ekstra runs) |
| **SCRAP** | Stop Rule aktiveret uden fremgang | → Evaluer anden model-base eller professionel speaker |

---

## Plan Lock

**Denne plan er FINAL.**

- Ingen ændringer undtagen hvis Phase A eller B fejler deres GO/NO-GO gates
- Ingen nye features, dashboards eller metrics før stemmen er godkendt i Phase B
- Scope creep afvises: "Det kan vi tilføje i v2" er acceptabelt svar
- Første prioritet er altid: én fungerende stemme der kan bære Honora audiobooks

---

## Changelog

| Dato | Version | Ændring |
|------|---------|---------|
| 2026-01-10 | 1.0 | Initial plan oprettet |

---

*Sidst opdateret: 2026-01-10*
