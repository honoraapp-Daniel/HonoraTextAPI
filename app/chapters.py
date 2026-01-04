import os
import json
import re
from supabase import create_client

from app.config import Config
from app.logger import get_logger
from app.utils import retry_on_failure

logger = get_logger(__name__)

# Lazy initialization - only create client when needed
_supabase_client = None

def get_supabase():
    global _supabase_client
    if _supabase_client is None:
        Config.validate_required("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        url = Config.SUPABASE_URL
        if not url.endswith("/"):
            url = f"{url}/"
        _supabase_client = create_client(url, Config.SUPABASE_SERVICE_ROLE_KEY)
    return _supabase_client


def normalize_whitespace(text: str) -> str:
    """
    Normalize excessive whitespace and newlines in text.
    - Replaces multiple consecutive newlines (with or without spaces) to max 2 newlines
    - Cleans up patterns like "\\n \\n\\n \\n" to just "\\n\\n"
    - Trims leading/trailing whitespace from lines
    """
    if not text:
        return text
    
    # First, normalize \n with spaces between them (e.g., "\n  \n \n" -> "\n\n")
    # This regex matches newline followed by optional spaces, repeated
    text = re.sub(r'(\n\s*)+', lambda m: '\n\n' if m.group().count('\n') >= 2 else '\n', text)
    
    # Clean up any remaining excessive newlines (more than 2)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Clean up lines that are just whitespace
    text = re.sub(r'\n\s+\n', '\n\n', text)
    
    # Trim leading/trailing whitespace
    text = text.strip()
    
    return text


# ============================================
# 3NF LOOKUP HELPER FUNCTIONS
# ============================================

def get_or_create_author(name: str) -> str:
    """Get existing author ID or create new author. Returns author UUID."""
    supabase = get_supabase()
    name = name.strip()
    
    # Try to find existing
    result = supabase.table("authors").select("id").eq("name", name).execute()
    if result.data:
        return result.data[0]["id"]
    
    # Create new
    result = supabase.table("authors").insert({"name": name}).execute()
    return result.data[0]["id"]


def get_or_create_language(name: str) -> str:
    """Get existing language ID or create new language. Returns language UUID."""
    supabase = get_supabase()
    name = name.strip()
    
    # Try to find existing
    result = supabase.table("languages").select("id").eq("name", name).execute()
    if result.data:
        return result.data[0]["id"]
    
    # Create new
    result = supabase.table("languages").insert({"name": name}).execute()
    return result.data[0]["id"]


def get_or_create_publisher(name: str) -> str:
    """Get existing publisher ID or create new publisher. Returns publisher UUID."""
    supabase = get_supabase()
    name = name.strip()
    
    # Try to find existing
    result = supabase.table("publishers").select("id").eq("name", name).execute()
    if result.data:
        return result.data[0]["id"]
    
    # Create new
    result = supabase.table("publishers").insert({"name": name}).execute()
    return result.data[0]["id"]


def get_category_id(name: str) -> str:
    """Get category ID by name. Returns None if not found (categories are pre-seeded)."""
    supabase = get_supabase()
    result = supabase.table("categories").select("id").eq("name", name).execute()
    if result.data:
        return result.data[0]["id"]
    return None


def link_book_authors(book_id: str, author_string: str):
    """Parse comma-separated authors and create book_authors relationships."""
    supabase = get_supabase()
    
    if not author_string or author_string == "Unknown":
        return
    
    # Split by comma and process each author
    author_names = [a.strip() for a in author_string.split(",") if a.strip()]
    
    for order, name in enumerate(author_names):
        author_id = get_or_create_author(name)
        # Insert into junction table (ignore if already exists)
        try:
            supabase.table("book_authors").insert({
                "book_id": book_id,
                "author_id": author_id,
                "author_order": order
            }).execute()
        except Exception:
            pass  # Relationship may already exist


# ============================================
# MAIN BOOK CREATION FUNCTION (3NF VERSION)
# ============================================

def create_book_in_supabase(metadata: dict) -> str:
    """
    Creates a new book entry in the 'books' table with full metadata.
    Uses 3NF lookup tables for author, category, language, and publisher.
    
    Args:
        metadata: dict containing title, author, language, and optional fields
        
    Returns:
        book_id (UUID string) of the created book
    """
    supabase = get_supabase()
    
    # Build insert data with only non-None values
    insert_data = {
        "title": metadata.get("title", "Unknown"),
        # Keep author text for backwards compatibility
        "author": metadata.get("author", "Unknown"),
        "language": metadata.get("language", "en"),
    }
    
    # Add optional text fields (keep for backwards compatibility)
    optional_text_fields = [
        "original_language", "publisher",
        "synopsis", "book_of_the_day_quote", "category"
    ]
    
    for field in optional_text_fields:
        value = metadata.get(field)
        # Skip None and empty strings
        if value is not None and value != "":
            insert_data[field] = value
    
    # Handle publishing_year separately (must be integer, not empty string)
    publishing_year = metadata.get("publishing_year")
    if publishing_year is not None and publishing_year != "":
        try:
            insert_data["publishing_year"] = int(publishing_year)
        except (ValueError, TypeError):
            # If it can't be converted to int, skip it
            print(f"[SUPABASE] Warning: Skipping invalid publishing_year: {publishing_year}")
    
    # === 3NF: Add foreign keys ===
    
    # Category FK
    category_name = metadata.get("category")
    if category_name:
        category_id = get_category_id(category_name)
        if category_id:
            insert_data["category_id"] = category_id
    
    # Language FK
    language_name = metadata.get("language")
    if language_name and language_name != "en":
        insert_data["language_id"] = get_or_create_language(language_name)
    elif language_name:
        # Handle common case of "English" or "en"
        insert_data["language_id"] = get_or_create_language(language_name)
    
    # Original Language FK
    original_lang = metadata.get("original_language")
    if original_lang:
        insert_data["original_language_id"] = get_or_create_language(original_lang)
    
    # Publisher FK
    publisher_name = metadata.get("publisher")
    if publisher_name:
        insert_data["publisher_id"] = get_or_create_publisher(publisher_name)
    
    # Insert the book
    result = supabase.table("books").insert(insert_data).execute()
    book_id = result.data[0]["id"]
    
    # Link authors (many-to-many)
    author_string = metadata.get("author")
    if author_string:
        link_book_authors(book_id, author_string)
    
    print(f"[SUPABASE] ✅ Created book with 3NF relations: {metadata.get('title')}")
    
    return book_id


# ============================================
# GEMINI-POWERED BOOK STRUCTURE DETECTION  
# ============================================

import google.generativeai as genai

# Lazy initialization - don't configure at import time!
_gemini_model = None
_configured = False

def get_gemini():
    """Get Gemini model with lazy initialization."""
    global _gemini_model, _configured
    if not _configured:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        genai.configure(api_key=api_key)
        _configured = True
    if _gemini_model is None:
        _gemini_model = genai.GenerativeModel("gemini-2.0-flash")
    return _gemini_model


STRUCTURE_DETECTION_PROMPT = """
You are a book structure analyzer. Given the first pages of a book (including any Contents/Table of Contents page), analyze and return the structure.

IMPORTANT RULES:
1. If the book is an ANTHOLOGY (multiple short stories/novellas), identify each STORY title
2. Chapters belong to stories in anthologies (e.g., "Crazy Paella" has "Chapter 1", "Chapter 2")
3. For regular novels, there are no stories - just chapters
4. Look for the Contents/Table of Contents page to understand the structure
5. Front matter (Introduction, About the Author, etc.) should be marked as "front_matter"

Return ONLY valid JSON in this exact format:
{
  "book_type": "anthology" | "novel" | "textbook",
  "title": "Detected book title if found",
  "author": "Detected author if found",
  "structure": [
    {"type": "front_matter", "title": "About the Author"},
    {"type": "story", "title": "Crazy Paella"},
    {"type": "chapter", "title": "Getting Ready", "parent_story": "Crazy Paella"},
    {"type": "chapter", "title": "The Lorry", "parent_story": "Crazy Paella"},
    {"type": "story", "title": "A Very Unusual Excursion"},
    {"type": "chapter", "title": "The Creature", "parent_story": "A Very Unusual Excursion"}
  ]
}

For a regular novel, use:
{
  "book_type": "novel",
  "title": "The Great Book",
  "author": "John Doe",
  "structure": [
    {"type": "chapter", "title": "The Beginning"},
    {"type": "chapter", "title": "The Middle"}
  ]
}
"""


@retry_on_failure(max_retries=2, delay=3, exceptions=(Exception,))
def detect_book_structure(full_text: str) -> dict:
    """
    Use Gemini to analyze book structure from first pages.
    Returns detected structure including book type, stories, and chapters.
    """
    # Use first ~15000 chars (roughly first 10-15 pages)
    sample_text = full_text[:15000]
    
    model = get_gemini()
    
    logger.info("Detecting book structure with Gemini...")
    
    prompt = f"{STRUCTURE_DETECTION_PROMPT}\n\nAnalyze this book's structure:\n\n{sample_text}"
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=4096
            )
        )
        
        content = response.text
        
        structure = json.loads(content)
        book_type = structure.get('book_type', 'unknown')
        items = structure.get('structure', [])
        
        # Detailed logging for debugging
        logger.info(f"Detected: {book_type} with {len(items)} items")
        
        # Log detected chapter titles for debugging
        chapter_titles = [item.get('title', 'Untitled') for item in items if item.get('type') == 'chapter']
        if chapter_titles:
            logger.debug(f"Chapter titles detected: {chapter_titles[:5]}{'...' if len(chapter_titles) > 5 else ''}")
        
        return structure
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse structure JSON: {e}")
        return {"book_type": "novel", "structure": []}
    except Exception as e:
        logger.error(f"Error detecting book structure: {e}")
        raise


