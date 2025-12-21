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
6. Convert foreign (Latin/Greek) words into pronunciation tags:
   Format: <word<<IPA:/.../>>>
7. Flatten poetry and quotes into normal paragraphs.
8. NEVER change the meaning of a sentence.
9. If uncertain about any segment, keep it but add an "uncertain" entry.
10. Return JSON only, no markdown, no explanations.

OUTPUT JSON:
{
  "cleaned_text": "...",
  "removed": [],
  "uncertain": []
}
"""


def extract_json_from_response(text: str) -> dict:
    """
    Extracts JSON from LLM response.
    With response_format={"type": "json_object"}, the model should return
    pure JSON. This function handles potential whitespace or markdown wrapping.
    """
    if not text:
        return None
        
    text = text.strip()
    
    # Try direct parse
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
            
    # Fallback: Find the first '{' and last '}'
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
            
    return None


def clean_page_text(page_items):
    text = " ".join([item["text"] for item in page_items])

    prompt = f"""
    CLEAN THIS PAGE:

    RAW PAGE TEXT:
    {text}

    RETURN CLEAN JSON (no markdown, no code blocks):
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": CLEANER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        max_tokens=4000  # Explicitly allow enough tokens for full page text
    )

    content = response.choices[0].message.content
    result = extract_json_from_response(content)
    
    if result is None:
        # Log the problematic response for debugging
        print(f"[CLEANER] ❌ Failed to parse LLM response.")
        print(f"[CLEANER] Start of response: {content[:200]}")
        print(f"[CLEANER] End of response: {content[-200:]}")
        raise HTTPException(
            status_code=500, 
            detail=f"Invalid JSON returned by LLM. Length: {len(content)}"
        )
    
    # Ensure required fields exist
    return {
        "cleaned_text": result.get("cleaned_text", ""),
        "removed": result.get("removed", []),
        "uncertain": result.get("uncertain", [])
    }
