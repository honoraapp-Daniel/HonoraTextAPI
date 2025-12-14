import os
import json
import re
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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
    for chapter in chapters:
        supabase.table("chapters").insert({
            "book_id": book_id,
            "chapter_index": chapter["chapter_index"],
            "title": chapter["title"]
        }).execute()
