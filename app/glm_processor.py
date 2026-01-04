"""
Text Processor for V3 Pipeline
Uses Google Gemini for text processing:
- Clean OCR errors
- Convert numbers/symbols to words
- Create natural paragraphs
- Create TTS sections (250-300 chars)
"""

import os
import re
import logging
from typing import List, Dict, Optional
import google.generativeai as genai

logger = logging.getLogger(__name__)

# Lazy client initialization
_gemini_configured = False


def get_gemini_model():
    """Get configured Gemini model."""
    global _gemini_configured
    if not _gemini_configured:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")
        genai.configure(api_key=api_key)
        _gemini_configured = True
    return genai.GenerativeModel("gemini-2.0-flash")


# ============================================
# PROMPTS
# ============================================

PARAGRAPH_PROMPT = """INSTRUKTION TIL TEKST-EDITOR (STRENG PARAGRAF-OPDELING):

Du er en teksteditor der forbereder bøger til en lydbogs-app. Din opgave er at opdele kapiteltekst i PARAGRAPHS.

═══════════════════════════════════════════════════════════════
REGEL 1: PARAGRAPH 0 - KAPITELTITEL (OBLIGATORISK)
═══════════════════════════════════════════════════════════════
Det FØRSTE [PARAGRAPH] SKAL være kapitlets titel og eventuelt kapitelnummer.
- KORREKT: "Chapter One: The Beginning" eller "I. Apprentice" eller "The Fellow-Craft"
- FORKERT: Bogens titel (f.eks. "Morals and Dogma") må ALDRIG være Paragraph 0
- Hvis kapitlets titel er f.eks. "I. Apprentice", så skriv det SAMLET som én Paragraph 0

═══════════════════════════════════════════════════════════════
REGEL 2: MINIMUM ORDANTAL FOR NORMALE PARAGRAPHS
═══════════════════════════════════════════════════════════════
Hver normal paragraph SKAL indeholde MINIMUM 20-30 ord (ca. 3-4 linjer tekst).
- ALDRIG enkeltlinjer som "It adds insolency to power." - disse skal SAMLES med næste tekst
- ALDRIG korte sætninger alene som "It is destruction and ruin." - saml dem!
- Hvis flere korte sætninger følger hinanden, FLET DEM til én større paragraph

UNDTAGELSER (korte paragraphs tilladt):
- Kapiteltitler og underoverskrifter
- Direkte citater markeret med anførselstegn
- Verslinjer fra digte
- Korte udbrud eller dialog

═══════════════════════════════════════════════════════════════
REGEL 3: LISTER SKAL HOLDES SAMMEN
═══════════════════════════════════════════════════════════════
Når teksten har punktopstilling, BEHOLD dem i SAMME paragraph:
- A., B., C. lister → én paragraph
- 1., 2., 3. lister → én paragraph  
- (one), (two), (three) lister → én paragraph
- Romertal i., ii., iii. lister → én paragraph

UNDTAGELSE: Hvis listen har MERE end 10 punkter, del op i 2 paragraphs.

═══════════════════════════════════════════════════════════════
REGEL 4: TAL TIL ORD
═══════════════════════════════════════════════════════════════
Konverter alle tal til ord:
- "Chapter 4" → "Chapter Four"
- "1918" → "Nineteen Eighteen"
- "12 men" → "Twelve men"

═══════════════════════════════════════════════════════════════
REGEL 5: FJERN STØJ
═══════════════════════════════════════════════════════════════
Fjern ALT der ikke er bogindhold:
- Sidetal (som "23 / 47")
- Filstørrelser ("267Kb")
- "Click to enlarge"
- Navigation, metadata, forfatterinfo der gentages

═══════════════════════════════════════════════════════════════
REGEL 6: OCR-RETTELSER
═══════════════════════════════════════════════════════════════
Ret scanningsfejl ("lie" → "he", "leas" → "has") men BEVAR forfatterens stil.

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════
Start DIREKTE med [PARAGRAPH] - ingen forklaringer.
Hvert afsnit markeres med [PARAGRAPH] i starten.

EKSEMPEL PÅ KORREKT OUTPUT:
[PARAGRAPH]
Chapter One: The Beginning
[PARAGRAPH]
This is a properly formatted paragraph with sufficient content. It contains multiple sentences that flow naturally together and provides meaningful context for the reader. The minimum word count ensures a smooth reading and listening experience.
[PARAGRAPH]
Another substantial paragraph follows here, containing at least twenty to thirty words as required by the formatting rules.

Her er teksten:

{text}"""


