"""
Metadata extraction module for Honora.
Uses GPT to extract book title, author, and additional metadata from PDF text.
"""
import json
import os
import re
from openai import OpenAI

# Lazy initialization - only create client when needed
_openai_client = None

def get_openai():
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY must be set")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client

METADATA_SYSTEM_PROMPT = """
You are a book metadata extractor for Honora audiobook platform. Given text from the first pages of a book, extract comprehensive metadata.

Return ONLY valid JSON in this exact format:
{
  "title": "Book Title Here",
  "author": "Author Name Here",
  "language": "en",
  "original_language": "en",
  "publisher": "Original Publisher Name",
  "publishing_year": 1925,
  "synopsis": "A compelling 2-3 sentence summary of the book's plot and themes.",
  "book_of_the_day_quote": "A memorable, inspiring quote from the book that captures its essence.",
  "category": "Genre Category"
}

RULES:
- If there are multiple authors, separate them with commas.
- If you cannot find a field, use null (not "Unknown").
- Language and original_language should be FULL language names (e.g. "English", "Danish", "German", "French", "Spanish"), NOT ISO codes.
- Synopsis should be engaging and suitable for audiobook marketing.
- book_of_the_day_quote should be a real quote from the text if available, otherwise a thematic quote.
- Category should be one of: Fiction, Non-Fiction, Mystery, Romance, Fantasy, Science Fiction, Biography, Self-Help, History, Philosophy, Business, Classic Literature, Children, Young Adult, Poetry, Religion, Science

IMPORTANT FOR PUBLISHER:
- Find the ORIGINAL publisher from the book's FIRST EDITION, not the PDF creator or digital publisher.
- Ignore publishers like "YOGeBooks", "Project Gutenberg", "eBook publisher" etc.
- For classic books, research the original publisher (e.g., "The Yogi Publication Society" for The Kybalion in 1908).
- If you cannot determine the original publisher, use null.
"""


def extract_json_from_text(text: str) -> dict:
    """Extract JSON from potentially messy LLM response."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try to extract from markdown code block
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Try to find raw JSON object
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    
    return None


def extract_book_metadata(first_pages_text: str) -> dict:
    """
    Uses GPT to extract comprehensive metadata from the first pages of a book.
    
    Args:
        first_pages_text: Combined text from the first few pages of the PDF
        
    Returns:
        dict with all metadata fields
    """
    prompt = f"""
Extract comprehensive book metadata from this text:

{first_pages_text[:8000]}  # Limit to avoid token limits

Return JSON with all metadata fields.
"""

    response = get_openai().chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": METADATA_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    content = response.choices[0].message.content
    result = extract_json_from_text(content)
    
    if result:
        return {
            "title": result.get("title") or "Unknown",
            "author": result.get("author") or "Unknown",
            "language": result.get("language") or "en",
            "original_language": result.get("original_language"),
            "publisher": result.get("publisher"),
            "publishing_year": result.get("publishing_year"),
            "synopsis": result.get("synopsis"),
            "book_of_the_day_quote": result.get("book_of_the_day_quote"),
            "category": result.get("category")
        }
    
    return {"title": "Unknown", "author": "Unknown", "language": "en"}


# URL path to category mapping for sacred-texts.com
SACRED_TEXTS_CATEGORIES = {
    "/hin/": "Hinduism",
    "/bud/": "Buddhism",
    "/egy/": "Egyptian Mythology",
    "/isl/": "Islam",
    "/jud/": "Judaism",
    "/chr/": "Christianity",
    "/neu/": "Legends & Sagas",
    "/ane/": "Ancient Near East",
    "/cla/": "Classics",
    "/gno/": "Gnosticism",
    "/eso/": "Esoteric & Occult",
    "/the/": "Theosophy",
    "/sro/": "Sub Rosa",
    "/pag/": "Paganism",
    "/nos/": "Prophecy",
    "/pro/": "Prophecy",
    "/ufo/": "Paranormal",
    "/atl/": "Atlantis & Lost Civilizations",
    "/earth/": "Earth Mysteries",
    "/time/": "Philosophy",
    "/sex/": "Sacred Sexuality",
    "/tantra/": "Tantra",
    "/jai/": "Jainism",
    "/zor/": "Zoroastrianism",
    "/tao/": "Taoism",
    "/shi/": "Shinto",
    "/sikh/": "Sikhism",
    "/baha/": "Baha'i",
    "/afr/": "African Traditional",
    "/aus/": "Australian Aboriginal",
    "/nam/": "Native American",
    "/pac/": "Pacific Traditions",
    "/sha/": "Shamanism",
    "/phi/": "Philosophy",
    "/aor/": "Alchemy",
    "/mas/": "Freemasonry",
    "/ros/": "Rosicrucianism",
    "/oto/": "Thelema",
    "/grim/": "Grimoires",
    "/tarot/": "Tarot",
    "/ast/": "Astrology",
    "/fort/": "Fortean",
    "/evil/": "Evil & Demonology",
    "/sym/": "Symbolism",
}

# Map specific categories to Honora's standard categories
HONORA_CATEGORY_MAP = {
    "Hinduism": "Spirituality & Religion",
    "Buddhism": "Spirituality & Religion",
    "Egyptian Mythology": "History & Mythology",
    "Islam": "Spirituality & Religion",
    "Judaism": "Spirituality & Religion",
    "Christianity": "Spirituality & Religion",
    "Legends & Sagas": "History & Mythology",
    "Ancient Near East": "History & Mythology",
    "Classics": "Classic Literature",
    "Gnosticism": "Spirituality & Religion",
    "Esoteric & Occult": "Spirituality & Religion",
    "Theosophy": "Spirituality & Religion",
    "Sub Rosa": "Spirituality & Religion",
    "Paganism": "Spirituality & Religion",
    "Prophecy": "Spirituality & Religion",
    "Paranormal": "Non-Fiction",
    "Atlantis & Lost Civilizations": "History & Mythology",
    "Earth Mysteries": "Non-Fiction",
    "Philosophy": "Philosophy",
    "Sacred Sexuality": "Spirituality & Religion",
    "Tantra": "Spirituality & Religion",
    "Jainism": "Spirituality & Religion",
    "Zoroastrianism": "Spirituality & Religion",
    "Taoism": "Spirituality & Religion",
    "Shinto": "Spirituality & Religion",
    "Sikhism": "Spirituality & Religion",
    "Baha'i": "Spirituality & Religion",
    "African Traditional": "Spirituality & Religion",
    "Australian Aboriginal": "Spirituality & Religion",
    "Native American": "Spirituality & Religion",
    "Pacific Traditions": "Spirituality & Religion",
    "Shamanism": "Spirituality & Religion",
    "Alchemy": "Spirituality & Religion",
    "Freemasonry": "Spirituality & Religion",
    "Rosicrucianism": "Spirituality & Religion",
    "Thelema": "Spirituality & Religion",
    "Grimoires": "Spirituality & Religion",
    "Tarot": "Spirituality & Religion",
    "Astrology": "Spirituality & Religion",
    "Fortean": "Non-Fiction",
    "Evil & Demonology": "Spirituality & Religion",
    "Symbolism": "Non-Fiction",
}


SYNOPSIS_SYSTEM_PROMPT = """
You are a book synopsis writer for Honora audiobook platform. Given sample text from a book's chapters, create compelling metadata.