def extract_chapters_smart(full_text: str) -> tuple:
    """
    Smart chapter extraction using GPT-detected structure.
    Returns (stories_list, chapters_list) where stories_list may be empty for novels.
    """
    def normalize_chapter_title(title: str, chapter_index: int) -> str:
        """
        Normalize chapter titles to use Arabic numerals for display while keeping the original
        wording for matching. Examples:
        - "Chapter one: Rhythm" -> "Chapter 1: Rhythm"
        - "Chapter IV - Breath" -> "Chapter 4: Breath"
        - "I. The Hermetic Philosophy" -> "Chapter 1: The Hermetic Philosophy"
        """
        number_words = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
            "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
            "nineteen": 19, "twenty": 20
        }
        roman_map = {
            "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
            "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13,
            "xiv": 14, "xv": 15, "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20
        }

        def roman_to_int(token: str) -> int:
            return roman_map.get(token.lower())

        clean = title.strip()
        # Patterns to catch leading chapter markers
        patterns = [
            r"^chapter\s+(\d+)[\s:\.\-–]+(.*)$",
            r"^chapter\s+([a-z]+)[\s:\.\-–]+(.*)$",
            r"^chapter\s+([ivxlcdm]+)[\s:\.\-–]+(.*)$",
            r"^([ivxlcdm]+)[\s:\.\-–]+(.*)$",
        ]
        number_value = None
        remainder = None

        for pat in patterns:
            m = re.match(pat, clean, flags=re.IGNORECASE)
            if m:
                token = m.group(1)
                remainder = m.group(2).strip()
                if token.isdigit():
                    number_value = int(token)
                elif token.lower() in number_words:
                    number_value = number_words[token.lower()]
                else:
                    number_value = roman_to_int(token)
                break

        if number_value is None:
            # No explicit number parsed; use index and keep original remainder
            remainder = clean
            number_value = chapter_index
        if not remainder:
            remainder = clean

        return f"Chapter {number_value}: {remainder}"

    structure = detect_book_structure(full_text)
    book_type = structure.get("book_type", "novel")
    items = structure.get("structure", [])
    
    stories = []
    chapters = []
    
    # Build story index mapping
    story_titles = [item["title"] for item in items if item.get("type") == "story"]
    story_index_map = {title: idx + 1 for idx, title in enumerate(story_titles)}
    
    # Track current story for chapters
    current_story = None
    chapter_index = 0
    
    for item in items:
        item_type = item.get("type")
        title = item.get("title", "Untitled")
        
        if item_type == "story":
            current_story = title
            story_idx = story_index_map.get(title, len(stories) + 1)
            stories.append({
                "story_index": story_idx,
                "title": title
            })
            # Reset chapter index for new story
            chapter_index = 0
            
        elif item_type == "chapter":
            chapter_index += 1
            parent_story = item.get("parent_story") or current_story
            
            chapters.append({
                "chapter_index": chapter_index,
                "title": title,
                "display_title": normalize_chapter_title(title, chapter_index),
                "parent_story": parent_story,
                "text": ""  # Will be filled by text extraction
            })
        
        elif item_type == "front_matter":
            # Skip front matter for now
            pass
    
    # Now extract actual text for each chapter using detected titles
    chapters_with_text = extract_chapter_text(full_text, chapters, book_type)
    
    print(f"[CHAPTERS] Found {len(stories)} stories and {len(chapters_with_text)} chapters")
    return stories, chapters_with_text