SECTION_PROMPT = """Instruktion til AI:

Du skal fungere som en teksteditor, der forbereder tekst til Tekst-til-Tale (TTS) med korte tekst-sektioner (chunks).

Opgave: Jeg vil give dig rå tekst. Din opgave er at opdele teksten i korte bidder, renset for støj og fejl, så den passer perfekt til en TTS-engine, der stopper efter hver sektion.

Følg disse 5 regler strengt:

1. Tal til Bogstaver: Konverter alle tal til ord (f.eks. "Chapter 4" skal være "Chapter Four", årstal "1918" skal være "Nineteen Eighteen").
2. Fjern Støj: Fjern ALT der ikke er en del af selve bogen/historien. Dette inkluderer: sidetal (som "23 / 47"), forfatterinfo der gentager sig, filstier, filstørrelser (som "267Kb"), "Click to enlarge", navigationslinks, metadata, og alt andet der tydeligt ikke er bogens indhold.
3. TTS-Chunking (Maks 250-300 tegn): Teksten skal opdeles i korte sektioner.
   - Begrænsning: Hver sektion må maksimalt indeholde 250-300 tegn (inklusive mellemrum).
   - Naturlig split: Du skal forestille dig, at du læser teksten højt. Hvor ville du lave en lille naturlig pause? Klip teksten ved det mest logiske sted inden for tegngrænsen.
   - VIGTIGT: Marker hver sektion med [SECTION] i starten.
4. Rens OCR-fejl: Ret indlysende stavefejl, der skyldes scanningen. Du må ikke omskrive sætninger eller ændre forfatterens stil – du må kun fjerne fejl.
5. Struktur: Bevar kapitler og overskrifter, men sørg for at de står for sig selv og er markeret tydeligt.

VIGTIGT: Giv INGEN forklarende tekst, kommentarer eller indledning. Start DIREKTE med [SECTION] og det rensede indhold.

Output: Giv mig KUN teksten opdelt i korte sektioner med [SECTION] markører.

Her er teksten der skal forarbejdes:

{text}"""


# ============================================
# PROCESSING FUNCTIONS
# ============================================

def call_gemini(prompt: str) -> str:
    """Call Gemini API with given prompt."""
    model = get_gemini_model()
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
        
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        raise


def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def is_heading_or_special(text: str) -> bool:
    """
    Check if text appears to be a heading, quote, or other special content
    that's allowed to be short.
    """
    text = text.strip()
    
    # Very short texts that look like chapter/section headers
    if len(text) < 100:
        # All caps or title case with few words = likely heading
        words = text.split()
        if len(words) <= 6:
            if text.isupper():
                return True
            # Starts with chapter/roman numeral
            if re.match(r'^(Chapter|CHAPTER|I{1,3}|IV|V|VI{0,3}|IX|X|XI{0,3}|[0-9]+\.)', text):
                return True
    
    # Quoted text
    if text.startswith('"') and text.endswith('"'):
        return True
    if text.startswith("'") and text.endswith("'"):
        return True
    
    # Poetry-like (very short lines ending with specific patterns)
    lines = text.split('\n')
    if len(lines) > 1 and all(len(line) < 50 for line in lines):
        return True
    
    return False


def validate_and_merge_paragraphs(paragraphs: List[Dict], chapter_title: str = None) -> List[Dict]:
    """
    Post-process paragraphs to ensure minimum word counts.
    Merges consecutive short paragraphs (under 20 words) unless they're headings/quotes.
    Ensures paragraph 0 is the chapter title, not the book title.
    """
    if not paragraphs:
        return paragraphs
    
    MIN_WORDS = 20
    validated = []
    pending_merge = ""
    
    for i, para in enumerate(paragraphs):
        text = para["text"]
        word_count = count_words(text)
        
        # First paragraph (index 0) should be chapter title
        if i == 0:
            # If chapter_title is provided, use it
            if chapter_title:
                validated.append({"id": "p0", "text": chapter_title})
                # If original p0 was the chapter title, skip it; otherwise keep as p1
                if text.lower().strip() != chapter_title.lower().strip():
                    # Original content wasn't the title, add it
                    if word_count >= MIN_WORDS or is_heading_or_special(text):
                        validated.append({"id": f"p{len(validated)}", "text": text})
                    else:
                        pending_merge = text
            else:
                validated.append({"id": "p0", "text": text})
            continue
        
        # Check if it's a heading/special content
        if is_heading_or_special(text):
            # Flush any pending merge first
            if pending_merge:
                validated.append({"id": f"p{len(validated)}", "text": pending_merge})
                pending_merge = ""
            validated.append({"id": f"p{len(validated)}", "text": text})
            continue
        
        # Normal paragraph checks
        if word_count < MIN_WORDS:
            # Too short - merge with pending or start pending
            if pending_merge:
                pending_merge = pending_merge + " " + text
            else:
                pending_merge = text
            
            # If merged content is now long enough, flush it
            if count_words(pending_merge) >= MIN_WORDS:
                validated.append({"id": f"p{len(validated)}", "text": pending_merge})
                pending_merge = ""
        else:
            # Normal paragraph with sufficient words
            if pending_merge:
                # Merge pending with this paragraph
                text = pending_merge + " " + text
                pending_merge = ""
            validated.append({"id": f"p{len(validated)}", "text": text})
    
    # Flush any remaining merge
    if pending_merge:
        if validated:
            # Append to last paragraph
            validated[-1]["text"] = validated[-1]["text"] + " " + pending_merge
        else:
            validated.append({"id": "p0", "text": pending_merge})
    
    # Re-number all paragraphs
    for i, para in enumerate(validated):
        para["id"] = f"p{i}"
    
    return validated


