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

PARAGRAPH_PROMPT = """Instruktion til AI:

Du skal fungere som en specialiseret teksteditor, der forbereder bøger til Tekst-til-Tale (TTS) med synkroniseret tekstfremhævning på skærmen.

Opgave: Jeg vil give dig rå tekst fra en PDF (ofte med OCR-fejl og sidetal). Din opgave er at "rense" teksten så den er optimal til lyd og skærmvisning.

Følg disse 5 regler strengt:

1. Tal til Bogstaver: Konverter alle tal til ord (f.eks. "Chapter 4" skal være "Chapter Four", årstal "1918" skal være "Nineteen Eighteen").
2. Fjern Støj: Fjern ALT der ikke er en del af selve bogen/historien. Dette inkluderer: sidetal (som "23 / 47"), forfatterinfo der gentager sig, filstier, filstørrelser (som "267Kb"), "Click to enlarge", navigationslinks, metadata, og alt andet der tydeligt ikke er bogens indhold.
3. Naturlige Afsnit: Brud de store, tunge tekstblokke op i mindre, naturlige afsnit. Det er afgørende for TTS-pauser og for læsbarhed på skærmen, når teksten fremhæves. VIGTIGT: Marker hvert afsnit med [PARAGRAPH] i starten.
4. Rens OCR-fejl: Ret indlysende stavefejl, der skyldes scanningen (f.eks. hvis "he" står som "lie", eller "has" står som "leas", så ret det). Du må ikke omskrive sætninger eller ændre forfatterens stil – du må kun fjerne fejl.
5. Struktur: Bevar kapitler, digte og underafsnit, men sørg for de er markeret tydeligt.

VIGTIGT: Giv INGEN forklarende tekst, kommentarer eller indledning. Start DIREKTE med [PARAGRAPH] og det rensede indhold.

Output: Giv mig KUN den rensede tekst med [PARAGRAPH] markører.

Her er teksten der skal forarbejdes:

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


def process_chapter_paragraphs(text: str) -> List[Dict]:
    """
    Process chapter text to create natural paragraphs.
    
    Returns list of paragraph dicts:
    [{"id": "p1", "text": "..."}, {"id": "p2", "text": "..."}]
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
    
    logger.info(f"GLM created {len(paragraphs)} paragraphs from {len(text)} chars")
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
    
    # Get paragraphs first
    paragraphs = process_chapter_paragraphs(chapter_text)
    
    # Use cleaned paragraph text for sections
    cleaned_text = "\n\n".join([p["text"] for p in paragraphs])
    sections = process_chapter_sections(cleaned_text)
    
    return {
        "title": chapter_title,
        "paragraphs": paragraphs,
        "sections": sections
    }