def extract_chapter_text(full_text: str, chapters: list, book_type: str) -> list:
    """
    Extract actual text content for each detected chapter.
    Uses chapter titles as markers to split text.
    """
    if not chapters:
        # Fallback: treat entire book as one chapter
        return [{
            "chapter_index": 1,
            "title": "Full Text",
            "parent_story": None,
            "text": full_text
        }]
    
    # Build regex pattern from chapter titles
    chapter_titles = [ch["title"] for ch in chapters]
    
    # Create markers for splitting
    result_chapters = []
    remaining_text = full_text
    
    for i, chapter in enumerate(chapters):
        title = chapter["title"]
        next_title = chapters[i + 1]["title"] if i + 1 < len(chapters) else None
        
        # Find where this chapter starts
        # Look for various chapter patterns OR the chapter title itself
        # Roman numeral pattern for matching I, II, III, IV, V, VI, VII, VIII, IX, X, XI, XII, XIII, XIV, XV, XVI, etc.
        roman_pattern = r"(?:X{0,3})(?:IX|IV|V?I{0,3})"
        
        chapter_patterns = [
            # Arabic numerals: "Chapter 1: Getting Ready", "Chapter 1. Getting Ready"
            rf"Chapter\s+\d+[:\.\s\-–]+{re.escape(title)}",
            # Word numbers: "Chapter One – Getting Ready" 
            rf"Chapter\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen)[:\.\s\-–]+{re.escape(title)}",
            # Roman numerals WITH Chapter: "Chapter I. Salaam", "Chapter III: The Theory", "CHAPTER IV - Title"
            rf"(?i)Chapter\s+{roman_pattern}[:\.\s\-–]+{re.escape(title)}",
            # Roman numerals WITHOUT Chapter: "I. The Hermetic Philosophy", "II. Breath Is Life"
            rf"(?:^|\n)\s*{roman_pattern}[:\.\s]+{re.escape(title)}",
            # Just the title on its own line
            rf"(?:^|\n){re.escape(title)}(?:\n|$)",
            # FLEXIBLE: Match "Chapter X" where X is the chapter_index (no title required)
            rf"(?:^|\n)Chapter\s+{re.escape(str(chapter['chapter_index']))}[:\.\s\-–]",
            rf"(?:^|\n)Chapter\s+{roman_pattern}[:\.\s\-–]",  # Any Chapter + Roman numeral
            # Chapter 0 triggers: "The life of" or "life of" at start of line
            rf"(?:^|\n)(?:The\s+)?[Ll]ife\s+of\s+.+",
        ]
        
        start_pos = None
        matched_pattern = None
        for idx, pattern in enumerate(chapter_patterns):
            match = re.search(pattern, remaining_text, re.IGNORECASE | re.MULTILINE)
            if match:
                start_pos = match.start()
                matched_pattern = idx
                break
        
        if start_pos is None:
            # Chapter title not found, log and skip
            print(f"[CHAPTERS] ⚠️ Could not find chapter in text: '{title[:50]}...' (searched {len(remaining_text)} chars)")
            continue
        
        # Find where this chapter ends (start of next chapter)
        end_pos = len(remaining_text)
        if next_title:
            for pattern in chapter_patterns:
                pattern = pattern.replace(re.escape(title), re.escape(next_title))
                match = re.search(pattern, remaining_text[start_pos + 1:], re.IGNORECASE | re.MULTILINE)
                if match:
                    end_pos = start_pos + 1 + match.start()
                    break
        
        # Extract chapter text
        chapter_text = remaining_text[start_pos:end_pos].strip()
        
        result_chapters.append({
            "chapter_index": chapter["chapter_index"],
            "title": title,
            "display_title": chapter.get("display_title", title),
            "parent_story": chapter.get("parent_story"),
            "text": chapter_text
        })
        print(f"[CHAPTERS] ✅ Extracted chapter {chapter['chapter_index']}: '{title}' ({len(chapter_text)} chars, pattern #{matched_pattern})")
    
    # CRITICAL FALLBACK: If no chapters were matched, create single chapter with full text
    if not result_chapters:
        print(f"[CHAPTERS] ⚠️ No chapters matched by regex! Creating fallback single chapter.")
        result_chapters = [{
            "chapter_index": 1,
            "title": "Full Text",
            "parent_story": None,
            "text": full_text
        }]
    
    return result_chapters


# Legacy function kept for backwards compatibility
CHAPTER_REGEX = re.compile(
    r"^(CHAPTER|BOOK|PART)\s+([A-Z]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten)",
    re.IGNORECASE
)


def extract_chapter_name(line: str) -> str:
    """
    Extracts just the chapter name from a line like "Chapter eleven. Rhythm."
    Returns just "Rhythm" (or the full line if no name found).
    """
    # Try to extract name after period: "Chapter eleven. Rhythm." -> "Rhythm"
    parts = line.split(".")
    if len(parts) >= 2:
        # Get the part after "Chapter X."
        name = parts[1].strip()
        if name:
            return name.rstrip(".")
    
    # Try to extract name after colon: "Chapter 11: Rhythm" -> "Rhythm"
    if ":" in line:
        name = line.split(":", 1)[1].strip()
        if name:
            return name
    
    # Try to extract name after dash: "Chapter 11 - Rhythm" -> "Rhythm"
    if " - " in line or " – " in line:
        name = re.split(r" [-–] ", line, 1)[-1].strip()
        if name:
            return name
    
    # No name found, return None (just use the chapter number)
    return None


def extract_chapters_from_text(full_text: str):
    """
    Legacy function - uses smart extraction now.
    Returns list of chapters (without story info for backwards compat).
    """
    stories, chapters = extract_chapters_smart(full_text)
    return chapters


def write_stories_to_supabase(book_id: str, stories: list) -> dict:
    """
    DEPRECATED: Stories table was removed in book_nodes migration.
    Use create_book_node() with node_type='treatise' instead.
    """
    logger.warning("[DEPRECATED] write_stories_to_supabase called - stories table no longer exists. Use book_nodes instead.")
    return {}


def write_treatises_to_supabase(book_id: str, treatises: list) -> dict:
    """
    DEPRECATED: Stories table was removed in book_nodes migration.
    Use create_book_node() with node_type='treatise' instead.
    """
    logger.warning("[DEPRECATED] write_treatises_to_supabase called - stories table no longer exists. Use book_nodes instead.")
    return {}


def write_parts_to_supabase(book_id: str, parts: list) -> dict:
    """
    DEPRECATED: Parts table was removed in book_nodes migration.
    Use create_book_node() with node_type='part' instead.
    """
    logger.warning("[DEPRECATED] write_parts_to_supabase called - parts table no longer exists. Use book_nodes instead.")
    return {}


def write_chapters_to_supabase(book_id: str, chapters: list, story_id_map: dict = None, part_id_map: dict = None) -> list:
    """
    Writes chapters to the 'chapters' table, including chapter text.
    Now links to book_nodes via node_id instead of story_id/part_id.
    
    Args:
        book_id: The book UUID
        chapters: List of chapter dicts (with optional node_id)
        story_id_map: DEPRECATED - no longer used (stories table removed)
        part_id_map: DEPRECATED - no longer used (parts table removed)
    
    Returns:
        List of created chapter dicts (including database UUIDs)
    """
    supabase = get_supabase()
    created_chapters = []
    
    for chapter in chapters:
        insert_data = {
            "book_id": book_id,
            "chapter_index": chapter["chapter_index"],
            "title": chapter.get("display_title") or chapter["title"],
            "text": chapter.get("text", "")
        }
        
        # Add node_id if provided (links to book_nodes tree)
        if chapter.get("node_id"):
            insert_data["node_id"] = chapter["node_id"]
        
        result = supabase.table("chapters").insert(insert_data).execute()
        
        if result.data:
            created_chapters.append(result.data[0])
            node_info = f" (node: {chapter.get('node_id', '')[:8]}...)" if chapter.get('node_id') else ""
            print(f"[SUPABASE] Created chapter {chapter.get('chapter_index')}: {chapter['title']}{node_info}")
    
    return created_chapters


