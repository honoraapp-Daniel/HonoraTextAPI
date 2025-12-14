"""
Metadata extraction module for Honora.
Uses GPT to extract book title and author from PDF text.
"""
import json
import os
import re
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

METADATA_SYSTEM_PROMPT = """
You are a book metadata extractor. Given text from the first pages of a book, extract:
1. The book title
2. The author name(s)
3. The language of the book (as ISO 639-1 code, e.g. "en", "da", "de", "fr")

Return ONLY valid JSON in this exact format:
{
  "title": "Book Title Here",
  "author": "Author Name Here",
  "language": "en"
}

If there are multiple authors, separate them with commas.
If you cannot find the title or author, use "Unknown" as the value.
If you cannot determine the language, default to "en".
Do not include subtitles unless they are essential to the title.
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
    Uses GPT to extract title, author, and language from the first pages of a book.
    
    Args:
        first_pages_text: Combined text from the first few pages of the PDF
        
    Returns:
        dict with "title", "author", and "language" keys
    """
    prompt = f"""
Extract the book title, author, and language from this text:

{first_pages_text}

Return JSON with "title", "author", and "language" keys.
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
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
            "title": result.get("title", "Unknown"),
            "author": result.get("author", "Unknown"),
            "language": result.get("language", "en")
        }
    
    return {"title": "Unknown", "author": "Unknown", "language": "en"}