def process_chapter_paragraphs(text: str, chapter_title: str = None) -> List[Dict]:
    """
    Process chapter text to create natural paragraphs.
    
    Args:
        text: Raw chapter text content
        chapter_title: The chapter title (will be used as Paragraph 0)
    
    Returns list of paragraph dicts:
    [{"id": "p0", "text": "Chapter Title"}, {"id": "p1", "text": "..."}, ...]
    """
    if not text or not text.strip():
        return []
    
    prompt = PARAGRAPH_PROMPT.format(text=text)
    result = call_gemini(prompt)
    
    # Parse [PARAGRAPH] markers
    paragraphs = []
    parts = re.split(r'\[PARAGRAPH\]', result)
    
    for i, part in enumerate(parts):
        cleaned = part.strip()
        if cleaned:
            paragraphs.append({
                "id": f"p{i}",
                "text": cleaned
            })
    
    # If no markers found, split by double newlines
    if len(paragraphs) <= 1 and result:
        parts = result.split('\n\n')
        paragraphs = []
        for i, part in enumerate(parts):
            cleaned = part.strip()
            if cleaned:
                paragraphs.append({
                    "id": f"p{i}",
                    "text": cleaned
                })
    
    # POST-PROCESSING: Validate and merge short paragraphs
    paragraphs = validate_and_merge_paragraphs(paragraphs, chapter_title)
    
    logger.info(f"GLM created {len(paragraphs)} validated paragraphs from {len(text)} chars")
    return paragraphs


def process_chapter_sections(text: str) -> List[Dict]:
    """
    Process chapter text to create TTS sections (250-300 chars).
    
    Returns list of section dicts:
    [{"id": "s1", "text": "..."}, {"id": "s2", "text": "..."}]
    """
    if not text or not text.strip():
        return []
    
    prompt = SECTION_PROMPT.format(text=text)
    result = call_gemini(prompt)
    
    # Parse [SECTION] markers
    sections = []
    parts = re.split(r'\[SECTION\]', result)
    
    for i, part in enumerate(parts):
        cleaned = part.strip()
        if cleaned:
            sections.append({
                "id": f"s{i}",
                "text": cleaned
            })
    
    # Validate section lengths - split any that are too long
    validated_sections = []
    for section in sections:
        if len(section["text"]) > 350:  # Allow some flexibility
            # Split long sections at sentence boundaries
            sub_sections = split_long_section(section["text"])
            for j, sub in enumerate(sub_sections):
                validated_sections.append({
                    "id": f"{section['id']}_{j}",
                    "text": sub
                })
        else:
            validated_sections.append(section)
    
    # Re-number sections
    for i, section in enumerate(validated_sections):
        section["id"] = f"s{i}"
    
    logger.info(f"GLM created {len(validated_sections)} sections from {len(text)} chars")
    return validated_sections


def split_long_section(text: str, max_chars: int = 300) -> List[str]:
    """Split a long section at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]
    
    sections = []
    sentences = re.split(r'(?<=[.!?])\s+', text)
    current = ""
    
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip()
        else:
            if current:
                sections.append(current)
            current = sentence
    
    if current:
        sections.append(current)
    
    return sections


def process_full_chapter(chapter_title: str, chapter_text: str) -> Dict:
    """
    Process a complete chapter through GLM pipeline.
    
    Returns:
    {
        "title": "Chapter name",
        "paragraphs": [...],
        "sections": [...]
    }
    """
    logger.info(f"Processing chapter: {chapter_title}")
    
    # Get paragraphs first - pass chapter_title to ensure Paragraph 0 is correct
    paragraphs = process_chapter_paragraphs(chapter_text, chapter_title=chapter_title)
    
    # Use cleaned paragraph text for sections (skip paragraph 0 which is the title)
    content_paragraphs = paragraphs[1:] if len(paragraphs) > 1 else paragraphs
    cleaned_text = "\n\n".join([p["text"] for p in content_paragraphs])
    sections = process_chapter_sections(cleaned_text)
    
    return {
        "title": chapter_title,
        "paragraphs": paragraphs,
        "sections": sections
    }