def clean_section_text(text: str) -> str:
    """
    Final cleanup for section text before TTS.
    - Removes 'Next:' markers
    - Removes trailing attribution lines
    - Converts IPA tags to plain text (TTS uses default pronunciation)
    - Removes source citations
    
    Args:
        text: Raw section text
        
    Returns:
        Cleaned text ready for TTS
    """
    if not text:
        return ""
    
    # Remove "Next:" at end (with optional whitespace)
    text = re.sub(r'\s*Next:\s*$', '', text, flags=re.IGNORECASE)
    
    # Remove "Previous:" at start
    text = re.sub(r'^Previous:\s*', '', text, flags=re.IGNORECASE)
    
    # Remove book attribution patterns at end of text
    # e.g., "The Kybalion, by Three Initiates," or "Science of Breath, by Yogi Ramacharaka, pseud. William Atkinson."
    text = re.sub(r',?\s+by\s+[A-Z][^.]*(?:,\s+[^.]+)?\.\s*$', '', text)
    
    # Remove standalone attribution lines (book title + author)
    text = re.sub(r'^(?:The\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s+by\s+[A-Z][^,\n]+(?:,\s+[^.\n]+)?\.\s*', '', text, flags=re.MULTILINE)
    
    # Convert IPA tags to plain text (old format with angle brackets)
    # <word<<IPA:/pronunciation/>>> -> word
    text = re.sub(r'<(\w+)<<IPA:[^>]+>>>', r'\1', text)
    
    # Convert IPA tags (new format with pipe separator)
    # <word|IPA:/pronunciation/> -> word
    text = re.sub(r'<(\w+)\|IPA:[^>]+>', r'\1', text)
    
    # Remove any remaining empty angle bracket constructs
    text = re.sub(r'<\s*>', '', text)
    
    # Normalize multiple spaces/newlines
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def split_into_sections_tts(text: str, chapter_title: str, max_chars: int = 250) -> list:
    """
    Split text into TTS-optimized sections.
    
    Section 0: Chapter title only (for TTS to announce the chapter)
    Section 1+: Content split at natural pauses, max ~250 chars
    
    Priority for splitting:
    1. Period (.) - best for TTS, natural sentence end
    2. Comma (,) - if sentence too long, split at comma
    3. Word boundary - absolute last resort
    
    Args:
        text: The chapter text to split (may include title at start)
        chapter_title: The chapter title to use as Section 0
        max_chars: Maximum characters per section (default: 250)
        
    Returns:
        List of sections where index 0 is the title
    """
    if not text or not text.strip():
        # Use just the name portion for Section 0, not "Chapter X: Name"
        name_only = extract_chapter_name(chapter_title) if chapter_title else None
        return [name_only or chapter_title] if chapter_title else []
    
    sections = []
    
    # Section 0 is the chapter name (without "Chapter X:" prefix for cleaner display)
    # The app already shows chapter number separately, so we just want the actual title
    name_only = extract_chapter_name(chapter_title) if chapter_title else chapter_title
    sections.append((name_only or chapter_title).strip())
    
    # Remove chapter title from beginning of text if present
    content = text.strip()
    if content.startswith(chapter_title.strip()):
        content = content[len(chapter_title.strip()):].strip()
    
    # Also try removing common chapter header patterns
    content = re.sub(r'^Chapter\s+[\dIVXLCDM]+[:\.\s\-–]+[^\n]*\n*', '', content, flags=re.IGNORECASE).strip()
    
    if not content:
        return sections
    
    # Normalize whitespace
    content = " ".join(content.split())
    
    # Split by sentences first (period, exclamation, question mark)
    sentences = re.split(r'(?<=[.!?])\s+', content)
    
    current_section = ""
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        
        # If adding this sentence would exceed limit
        if len(current_section) + len(sentence) + 1 > max_chars:
            # Save current section if not empty
            if current_section:
                sections.append(current_section.strip())
                current_section = ""
            
            # If single sentence is too long, try to split at commas
            if len(sentence) > max_chars:
                # Split at commas
                comma_parts = sentence.split(',')
                comma_chunk = ""
                
                for i, part in enumerate(comma_parts):
                    part = part.strip()
                    # Add comma back except for last part
                    if i < len(comma_parts) - 1:
                        part = part + ","
                    
                    if len(comma_chunk) + len(part) + 1 > max_chars:
                        if comma_chunk:
                            sections.append(comma_chunk.strip())
                        comma_chunk = part
                    else:
                        comma_chunk = (comma_chunk + " " + part).strip()
                
                if comma_chunk:
                    # If still too long, split by words as last resort
                    if len(comma_chunk) > max_chars:
                        words = comma_chunk.split()
                        word_chunk = ""
                        for word in words:
                            if len(word_chunk) + len(word) + 1 > max_chars:
                                if word_chunk:
                                    sections.append(word_chunk.strip())
                                word_chunk = word
                            else:
                                word_chunk = (word_chunk + " " + word).strip()
                        if word_chunk:
                            current_section = word_chunk
                    else:
                        current_section = comma_chunk
            else:
                current_section = sentence
        else:
            current_section = (current_section + " " + sentence).strip()
    
    # Don't forget the last section
    if current_section:
        sections.append(current_section.strip())
    
    return sections


def chunk_chapter_text(text: str, max_chars: int = 250) -> list:
    """
    LEGACY: Splits text into chunks of max_chars, respecting sentence boundaries.
    Use split_into_sections_tts() for new code.
    
    Args:
        text: The chapter text to chunk
        max_chars: Maximum characters per chunk (default: 250)
        
    Returns:
        List of text chunks, each <= max_chars
    """
    if not text or not text.strip():
        return []
    
    # Normalize whitespace
    text = " ".join(text.split())
    
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    
    # Split by sentence endings
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    current_chunk = ""
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
            
        # If adding this sentence would exceed limit
        if len(current_chunk) + len(sentence) + 1 > max_chars:
            # Save current chunk if not empty
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            
            # If single sentence is too long, split by words
            if len(sentence) > max_chars:
                words = sentence.split()
                word_chunk = ""
                for word in words:
                    if len(word_chunk) + len(word) + 1 > max_chars:
                        if word_chunk:
                            chunks.append(word_chunk.strip())
                        word_chunk = word
                    else:
                        word_chunk = (word_chunk + " " + word).strip()
                if word_chunk:
                    current_chunk = word_chunk
            else:
                current_chunk = sentence
        else:
            current_chunk = (current_chunk + " " + sentence).strip()
    
    # Don't forget the last chunk
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks


