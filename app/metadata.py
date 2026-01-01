"""
Metadata extraction module for Honora.
Uses Gemini for synopsis/category, OpenAI GPT for PDF metadata extraction.
"""
import json
import os
import re
from openai import OpenAI

# Lazy initialization - only create clients when needed
_openai_client = None
_gemini_client = None

def get_openai():
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY must be set")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client

def get_gemini():
    """Get Google Gemini client for synopsis/category generation."""
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY must be set")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client

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
    Falls back to Gemini for any fields that return as "Unknown".
    
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
        metadata = {
            "title": result.get("title") or "Unknown",
            "author": result.get("author") or "Unknown",
            "language": result.get("language") or "English",
            "original_language": result.get("original_language"),
            "publisher": result.get("publisher"),
            "publishing_year": result.get("publishing_year"),
            "synopsis": result.get("synopsis"),
            "book_of_the_day_quote": result.get("book_of_the_day_quote"),
            "category": result.get("category"),
            "translated": False,
            "explicit": False
        }
        
        # Use Gemini fallback for any "Unknown" fields
        if metadata["title"] == "Unknown" or metadata["author"] == "Unknown":
            print("[METADATA] GPT returned 'Unknown' for title/author - trying Gemini fallback...")
            gemini_metadata = extract_metadata_with_gemini(first_pages_text)
            
            if gemini_metadata:
                if metadata["title"] == "Unknown" and gemini_metadata.get("title"):
                    metadata["title"] = gemini_metadata["title"]
                    print(f"[METADATA] ✅ Gemini found title: {metadata['title']}")
                
                if metadata["author"] == "Unknown" and gemini_metadata.get("author"):
                    metadata["author"] = gemini_metadata["author"]
                    print(f"[METADATA] ✅ Gemini found author: {metadata['author']}")
                
                # Fill in other missing fields
                if not metadata.get("publisher") and gemini_metadata.get("publisher"):
                    metadata["publisher"] = gemini_metadata["publisher"]
                
                if not metadata.get("publishing_year") and gemini_metadata.get("publishing_year"):
                    metadata["publishing_year"] = gemini_metadata["publishing_year"]
        
        return metadata
    
    # If GPT fails completely, try Gemini
    print("[METADATA] GPT failed to extract - using Gemini fallback...")
    gemini_metadata = extract_metadata_with_gemini(first_pages_text)
    if gemini_metadata:
        return gemini_metadata
    
    return {
        "title": "Unknown", 
        "author": "Unknown", 
        "language": "English",
        "translated": False,
        "explicit": False
    }


def extract_metadata_with_gemini(first_pages_text: str) -> dict:
    """
    Fallback metadata extraction using Gemini when GPT returns "Unknown".
    
    Args:
        first_pages_text: Text from first pages of the book
        
    Returns:
        dict with metadata fields
    """
    try:
        client = get_gemini()
        
        prompt = f"""
{METADATA_SYSTEM_PROMPT}

Extract metadata from this book text:

{first_pages_text[:8000]}

Return ONLY valid JSON with all metadata fields.
"""
        
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[prompt]
        )
        
        # Extract text from response
        content = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text:
                content += part.text
        
        result = extract_json_from_text(content)
        
        if result:
            return {
                "title": result.get("title") or "Unknown",
                "author": result.get("author") or "Unknown",
                "language": result.get("language") or "English",
                "original_language": result.get("original_language"),
                "publisher": result.get("publisher"),
                "publishing_year": result.get("publishing_year"),
                "synopsis": result.get("synopsis"),
                "book_of_the_day_quote": result.get("book_of_the_day_quote"),
                "category": result.get("category"),
                "translated": False,
                "explicit": False
            }
    except Exception as e:
        print(f"[METADATA] Gemini fallback failed: {e}")
    
    return None


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
    # First, try to get category from URL (most reliable for sacred-texts.com)
    url_subcategory, url_category = get_category_from_url(source_url)
    
    print(f"[METADATA] Source URL: {source_url}")
    print(f"[METADATA] URL-based category: {url_subcategory} -> {url_category}")
    
    # Prepare the prompt with URL hint if available
    url_hint = ""
    if url_subcategory:
        url_hint = f"\n\nIMPORTANT: This book is from the '{url_subcategory}' section. Use category '{url_category}'."
    
    prompt = f"""
{SYNOPSIS_SYSTEM_PROMPT}

Generate metadata for this book based on the following chapter content:

{chapter_content[:6000]}
{url_hint}

Return ONLY valid JSON with synopsis, category, subcategory, and a real quote from the text.
"""

    try:
        print(f"[METADATA] Calling Gemini 2.0 Flash for synopsis generation...")
        print(f"[METADATA] Chapter content length: {len(chapter_content)} chars")
        print(f"[METADATA] URL hint: {url_hint[:100] if url_hint else 'None'}")
        
        # Use Gemini 2.0 Flash for text generation
        client = get_gemini()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[prompt]
        )
        
        # Extract text from response
        content = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text:
                content += part.text
        
        print(f"[METADATA] Gemini response received: {len(content)} chars")
        
        result = extract_json_from_text(content)
        
        if result:
            print(f"[METADATA] ✅ JSON parsed successfully")
            print(f"[METADATA] Synopsis: {result.get('synopsis', '')[:100]}...")
            print(f"[METADATA] Gemini category: {result.get('category')}")
            
            # ALWAYS use URL-based category if available (most accurate for sacred-texts.com)
            # Only fall back to Gemini's category if no URL category
            if url_category:
                final_category = url_category
                print(f"[METADATA] Using URL-based category: {final_category}")
            else:
                final_category = result.get("category") or "Spirituality & Religion"
                print(f"[METADATA] Using Gemini category: {final_category}")
            
            return {
                "synopsis": result.get("synopsis"),
                "category": final_category,
                "subcategory": url_subcategory or result.get("subcategory"),
                "book_of_the_day_quote": result.get("book_of_the_day_quote")
            }
        else:
            print(f"[METADATA] ❌ Failed to parse JSON from response: {content[:200]}")
    except Exception as e:
        import traceback
        print(f"[METADATA] ❌ Error generating synopsis: {e}")
        print(f"[METADATA] Traceback: {traceback.format_exc()}")
    
    # Fallback with URL-based category if available
    print(f"[METADATA] Using fallback - category: {url_category or 'Spirituality & Religion'}")
    return {
        "synopsis": None,
        "category": url_category or "Spirituality & Religion",
        "subcategory": url_subcategory,
        "book_of_the_day_quote": None
    }

