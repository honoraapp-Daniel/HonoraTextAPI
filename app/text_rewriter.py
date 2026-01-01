"""
Text rewriting module using Gemini to clean special characters for TTS.
Removes symbols like ♄ ✶ △ ♂ that TTS cannot read properly.
"""
from app.config import Config
from app.logger import get_logger
from app.utils import retry_on_failure
from google import genai

logger = get_logger(__name__)

# Lazy initialization
_gemini_client = None


def get_gemini_client():
    """Get Gemini client for text rewriting."""
    global _gemini_client
    if _gemini_client is None:
        Config.validate_required("GEMINI_API_KEY")
        _gemini_client = genai.Client(api_key=Config.GEMINI_API_KEY)
    return _gemini_client


REWRITE_SYSTEM_PROMPT = """
You are a text rewriting assistant for an audiobook platform. Your job is to rewrite text to be TTS-friendly by replacing special symbols AND NUMBERS with their written equivalents.

CRITICAL RULES:
1. Replace ALL special symbols (astrological, alchemical, mathematical, etc.) with their WRITTEN NAMES
2. Replace ALL NUMBERS with their WRITTEN WORDS (including fractions, decimals, currency, dates, etc.)
3. Keep ALL regular text, punctuation, and sentence structure EXACTLY as is
4. Do NOT change the meaning, tone, or structure of the text
5. Do NOT add explanations or commentary
6. Return ONLY the rewritten text, nothing else

EXAMPLES OF NUMBER CONVERSION:
Input: "In 1834, he published 50⅓ copies for £530 at 2° 21'"
Output: "In eighteen thirty-four, he published fifty and one-third copies for five hundred thirty pounds at two degrees twenty-one minutes"

Input: "Chapter 3: The 7 Hermetic Principles (1908)"
Output: "Chapter three: The seven Hermetic Principles (nineteen oh-eight)"

Input: "The measurement was 15.5 cm or 6.1 inches"
Output: "The measurement was fifteen point five centimeters or six point one inches"

EXAMPLES OF SYMBOL CONVERSION:
Input: "♄ rules over Saturday and ✶ represents divinity"
Output: "Saturn rules over Saturday and star represents divinity"

Input: "The △ symbolizes fire and ♂ represents Mars"
Output: "The triangle symbolizes fire and Mars represents Mars"

Input: "If ♄ is in the 10th house with ♀"
Output: "If Saturn is in the tenth house with Venus"

COMMON SYMBOLS TO REPLACE:
- ♄ = Saturn, ♃ = Jupiter, ♂ = Mars, ♀ = Venus, ☿ = Mercury, ☉ = Sun, ☽ = Moon
- ✶ or ✵ = star, △ = triangle, ▽ = inverted triangle, □ = square, ○ = circle
- ✓ = check mark, ✗ = cross, ⊕ = circled plus, ⊗ = circled times
- Ψ = Psi, Ω = Omega, α = alpha, β = beta, γ = gamma, θ = theta, λ = lambda, μ = mu, ρ = rho, σ = sigma, τ = tau, φ = phi, χ = chi, ω = omega

CURRENCY SYMBOLS:
- £ = pounds, $ = dollars, € = euros, ¥ = yen

FRACTIONS:
- ½ = one-half, ⅓ = one-third, ¼ = one-quarter, ¾ = three-quarters, ⅕ = one-fifth, etc.

DEGREES AND MEASUREMENTS:
- ° = degrees, ' = minutes (for angles), " = seconds (for angles)
- % = percent

Return ONLY the rewritten text with ALL numbers and symbols converted to words.
"""