def write_sections_to_supabase(chapter_id: str, sections: list):
    """
    Writes TTS chunks to the 'tts_chunks' table (renamed from 'sections').
    Applies final TTS cleanup to each chunk.
    
    Args:
        chapter_id: UUID of the parent chapter
        sections: List of text chunks (~250 chars each)
    
    Returns:
        List of created chunk IDs
    """
    supabase = get_supabase()
    chunk_ids = []
    
    for index, text in enumerate(sections):
        # Apply final cleanup for TTS
        cleaned_text = clean_section_text(text)
        
        # Skip empty chunks after cleanup
        if not cleaned_text:
            continue
        
        result = supabase.table("tts_chunks").insert({
            "chapter_id": chapter_id,
            "chunk_index": index,  # Renamed from section_index
            "text_ref": cleaned_text,
            "start_ms": None,  # Will be calculated after TTS
            "end_ms": None     # Will be calculated after TTS
        }).execute()
        
        if result.data:
            chunk_ids.append(result.data[0]["id"])
    
    return chunk_ids


def get_chapters_for_book(book_id: str) -> list:
    """
    Fetches all chapters for a book from Supabase.
    
    Args:
        book_id: UUID of the book
        
    Returns:
        List of chapter dicts with id, chapter_index, title, text
    """
    supabase = get_supabase()
    result = supabase.table("chapters").select("*").eq("book_id", book_id).order("chapter_index").execute()
    return result.data


# ============================================
# PARAGRAPH FUNCTIONS (for app display)
# ============================================

# Gemini model already configured above


PARAGRAPH_SYSTEM_PROMPT = """You are a text segmentation engine for Honora audiobook app.

Your job is to split text into NATURAL PARAGRAPHS for display in a mobile app.

CRITICAL RULES:
1. ONLY split at periods (.) - NEVER split at ! or ? or any other character
2. Each paragraph MUST end with a period (.)
3. NEVER split in the middle of a sentence
4. It's OK if paragraphs are long - readability is more important than length
5. Keep semantically related sentences together
6. Start new paragraph only when there's a topic change AND it's after a period

DO NOT consider character count. The ONLY rule is: split at periods when there's a natural topic break.

OUTPUT: Return a JSON object with a "paragraphs" key containing an array of paragraph strings.
Example: {"paragraphs": ["First paragraph with complete sentences.", "Second paragraph continues the narrative.", "Third paragraph with new topic."]}

Return ONLY the JSON object, no markdown, no explanations."""


def extract_chapter_header(text: str) -> tuple:
    """
    Extracts the chapter header (title line) from the beginning of chapter text.
    Returns (header, remaining_text) tuple.
    
    Handles patterns like:
    - "Chapter I. The Hermetic Philosophy The Kybalion..."
    - "Chapter Four. The All The Kybalion..."
    - "I. The Hermetic Philosophy"
    """
    if not text or not text.strip():
        return None, text
    
    # Pattern for chapter headers at the start of text
    # Matches: "Chapter X. Title" or "Chapter X: Title" or just "X. Title" (Roman numerals)
    patterns = [
        # "Chapter" + number/roman + separator + title (greedy to get full header line)
        r'^(Chapter\s+(?:\d+|[IVXLCDM]+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen)[:\.\s\-–][^\n]*)',
        # Roman numeral at start + separator + title
        r'^([IVXLCDM]+[:\.\s]+[^\n]*)',
    ]
    
    text = text.strip()
    
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            header = match.group(1).strip()
            remaining = text[match.end():].strip()
            print(f"[CHAPTERS] Extracted chapter header: '{header[:60]}...'")
            return header, remaining
    
    return None, text


@retry_on_failure(max_retries=2, delay=3, exceptions=(Exception,))
def split_into_paragraphs_gpt(text: str) -> list:
    """
    Uses GPT to split text into natural paragraphs for app display.
    Handles large texts by splitting into chunks to avoid token limits.
    
    IMPORTANT: The chapter header (e.g., "Chapter I. Title...") is always
    extracted as the first paragraph, separate from the content.
    """
    if not text or not text.strip():
        return []
    
    # First, extract chapter header as separate paragraph
    chapter_header, remaining_text = extract_chapter_header(text)
    
    all_paragraphs = []
    
    # Add chapter header as first paragraph if found
    if chapter_header:
        all_paragraphs.append(chapter_header)
    
    # For very short remaining text, return as single paragraph
    if len(remaining_text) <= 350:
        if remaining_text.strip():
            all_paragraphs.append(remaining_text.strip())
        return all_paragraphs
    
    # Chunking strategy: Split text into ~10k character chunks
    # This ensures we stay well within the TPM limits even for large chapters.
    chunk_size = 10000
    chunks = [remaining_text[i:i + chunk_size] for i in range(0, len(remaining_text), chunk_size)]
    
    logger.info(f"Splitting text into paragraphs using Gemini ({len(chunks)} chunks)...")
    
    # Use Gemini for paragraph splitting
    model = get_gemini()
    
    for i, chunk in enumerate(chunks):
        try:
            prompt = f"""{PARAGRAPH_SYSTEM_PROMPT}

Split this text into natural paragraphs:

{chunk}"""
            
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    max_output_tokens=8192
                )
            )
            
            content = response.text
            
            # Parse JSON from response
            result = None
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code block
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(1))
                else:
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        result = json.loads(json_match.group(0))
            
            chunk_paragraphs = []
            if isinstance(result, list):
                chunk_paragraphs = result
            elif isinstance(result, dict):
                for key in ["paragraphs", "segments", "sections", "result"]:
                    if key in result and isinstance(result[key], list):
                        chunk_paragraphs = result[key]
                        break
            
            if chunk_paragraphs:
                all_paragraphs.extend(chunk_paragraphs)
            else:
                # Fallback for this chunk if no list found
                all_paragraphs.append(chunk)
                
        except Exception as e:
            logger.warning(f"Error splitting chunk {i+1}: {e}")
            # Fallback for this specific chunk
            all_paragraphs.extend(fallback_paragraph_split(chunk))
            
    return all_paragraphs



def fallback_paragraph_split(text: str, max_chars: int = 350) -> list:
    """
    Fallback paragraph splitting when GPT fails.
    Splits by paragraph breaks, then by sentences if needed.
    """
    paragraphs = []
    
    # First, split by paragraph breaks
    raw_paragraphs = text.split('\n\n')
    
    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue
            
        if len(para) <= max_chars:
            paragraphs.append(para)
        else:
            # Split long paragraphs ONLY at periods (.) - never at ! or ?
            sentences = re.split(r'(?<=\.)\s+', para)
            current = ""
            for sentence in sentences:
                if len(current) + len(sentence) + 1 > max_chars:
                    if current:
                        paragraphs.append(current.strip())
                    current = sentence
                else:
                    current = (current + " " + sentence).strip()
            if current:
                paragraphs.append(current.strip())
    
    return paragraphs


