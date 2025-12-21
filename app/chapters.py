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
    
    return book_id



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
    if " - " in line:
        name = line.split(" - ", 1)[1].strip()
        if name:
            return name
    
    # No name found, return None (just use the chapter number)
    return None


def extract_chapters_from_text(full_text: str):
    lines = full_text.split("\n")
    chapters = []

    current_title = None
    current_text = []
    chapter_index = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if CHAPTER_REGEX.match(line):
            if current_title is not None:
                chapters.append({
                    "chapter_index": chapter_index,
                    "title": current_title,
                    "text": "\n".join(current_text)
                })
                current_text = []

            chapter_index += 1
            # Extract just the chapter name, not "Chapter X. Name"
            current_title = extract_chapter_name(line)
        else:
            current_text.append(line)


    if current_title and current_text:
        chapters.append({
            "chapter_index": chapter_index,
            "title": current_title,
            "text": "\n".join(current_text)
        })

    return chapters


def write_chapters_to_supabase(book_id: str, chapters: list):
    """
    Writes chapters to the 'chapters' table, including chapter text.
    """
    supabase = get_supabase()
    for chapter in chapters:
        supabase.table("chapters").insert({
            "book_id": book_id,
            "chapter_index": chapter["chapter_index"],
            "title": chapter["title"],
            "text": chapter.get("text", "")  # Store chapter text for later chunking
        }).execute()


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
        model="gpt-4.1",
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
