import json
import os
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
10. Return JSON only.

OUTPUT JSON:
{
  "cleaned_text": "...",
  "removed": [],
  "uncertain": []
}
"""

def clean_page_text(page_items):
    text = " ".join([item["text"] for item in page_items])

    prompt = f"""
    CLEAN THIS PAGE:

    RAW PAGE TEXT:
    {text}

    RETURN CLEAN JSON:
    """

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": CLEANER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
    )

    try:
        return json.loads(response.choices[0].message.content)
    except:
        raise HTTPException(status_code=500, detail="Invalid JSON returned by LLM")

