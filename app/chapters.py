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


def create_book_in_supabase(title: str, author: str, language: str = "en") -> str:
    """
    Creates a new book entry in the 'books' table.
    
    Args:
        title: Book title
        author: Book author
        language: Language code (default: "en")
        
    Returns:
        book_id (UUID string) of the created book
    """
    supabase = get_supabase()
    result = supabase.table("books").insert({
        "title": title,
        "author": author,
        "language": language
    }).execute()
    
    # Return the generated UUID
    return result.data[0]["id"]


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
    supabase = get_supabase()
    for chapter in chapters:
        supabase.table("chapters").insert({
            "book_id": book_id,
            "chapter_index": chapter["chapter_index"],
            "title": chapter["title"]
        }).execute()