def write_paragraphs_to_supabase(chapter_id: str, paragraphs: list):
    """
    Writes paragraphs to the 'paragraphs' table.
    
    Args:
        chapter_id: UUID of the parent chapter
        paragraphs: List of paragraph text strings
    """
    supabase = get_supabase()
    
    for index, text in enumerate(paragraphs):
        supabase.table("paragraphs").insert({
            "chapter_id": chapter_id,
            "paragraph_index": index,
            "text": text,
            "start_ms": None,  # Will be linked to sections after TTS
            "end_ms": None
        }).execute()


def ensure_paragraph_0_is_title(paragraphs: list, chapter_title: str) -> list:
    """
    Ensure paragraph index 0 is the chapter title only.
    
    This guarantees that:
    - Paragraph 0 = Chapter title (for display header)
    - Paragraph 1+ = Actual content
    
    Args:
        paragraphs: List of paragraph strings from GPT
        chapter_title: The chapter title to use as Paragraph 0
        
    Returns:
        List of paragraphs with title as first element
    """
    if not paragraphs:
        return [chapter_title] if chapter_title else []
    
    clean_title = chapter_title.strip() if chapter_title else ""
    
    # Check if first paragraph is already the title
    if paragraphs[0].strip() == clean_title:
        return paragraphs
    
    # Check if first paragraph starts with the title (duplicate issue)
    if paragraphs[0].strip().startswith(clean_title):
        # Remove title from first paragraph content
        first_content = paragraphs[0].strip()[len(clean_title):].strip()
        if first_content:
            return [clean_title, first_content] + paragraphs[1:]
        else:
            return [clean_title] + paragraphs[1:]
    
    # Title not present, add it as first paragraph
    return [clean_title] + paragraphs


# ============================================
# PERFECT PARAGRAPH SPLITTING (spaCy + Gemini + Validation)
# ============================================

# Prompt for Gemini to group sentences into paragraphs
PARAGRAPH_GROUPING_PROMPT = """You are organizing sentences into natural reading paragraphs for an audiobook app.

INPUT: A numbered list of sentences from a chapter.
OUTPUT: JSON with paragraph groups (arrays of sentence numbers).

RULES:
1. Group semantically related sentences together
2. Start a new paragraph when the topic changes
3. Dialogue should generally stay with its context
4. Each paragraph should typically be 2-6 sentences
5. It's OK to have longer paragraphs if they're thematically unified
6. Single-sentence paragraphs are only OK for dramatic effect or topic intros
7. EVERY sentence must be included in exactly one paragraph

EXAMPLE INPUT:
1. The sun rose slowly over the mountains.
2. Birds began their morning chorus.
3. Sarah stretched and looked out the window.
4. Meanwhile in the city, traffic was already building.
5. Horns honked impatiently at every intersection.

EXAMPLE OUTPUT:
{"paragraphs": [[1, 2, 3], [4, 5]]}

Return ONLY the JSON object, no markdown, no explanations."""


def split_into_paragraphs_perfect(text: str, chapter_title: str = None) -> list:
    """
    Perfect paragraph splitting using spaCy + GPT + validation.
    
    This is the new approach that GUARANTEES:
    1. No mid-sentence splits (spaCy handles sentence detection)
    2. No single-character paragraphs (validation layer)
    3. Natural paragraph boundaries (GPT semantic grouping)
    
    Args:
        text: Raw chapter text
        chapter_title: Optional chapter title to use as first paragraph
        
    Returns:
        List of paragraph strings
    """
    from app.sentence_detector import (
        detect_sentences,
        sentences_to_numbered_text,
        clean_text_for_sentences,
        merge_short_sentences
    )
    
    if not text or not text.strip():
        return [chapter_title] if chapter_title else []
    
    # Extract chapter header if present
    header, remaining_text = extract_chapter_header(text)
    
    # Use provided title or extracted header
    title_to_use = chapter_title or header or ""
    
    all_paragraphs = []
    if title_to_use:
        all_paragraphs.append(title_to_use.strip())
    
    if not remaining_text or not remaining_text.strip():
        return all_paragraphs
    
    # Clean text before processing
    clean_text = clean_text_for_sentences(remaining_text)
    
    # Step 1: Use spaCy to get guaranteed complete sentences
    logger.info("Step 1: Detecting sentences with spaCy...")
    sentences = detect_sentences(clean_text)
    
    if not sentences:
        # Fallback if no sentences detected
        if remaining_text.strip():
            all_paragraphs.append(remaining_text.strip())
        return all_paragraphs
    
    # Merge very short sentences (handles edge cases)
    sentences = merge_short_sentences(sentences, min_chars=15)
    
    logger.info(f"Found {len(sentences)} sentences")
    
    # Step 2: Use GPT to group sentences into paragraphs
    logger.info("Step 2: Grouping sentences with GPT...")
    paragraph_groups = group_sentences_with_gemini(sentences)
    
    if not paragraph_groups:
        # Fallback: group every 3-5 sentences
        logger.warning("GPT grouping failed, using fallback")
        paragraph_groups = fallback_sentence_grouping(sentences)
    
    # Step 3: Build paragraphs from sentence groups
    logger.info("Step 3: Building paragraphs from groups...")
    for group in paragraph_groups:
        para_sentences = [sentences[i - 1] for i in group if 0 < i <= len(sentences)]
        if para_sentences:
            paragraph_text = " ".join(para_sentences)
            all_paragraphs.append(paragraph_text)
    
    # Step 4: Validate and fix any issues
    logger.info("Step 4: Validating paragraphs...")
    all_paragraphs = validate_and_fix_paragraphs(all_paragraphs, title_to_use)
    
    logger.info(f"Created {len(all_paragraphs)} paragraphs")
    return all_paragraphs


def group_sentences_with_gemini(sentences: list) -> list:
    """
    Use GPT to group sentence indices into paragraph groups.
    
    This approach is more reliable than asking GPT to split raw text
    because we're just asking for groupings of pre-split sentences.
    
    Args:
        sentences: List of sentence strings
        
    Returns:
        List of lists, where each inner list contains sentence indices (1-based)
    """
    from app.sentence_detector import sentences_to_numbered_text
    
    if not sentences:
        return []
    
    # For very short texts, just return all as one paragraph
    if len(sentences) <= 3:
        return [list(range(1, len(sentences) + 1))]
    
    # Generate numbered text for GPT
    numbered_text = sentences_to_numbered_text(sentences)
    
    # Chunking: Process up to 100 sentences at a time
    chunk_size = 100
    if len(sentences) > chunk_size:
        all_groups = []
        offset = 0
        for i in range(0, len(sentences), chunk_size):
            chunk_sentences = sentences[i:i + chunk_size]
            chunk_groups = _gemini_group_chunk(chunk_sentences, offset)
            all_groups.extend(chunk_groups)
            offset += len(chunk_sentences)
        return all_groups
    
    return _gemini_group_chunk(sentences, 0)


