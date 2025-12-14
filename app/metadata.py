"""
Metadata extraction module for Honora.
Uses GPT to extract book title and author from PDF text.
"""
import json
import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

METADATA_SYSTEM_PROMPT = """
You are a book metadata extractor. Given text from the first pages of a book, extract:
1. The book title
2. The author name(s)

Return ONLY valid JSON in this exact format:
{
  "title": "Book Title Here",
  "author": "Author Name Here"
}

If there are multiple authors, separate them with commas.
If you cannot find the title or author, use "Unknown" as the value.
Do not include subtitles unless they are essential to the title.
"""


def extract_book_metadata(first_pages_text: str) -> dict:
    """
    Uses GPT to extract title and author from the first pages of a book.
    
    Args:
        first_pages_text: Combined text from the first few pages of the PDF
        
    Returns:
        dict with "title" and "author" keys
    """
    prompt = f"""
Extract the book title and author from this text:

{first_pages_text}

Return JSON with "title" and "author" keys only.
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": METADATA_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
    )

    try:
        result = json.loads(response.choices[0].message.content)
        return {
            "title": result.get("title", "Unknown"),
            "author": result.get("author", "Unknown")
        }
    except:
        return {"title": "Unknown", "author": "Unknown"}