@retry_on_failure(max_retries=2, delay=2, exceptions=(Exception,))
def rewrite_text_gemini(text: str) -> str:
    """
    Rewrite text using Gemini to replace special characters with written equivalents.
    
    Args:
        text: Original text with special characters
        
    Returns:
        Rewritten text with symbols replaced by words
    """
    if not text or not text.strip():
        return text
    
    logger.info(f"Rewriting text with Gemini (length: {len(text)} chars)")
    
    try:
        client = get_gemini_client()
        
        prompt = f"""{REWRITE_SYSTEM_PROMPT}

TEXT TO REWRITE:
{text}

REWRITTEN TEXT:"""
        
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=[prompt]
        )
        
        # Extract text from response
        rewritten = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text:
                rewritten += part.text
        
        rewritten = rewritten.strip()
        
        if not rewritten:
            logger.warning("Gemini returned empty response, using original text")
            return text
        
        logger.info(f"Text rewritten successfully ({len(text)} -> {len(rewritten)} chars)")
        return rewritten
        
    except Exception as e:
        logger.error(f"Error rewriting text with Gemini: {e}")
        raise


@retry_on_failure(max_retries=2, delay=2, exceptions=(Exception,))
def optimize_paragraphs_gemini(paragraphs: list, chapter_title: str = "") -> dict:
    """
    Analyze and optimize paragraphs: merge short ones, split long ones, check TTS quality.
    
    Args:
        paragraphs: List of paragraph texts (excluding title at index 0)
        chapter_title: Optional chapter title for context
        
    Returns:
        dict with:
            - optimized_paragraphs: List of optimized paragraphs
            - changes: List of changes made
            - suggestions: List of suggestions
    """
    if not paragraphs or len(paragraphs) == 0:
        return {
            "optimized_paragraphs": paragraphs,
            "changes": [],
            "suggestions": []
        }
    
    logger.info(f"Optimizing {len(paragraphs)} paragraphs with Gemini")
    
    try:
        client = get_gemini_client()
        
        # Prepare paragraphs with indices for reference
        paragraphs_text = "\n\n".join([f"[P{i}] {p}" for i, p in enumerate(paragraphs)])
        
        context = f"Chapter: {chapter_title}\n\n" if chapter_title else ""
        
        prompt = f"""
You are an audiobook paragraph optimizer. Analyze these paragraphs and optimize them for TTS narration.

{context}PARAGRAPHS:
{paragraphs_text}

OPTIMIZATION RULES:
1. Merge very short paragraphs (< 50 chars) with adjacent ones if semantically related
2. Split very long paragraphs (> 800 chars) at natural sentence boundaries
3. Ensure each paragraph is a complete thought
4. Keep paragraph count balanced (aim for 100-400 chars per paragraph)
5. DO NOT change the text content, only reorganize paragraph boundaries
6. Return the optimized list in JSON format

Return JSON in this EXACT format:
{{
  "optimized_paragraphs": ["paragraph 1 text", "paragraph 2 text", ...],
  "changes": ["Description of change 1", "Description of change 2", ...],
  "suggestions": ["Optional suggestion 1", ...]
}}

IMPORTANT: Include ALL text from the original paragraphs, just reorganized.
"""
        
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=[prompt]
        )
        
        # Extract text from response
        content = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text:
                content += part.text
        
        # Parse JSON
        import json
        import re
        
        # Try to extract JSON from markdown code block
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(1))
        else:
            # Try direct parse
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
            else:
                logger.warning("Could not parse JSON from Gemini response")
                return {
                    "optimized_paragraphs": paragraphs,
                    "changes": [],
                    "suggestions": ["Could not parse optimization response"]
                }
        
        optimized = result.get("optimized_paragraphs", paragraphs)
        changes = result.get("changes", [])
        suggestions = result.get("suggestions", [])
        
        logger.info(f"Optimization complete: {len(paragraphs)} -> {len(optimized)} paragraphs, {len(changes)} changes")
        
        return {
            "optimized_paragraphs": optimized,
            "changes": changes,
            "suggestions": suggestions
        }
        
    except Exception as e:
        logger.error(f"Error optimizing paragraphs with Gemini: {e}")
        raise