Return ONLY valid JSON in this exact format:
{
  "synopsis": "A compelling 2-3 sentence summary of the book's themes and content. Should be engaging for audiobook marketing.",
  "category": "One of the valid categories",
  "subcategory": "More specific genre if known",
  "book_of_the_day_quote": "A memorable, inspiring quote from the provided text that captures the book's essence."
}

VALID CATEGORIES (choose one):
- Spirituality & Religion
- Philosophy
- History & Mythology
- Classic Literature
- Non-Fiction
- Self-Help
- Fiction
- Poetry
- Biography
- Science

RULES:
- Synopsis should capture the book's essence and appeal to listeners
- Quote must be an ACTUAL quote from the provided text, not made up
- If the text is spiritual/religious, focus on the wisdom and teachings
- Keep synopsis under 250 characters for app display
"""


def get_category_from_url(source_url: str) -> tuple:
    """
    Extract category from sacred-texts.com URL path.
    
    Returns:
        tuple: (specific_category, honora_category)
    """
    if not source_url:
        return None, None
    
    for path, specific_cat in SACRED_TEXTS_CATEGORIES.items():
        if path in source_url.lower():
            honora_cat = HONORA_CATEGORY_MAP.get(specific_cat, "Spirituality & Religion")
            return specific_cat, honora_cat
    
    return None, None


def generate_synopsis_and_category(chapter_content: str, source_url: str = None) -> dict:
    """
    Generate synopsis, category, and quote from chapter content using GPT.
    
    For sacred-texts.com, also uses URL path to help determine category.
    
    Args:
        chapter_content: Sample text from first few chapters
        source_url: Original source URL (for category hints)
        
    Returns:
        dict with synopsis, category, subcategory, book_of_the_day_quote
    """
    # First, try to get category from URL
    url_subcategory, url_category = get_category_from_url(source_url)
    
    # Prepare the prompt with URL hint if available
    url_hint = ""
    if url_subcategory:
        url_hint = f"\n\nHINT: This book is from the '{url_subcategory}' section, so the category is likely '{url_category}'."
    
    prompt = f"""
Generate metadata for this book based on the following chapter content:

{chapter_content[:6000]}
{url_hint}

Return JSON with synopsis, category, subcategory, and a real quote from the text.
"""

    try:
        response = get_openai().chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYNOPSIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content
        result = extract_json_from_text(content)
        
        if result:
            # Use URL-based category if GPT didn't provide one or if we have a URL hint
            final_category = result.get("category")
            if not final_category or (url_category and url_category != "Spirituality & Religion"):
                final_category = url_category or "Spirituality & Religion"
            
            return {
                "synopsis": result.get("synopsis"),
                "category": final_category,
                "subcategory": url_subcategory or result.get("subcategory"),
                "book_of_the_day_quote": result.get("book_of_the_day_quote")
            }
    except Exception as e:
        print(f"[METADATA] Error generating synopsis: {e}")
    
    # Fallback with URL-based category if available
    return {
        "synopsis": None,
        "category": url_category or "Spirituality & Religion",
        "subcategory": url_subcategory,
        "book_of_the_day_quote": None
    }

