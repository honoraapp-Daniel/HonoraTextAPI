"""
Metadata extraction module for Honora.
Uses GPT to extract book title, author, and additional metadata from PDF text.
"""
import json
import os
import re
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

    response = client.chat.completions.create(
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