@retry_on_failure(max_retries=2, delay=3, exceptions=(Exception,))
def _gemini_group_chunk(sentences: list, offset: int = 0) -> list:
    """
    Internal function to group a chunk of sentences with GPT.
    
    Args:
        sentences: Chunk of sentences to group
        offset: Offset to add to returned indices
        
    Returns:
        List of paragraph groups (adjusted for offset)
    """
    from app.sentence_detector import sentences_to_numbered_text
    
    numbered_text = sentences_to_numbered_text(sentences)
    
    try:
        model = get_gemini()
        
        prompt = f"""{PARAGRAPH_GROUPING_PROMPT}

Here are the sentences to group:

{numbered_text}"""
        
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=4096
            )
        )
        
        content = response.text
        
        # Parse JSON from response
        result = None
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
        
        if result and "paragraphs" in result:
            groups = result["paragraphs"]
            # Adjust indices for offset
            if offset > 0:
                groups = [[idx + offset for idx in group] for group in groups]
            return groups
        
    except Exception as e:
        logger.warning(f"Gemini grouping error: {e}")
    
    # Fallback
    return fallback_sentence_grouping(sentences, offset)


def fallback_sentence_grouping(sentences: list, offset: int = 0) -> list:
    """
    Fallback grouping when Gemini fails.
    Groups sentences in batches of 3-5.
    
    Args:
        sentences: List of sentences
        offset: Offset to add to indices
        
    Returns:
        List of paragraph groups
    """
    if not sentences:
        return []
    
    groups = []
    current_group = []
    target_size = 4  # Aim for 4 sentences per paragraph
    
    for i, sent in enumerate(sentences, 1):
        current_group.append(i + offset)
        
        # Start new paragraph at natural breaks or when we hit target size
        if len(current_group) >= target_size:
            # Check if sentence ends with strong punctuation
            if sent.rstrip().endswith('.'):
                groups.append(current_group)
                current_group = []
    
    # Don't forget remaining sentences
    if current_group:
        groups.append(current_group)
    
    return groups


def validate_and_fix_paragraphs(paragraphs: list, chapter_title: str = None) -> list:
    """
    Quality assurance for paragraphs.
    
    Fixes:
    1. Paragraphs shorter than 20 chars (merge with adjacent)
    2. Paragraphs that don't end with . ! or ? 
    3. Single-word paragraphs
    4. Numeric-only paragraphs
    5. Paragraphs that are just whitespace
    
    Args:
        paragraphs: List of paragraph strings
        chapter_title: Title to preserve as first paragraph
        
    Returns:
        Validated and fixed list of paragraphs
    """
    if not paragraphs:
        return [chapter_title] if chapter_title else []
    
    MIN_CHARS = 20
    
    # First, clean and filter obviously bad paragraphs
    cleaned = []
    for para in paragraphs:
        if not para or not para.strip():
            continue
        
        para = para.strip()
        
        # Skip if numeric only (like "1" or "42")
        if para.replace(".", "").replace(",", "").strip().isdigit():
            continue
        
        # Skip if single letter/character
        if len(para) <= 2:
            continue
        
        cleaned.append(para)
    
    if not cleaned:
        return [chapter_title] if chapter_title else []
    
    # Merge short paragraphs with their neighbors
    result = []
    buffer = ""
    
    title_normalized = chapter_title.strip().lower() if chapter_title else ""
    
    for i, para in enumerate(cleaned):
        # Never merge the title
        if para.strip().lower() == title_normalized:
            if buffer:
                result.append(buffer)
                buffer = ""
            result.append(para)
            continue
        
        # If paragraph is too short, buffer it
        if len(para) < MIN_CHARS:
            if buffer:
                buffer = buffer + " " + para
            else:
                buffer = para
        else:
            # Paragraph is good length
            if buffer:
                # Merge buffer with this paragraph
                result.append(buffer + " " + para)
                buffer = ""
            else:
                result.append(para)
    
    # Handle remaining buffer
    if buffer:
        if result and result[-1].strip().lower() != title_normalized:
            result[-1] = result[-1] + " " + buffer
        else:
            result.append(buffer)
    
    return result


def split_into_sections_perfect(text: str, chapter_title: str, max_chars: int = 250) -> list:
    """
    Split text into TTS-optimized sections using spaCy.
    
    This replaces the old character-based splitting with sentence-aware splitting.
    
    Section 0: Chapter title only (for TTS to announce)
    Section 1+: Content split at sentence boundaries, max ~250 chars
    
    Args:
        text: The chapter text
        chapter_title: The chapter title for Section 0
        max_chars: Maximum characters per section
        
    Returns:
        List of sections
    """
    from app.sentence_detector import (
        detect_sentences,
        split_long_sentence,
        clean_text_for_sentences
    )
    
    if not text or not text.strip():
        # Use just the name portion for Section 0, not "Chapter X: Name"
        name_only = extract_chapter_name(chapter_title) if chapter_title else None
        return [name_only or chapter_title] if chapter_title else []
    
    sections = []
    
    # Section 0 is the chapter name (without "Chapter X:" prefix for cleaner display)
    name_only = extract_chapter_name(chapter_title) if chapter_title else chapter_title
    sections.append((name_only or chapter_title or "Chapter").strip())
    
    # Remove chapter title from beginning if present
    content = text.strip()
    if chapter_title and content.startswith(chapter_title.strip()):
        content = content[len(chapter_title.strip()):].strip()
    
    # Also try removing common chapter header patterns
    content = re.sub(r'^Chapter\s+[\dIVXLCDM]+[:\.\s\-–]+[^\n]*\n*', '', content, flags=re.IGNORECASE).strip()
    
    if not content:
        return sections
    
    # Clean and get sentences
    content = clean_text_for_sentences(content)
    sentences = detect_sentences(content)
    
    if not sentences:
        # Fallback: just split by character count
        chunks = [content[i:i+max_chars] for i in range(0, len(content), max_chars)]
        return sections + chunks
    
    # Build sections by combining sentences up to max_chars
    current_section = ""
    
    for sentence in sentences:
        # Handle very long sentences
        if len(sentence) > max_chars:
            # Save current section if not empty
            if current_section:
                sections.append(current_section.strip())
                current_section = ""
            
            # Split the long sentence
            sub_chunks = split_long_sentence(sentence, max_chars)
            sections.extend(sub_chunks)
            continue
        
        # Would adding this sentence exceed the limit?
        if len(current_section) + len(sentence) + 1 > max_chars:
            if current_section:
                sections.append(current_section.strip())
            current_section = sentence
        else:
            current_section = (current_section + " " + sentence).strip() if current_section else sentence
    
    # Don't forget the last section
    if current_section:
        sections.append(current_section.strip())
    
    # Final validation: remove any empty sections
    sections = [s for s in sections if s and s.strip()]
    
    return sections


# ============================================
# BOOK NODES FUNCTIONS (Tree-based structure)
# ============================================

