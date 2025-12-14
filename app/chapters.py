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


def create_book_in_supabase(title: str, author: str) -> str:
    """
    Creates a new book entry in the 'books' table.
    
    Args:
        title: Book title
        author: Book author
        
    Returns:
        book_id (UUID string) of the created book
    """
    supabase = get_supabase()
    result = supabase.table("books").insert({
        "title": title,
        "author": author
    }).execute()
    
    # Return the generated UUID
    return result.data[0]["id"]


CHAPTER_REGEX = re.compile(
    r"^(CHAPTER|BOOK|PART)\s+([A-Z]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten)",
    re.IGNORECASE
)

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
            if current_title:
                chapters.append({
                    "chapter_index": chapter_index,
                    "title": current_title,
                    "text": "\n".join(current_text)
                })
                current_text = []

            chapter_index += 1
            current_title = line
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
