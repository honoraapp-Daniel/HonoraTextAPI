import json
import os
import re
from fastapi import HTTPException
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

CLEANER_SYSTEM_PROMPT = """
You are a strict text-cleaning engine for Honora, an audiobook restoration system.
Your job is to CLEAN TEXT ONLY — never rewrite meaning or add new ideas.

RULES:
1. Keep all main text, paragraphs, chapter titles.
2. Remove headers, footers, page numbers, index items, references, editor notes.
3. Convert all numbers and years into English words.
4. Convert Roman numerals into English words.
5. Modernize spelling only when meaning is unchanged.
6. Convert foreign (Latin/Greek/Sanskrit) words into pronunciation tags:
   Format: <word|IPA:/pronunciation/> (use pipe separator for TTS parsing)
7. Flatten poetry and quotes into normal paragraphs.
8. NEVER change the meaning of a sentence.
9. If uncertain about any segment, keep it but add an "uncertain" entry.
10. Return JSON only, no markdown, no explanations.
11. Remove navigation markers: "Next:", "Previous:", "Contents", "Back to", etc.
12. Remove book/chapter attribution lines at end of paragraphs (e.g., "The Kybalion, by Three Initiates")
13. Remove source citations like "Science of Breath, by Yogi Ramacharaka, pseud. William Atkinson."
14. Remove trailing periods after chapter titles (e.g., "Chapter One." → "Chapter One")

OUTPUT JSON:
{
  "cleaned_text": "...",
  "removed": [],
  "uncertain": []
}
"""

def sanitize_input_text(text: str) -> str:
    """
    Strips non-printable characters and other potentially problematic 
    hidden characters from the input text before sending to LLM.
    """
    if not text:
        return ""
    # Remove non-printable characters except standard whitespace
    return "".join(char for char in text if char.isprintable() or char in "\n\r\t")


def extract_json_from_response(text: str) -> dict:
    """
    Extracts JSON from LLM response.
    Handles potential whitespace, markdown wrapping, and even partial JSON.
    """
    if not text:
        return None
        
    text = text.strip()
    
    # 1. Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # 2. Try to extract from markdown code block
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
            
    # 3. Fallback: Find the first '{' and last '}'
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        json_str = text[start:end+1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # 4. Last resort: If truncated, try to close the main string and object
            try:
                # Try adding closing quote and braces
                if '"cleaned_text":' in json_str:
                    repaired = json_str.strip()
                    if not repaired.endswith('}'):
                        if not repaired.endswith('"'):
                            repaired += '"'
                        repaired += '}'
                    return json.loads(repaired)
            except:
                pass
            
    # 5. Regex search for the specific field we need (cleaned_text)
    cleaned_match = re.search(r'"cleaned_text":\s*"(.*?)"(?:\s*,|\s*\})', text, re.DOTALL)
    if cleaned_match:
        return {
            "cleaned_text": cleaned_match.group(1),
            "removed": [],
            "uncertain": []
        }
            
    return None


def clean_page_text(page_items):
    text = " ".join([item["text"] for item in page_items])
    text = sanitize_input_text(text)

    prompt = f"""
    CLEAN THIS PAGE TEXT:
    {text}

    RETURN CLEAN JSON WITH key "cleaned_text".
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": CLEANER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        max_tokens=16384
    )

    content = response.choices[0].message.content
    result = extract_json_from_response(content)
    
    if result is None:
        print(f"[CLEANER] ❌ Failed to parse LLM response.")
        print(f"[CLEANER] Full response content follows:")
        print("-" * 40)
        print(content)
        print("-" * 40)
        raise HTTPException(
            status_code=500, 
            detail=f"Invalid JSON returned by LLM. Length: {len(content)}"
        )
    
    return {
        "cleaned_text": result.get("cleaned_text", ""),
        "removed": result.get("removed", []),
        "uncertain": result.get("uncertain", [])
    }
