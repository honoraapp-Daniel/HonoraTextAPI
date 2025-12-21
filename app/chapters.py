import os
import json
import re
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Lazy initialization - only create client when needed
_supabase_client = None

def get_supabase():
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


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
        "original_language", "publisher", "publishing_year",
        "synopsis", "book_of_the_day_quote", "category"
    ]
    
    for field in optional_text_fields:
        if metadata.get(field) is not None:
            insert_data[field] = metadata[field]
    
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
    


# ============================================
# GPT-POWERED BOOK STRUCTURE DETECTION
# ============================================

from openai import OpenAI

_openai_client = None

def get_openai():
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY must be set")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


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


def detect_book_structure(full_text: str) -> dict:
    """
    Use GPT to analyze book structure from first pages.
    Returns detected structure including book type, stories, and chapters.
    """
    # Use first ~15000 chars (roughly first 10-15 pages)
    sample_text = full_text[:15000]
    
    client = get_openai()
    
    print("[CHAPTERS] Detecting book structure with GPT...")
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": STRUCTURE_DETECTION_PROMPT},
            {"role": "user", "content": f"Analyze this book's structure:\n\n{sample_text}"}
        ],
        response_format={"type": "json_object"}
    )
    
    content = response.choices[0].message.content
    
    try:
        structure = json.loads(content)
        print(f"[CHAPTERS] ✅ Detected: {structure.get('book_type', 'unknown')} with {len(structure.get('structure', []))} items")
        return structure
    except json.JSONDecodeError:
        print("[CHAPTERS] ⚠️ Failed to parse structure, using fallback")
        return {"book_type": "novel", "structure": []}


def extract_chapters_smart(full_text: str) -> tuple:
    """
    Smart chapter extraction using GPT-detected structure.
    Returns (stories_list, chapters_list) where stories_list may be empty for novels.
    """
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
        # Look for "Chapter X" pattern OR the chapter title itself
        chapter_patterns = [
            rf"Chapter\s+\d+[:\.\s\-–]+{re.escape(title)}",  # "Chapter 1: Getting Ready"
            rf"Chapter\s+\w+[:\.\s\-–]+{re.escape(title)}",  # "Chapter One – Getting Ready"
            rf"(?:^|\n){re.escape(title)}(?:\n|$)",  # Just the title on its own line
        ]
        
        start_pos = None
        for pattern in chapter_patterns:
            match = re.search(pattern, remaining_text, re.IGNORECASE | re.MULTILINE)
            if match:
                start_pos = match.start()
                break
        
        if start_pos is None:
            # Chapter title not found, skip
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
            "parent_story": chapter.get("parent_story"),
            "text": chapter_text
        })
    
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
    Writes stories to the 'stories' table for anthology books.
    Returns mapping of story_title -> story_id for linking chapters.
    """
    if not stories:
        return {}
    
    supabase = get_supabase()
    story_id_map = {}
    
    for story in stories:
        result = supabase.table("stories").insert({
            "book_id": book_id,
            "story_index": story["story_index"],
            "title": story["title"]
        }).execute()
        
        story_id = result.data[0]["id"]
        story_id_map[story["title"]] = story_id
        print(f"[SUPABASE] Created story: {story['title']}")
    
    return story_id_map


def write_chapters_to_supabase(book_id: str, chapters: list, story_id_map: dict = None) -> list:
    """
    Writes chapters to the 'chapters' table, including chapter text.
    Optionally links to stories for anthology books.
    
    Returns:
        List of created chapter dicts (including database UUIDs)
    """
    supabase = get_supabase()
    story_id_map = story_id_map or {}
    created_chapters = []
    
    for chapter in chapters:
        parent_story = chapter.get("parent_story")
        story_id = story_id_map.get(parent_story) if parent_story else None
        
        insert_data = {
            "book_id": book_id,
            "chapter_index": chapter["chapter_index"],
            "title": chapter["title"],
            "text": chapter.get("text", "")
        }
        
        if story_id:
            insert_data["story_id"] = story_id
        
        result = supabase.table("chapters").insert(insert_data).execute()
        
        if result.data:
            created_chapters.append(result.data[0])
            print(f"[SUPABASE] Created chapter {chapter.get('chapter_index')}: {chapter['title']}" + 
                  (f" (story: {parent_story})" if parent_story else ""))
    
    return created_chapters


def chunk_chapter_text(text: str, max_chars: int = 250) -> list:
    """
    Splits text into chunks of max_chars, respecting sentence boundaries.
    Falls back to word boundaries if a sentence exceeds max_chars.
    
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
    import re
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
    Writes sections to the 'sections' table.
    
    Args:
        chapter_id: UUID of the parent chapter
        sections: List of text chunks
    """
    supabase = get_supabase()
    
    for index, text in enumerate(sections):
        supabase.table("sections").insert({
            "chapter_id": chapter_id,
            "section_index": index,
            "text_ref": text,
            "start_ms": None,  # Will be calculated after TTS
            "end_ms": None     # Will be calculated after TTS
        }).execute()


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

from openai import OpenAI

# Lazy OpenAI client initialization
_openai_client = None

def get_openai():
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY must be set")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


PARAGRAPH_SYSTEM_PROMPT = """You are a text segmentation engine for Honora audiobook app.

Your job is to split text into NATURAL PARAGRAPHS for display in a mobile app.
These paragraphs will be used for:
- Time-synchronized transcripts (like Apple Podcasts)
- Copy-to-notes feature
- Tap-to-play from specific point

RULES:
1. Each paragraph should be 150-350 characters (optimal for mobile reading)
2. Split at natural semantic boundaries (complete thoughts)
3. Keep related sentences together
4. Start new paragraph when topic/speaker changes
5. Respect existing paragraph breaks in the text
6. Never split in the middle of a sentence

OUTPUT: Return a JSON array of paragraph strings.
Example: ["First paragraph text here.", "Second paragraph continues the narrative.", "Third paragraph with new topic."]

Return ONLY the JSON array, no markdown, no explanations."""


def split_into_paragraphs_gpt(text: str) -> list:
    """
    Uses GPT to split text into natural paragraphs for app display.
    
    Args:
        text: Chapter text to split
        
    Returns:
        List of paragraph strings (150-350 chars each)
    """
    if not text or not text.strip():
        return []
    
    # For very short text, return as single paragraph
    if len(text) <= 350:
        return [text.strip()]
    
    client = get_openai()
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": PARAGRAPH_SYSTEM_PROMPT},
            {"role": "user", "content": f"Split this text into natural paragraphs:\n\n{text}"}
        ],
        response_format={"type": "json_object"}
    )
    
    content = response.choices[0].message.content
    
    try:
        # GPT returns {"paragraphs": [...]} or just [...]
        result = json.loads(content)
        if isinstance(result, list):
            return result
        elif isinstance(result, dict):
            # Try common keys
            for key in ["paragraphs", "segments", "sections", "result"]:
                if key in result and isinstance(result[key], list):
                    return result[key]
        return [text]  # Fallback
    except json.JSONDecodeError:
        # Fallback: split by paragraph breaks or sentences
        return fallback_paragraph_split(text)


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
            # Split long paragraphs by sentences
            sentences = re.split(r'(?<=[.!?])\s+', para)
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