# Valid node types (must match Supabase CHECK constraint)
VALID_NODE_TYPES = [
    # Front matter
    'front_matter', 'toc', 'preface', 'foreword', 'introduction',
    'dedication', 'acknowledgments', 'prologue', 'authors_note',
    # Main content
    'part', 'book', 'volume', 'section', 'chapter', 'subsection',
    'main_work', 'treatise', 'fragment', 'letter', 'discourse',
    'essay', 'sermon', 'dialogue', 'meditation',
    # Back matter
    'epilogue', 'appendix', 'glossary', 'bibliography', 'index',
    'back_matter', 'notes', 'afterword', 'postscript', 'endnotes'
]


def generate_order_key(book_id: str, parent_id: str = None) -> str:
    """
    Generate the next order_key for a node at a given level.
    
    Args:
        book_id: The book UUID
        parent_id: Parent node UUID (None for root level)
    
    Returns:
        Order key string (e.g., "0001", "0002.0001")
    """
    supabase = get_supabase()
    
    # Get parent's order_key as prefix
    prefix = ""
    if parent_id:
        parent_result = supabase.table("book_nodes").select("order_key").eq("id", parent_id).execute()
        if parent_result.data:
            prefix = parent_result.data[0]["order_key"] + "."
    
    # Find highest existing key at this level
    if parent_id:
        existing = supabase.table("book_nodes").select("order_key").eq("book_id", book_id).eq("parent_id", parent_id).execute()
    else:
        existing = supabase.table("book_nodes").select("order_key").eq("book_id", book_id).is_("parent_id", "null").execute()
    
    if not existing.data:
        next_num = 1
    else:
        # Find max order_key and increment
        max_key = max(row["order_key"] for row in existing.data)
        last_segment = max_key.split(".")[-1]
        next_num = int(last_segment) + 1
    
    return f"{prefix}{next_num:04d}"


def create_book_node(
    book_id: str,
    node_type: str,
    display_title: str,
    parent_id: str = None,
    source_title: str = None,
    order_key: str = None,
    exclude_from_frontend: bool = False,
    exclude_from_audio: bool = False,
    has_content: bool = True,
    confidence: float = 1.0
) -> dict:
    """
    Create a book_node in the tree structure.
    
    Args:
        book_id: The book UUID
        node_type: One of VALID_NODE_TYPES (preface, chapter, part, etc.)
        display_title: What the user sees
        parent_id: Parent node UUID (None for root nodes)
        source_title: Raw title from source (optional)
        order_key: Explicit key (auto-generated if None)
        exclude_from_frontend: Hide from app navigation
        exclude_from_audio: Skip during TTS
        has_content: Does this node have paragraphs?
        confidence: AI detection confidence (0-1)
    
    Returns:
        Created node dict with id
    """
    supabase = get_supabase()
    
    # Validate node_type
    if node_type not in VALID_NODE_TYPES:
        raise ValueError(f"Invalid node_type: {node_type}. Must be one of {VALID_NODE_TYPES}")
    
    # Auto-generate order_key if not provided
    if not order_key:
        order_key = generate_order_key(book_id, parent_id)
    
    insert_data = {
        "book_id": book_id,
        "parent_id": parent_id,
        "node_type": node_type,
        "order_key": order_key,
        "display_title": display_title,
        "source_title": source_title or display_title,
        "exclude_from_frontend": exclude_from_frontend,
        "exclude_from_audio": exclude_from_audio,
        "has_content": has_content,
        "confidence": confidence
    }
    
    result = supabase.table("book_nodes").insert(insert_data).execute()
    
    if result.data:
        node = result.data[0]
        logger.info(f"[BOOK_NODES] Created {node_type}: {display_title} (order: {order_key})")
        return node
    
    raise Exception(f"Failed to create book_node: {display_title}")


def link_node_paragraphs(node_id: str, paragraph_ids: list) -> int:
    """
    Link paragraphs to a book_node.
    
    Args:
        node_id: The book_node UUID
        paragraph_ids: List of paragraph UUIDs in order
    
    Returns:
        Number of links created
    """
    supabase = get_supabase()
    
    for position, para_id in enumerate(paragraph_ids):
        supabase.table("book_node_paragraphs").insert({
            "node_id": node_id,
            "paragraph_id": para_id,
            "position_in_node": position
        }).execute()
    
    logger.info(f"[BOOK_NODES] Linked {len(paragraph_ids)} paragraphs to node {node_id[:8]}")
    return len(paragraph_ids)


def link_paragraph_tts_chunks(paragraph_id: str, tts_chunk_ids: list) -> int:
    """
    Link TTS chunks to a paragraph.
    
    Args:
        paragraph_id: The paragraph UUID
        tts_chunk_ids: List of TTS chunk UUIDs in order
    
    Returns:
        Number of links created
    """
    supabase = get_supabase()
    
    for position, chunk_id in enumerate(tts_chunk_ids):
        supabase.table("paragraph_tts_chunks").insert({
            "paragraph_id": paragraph_id,
            "tts_chunk_id": chunk_id,
            "position_in_paragraph": position
        }).execute()
    
    return len(tts_chunk_ids)


def get_book_nodes(book_id: str, include_hidden: bool = False) -> list:
    """
    Fetch all book_nodes for a book in order.
    
    Args:
        book_id: The book UUID
        include_hidden: Include nodes with exclude_from_frontend=True
    
    Returns:
        List of node dicts ordered by order_key
    """
    supabase = get_supabase()
    
    query = supabase.table("book_nodes").select("*").eq("book_id", book_id).order("order_key")
    
    if not include_hidden:
        query = query.eq("exclude_from_frontend", False)
    
    result = query.execute()
    return result.data


def get_node_content(node_id: str) -> dict:
    """
    Get full content for a node (paragraphs and TTS chunks).
    
    Args:
        node_id: The book_node UUID
    
    Returns:
        Dict with node info, paragraphs, and tts_chunks
    """
    supabase = get_supabase()
    
    # Get node
    node = supabase.table("book_nodes").select("*").eq("id", node_id).single().execute()
    if not node.data:
        return None
    
    # Get paragraphs
    paragraphs = supabase.table("book_node_paragraphs").select(
        "position_in_node, paragraphs(id, text, paragraph_index)"
    ).eq("node_id", node_id).order("position_in_node").execute()
    
    return {
        "node": node.data,
        "paragraphs": [p["paragraphs"] for p in paragraphs.data] if paragraphs.data else []
    }


def map_content_type_to_node_type(content_type: str) -> str:
    """
    Map legacy content_type values to new node_type values.
    
    Args:
        content_type: Legacy type ('prefatory', 'chapter', 'book', 'appendix', 'treatise')
    
    Returns:
        New node_type value
    """
    mapping = {
        'prefatory': 'preface',       # Most common prefatory type
        'chapter': 'chapter',
        'book': 'book',               # "Book I", "Book II" style
        'appendix': 'appendix',
        'treatise': 'treatise',
        'introduction': 'introduction',
        'preface': 'preface',
        'foreword': 'foreword',
        'prologue': 'prologue',
        'epilogue': 'epilogue'
    }
    return mapping.get(content_type, 'chapter')
