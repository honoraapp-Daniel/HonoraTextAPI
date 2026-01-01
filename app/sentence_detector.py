"""
Sentence Detector Module for Honora.

Uses spaCy for robust sentence boundary detection.
This ensures we NEVER split text mid-sentence, handling:
- Abbreviations (Dr., Mr., Mrs., etc.)
- Numbers (3.14, 1.5, etc.)
- Quoted text
- Ellipsis (...)
- Edge cases that break regex-based splitting
"""
import os
import re
import subprocess
from typing import List, Tuple

from app.logger import get_logger

logger = get_logger(__name__)

# Lazy initialization of spaCy
_nlp = None

def get_spacy():
    """
    Get or initialize spaCy model with proper error handling.
    
    Returns:
        spaCy Language model
        
    Raises:
        RuntimeError: If spaCy model cannot be loaded
    """
    global _nlp
    if _nlp is None:
        try:
            import spacy
            logger.info("Loading spaCy English model...")
            _nlp = spacy.load("en_core_web_sm")
            logger.info("spaCy model loaded successfully")
        except OSError:
            # Model not downloaded, attempt to download it
            logger.warning("spaCy model not found. Attempting to download...")
            try:
                subprocess.run(
                    ["python", "-m", "spacy", "download", "en_core_web_sm"],
                    check=True,
                    capture_output=True,
                    text=True
                )
                import spacy
                _nlp = spacy.load("en_core_web_sm")
                logger.info("spaCy model downloaded and loaded successfully")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to download spaCy model: {e.stderr}")
                raise RuntimeError(
                    "spaCy model 'en_core_web_sm' is not installed and automatic "
                    "download failed. Please install manually: "
                    "python -m spacy download en_core_web_sm"
                )
            except Exception as e:
                logger.error(f"Unexpected error loading spaCy model: {e}")
                raise RuntimeError(f"Failed to load spaCy model: {e}")
    return _nlp


def detect_sentences(text: str) -> List[str]:
    """
    Split text into guaranteed complete sentences using spaCy.
    
    This is the foundation of our paragraph splitting - by guaranteeing
    complete sentences, we ensure paragraphs never end mid-sentence.
    
    Args:
        text: Raw chapter text
        
    Returns:
        List of complete sentences (strings)
    """
    if not text or not text.strip():
        return []
    
    nlp = get_spacy()
    
    # Process the text
    doc = nlp(text)
    
    # Extract sentences
    sentences = []
    for sent in doc.sents:
        sent_text = sent.text.strip()
        if sent_text:
            sentences.append(sent_text)
    
    return sentences


def detect_sentences_with_indices(text: str) -> List[Tuple[int, str]]:
    """
    Split text into sentences with their 1-based indices.
    
    This format is ideal for LLM-based paragraph grouping,
    where the LLM only needs to specify which sentence indices
    belong to each paragraph.
    
    Args:
        text: Raw chapter text
        
    Returns:
        List of (index, sentence_text) tuples, 1-indexed
    """
    sentences = detect_sentences(text)
    return [(i + 1, s) for i, s in enumerate(sentences)]


def sentences_to_numbered_text(sentences: List[str]) -> str:
    """
    Convert sentences to numbered text for LLM prompt.
    
    Example output:
        1. The sun rose slowly.
        2. Birds began to sing.
        3. Meanwhile in the city, traffic was building.
    
    Args:
        sentences: List of sentence strings
        
    Returns:
        Numbered text string
    """
    lines = []
    for i, sent in enumerate(sentences, 1):
        lines.append(f"{i}. {sent}")
    return "\n".join(lines)


def is_sentence_ending(text: str) -> bool:
    """
    Check if text ends with sentence-ending punctuation.
    
    Used for validation to ensure paragraphs end properly.
    """
    if not text:
        return False
    text = text.strip()
    return text.endswith('.') or text.endswith('!') or text.endswith('?')


def merge_short_sentences(sentences: List[str], min_chars: int = 20) -> List[str]:
    """
    Merge very short sentences with their neighbors.
    
    Handles edge cases like:
    - "Yes." (single word responses)
    - "1." (numbered lists that got split)
    - Dialogue fragments
    
    Args:
        sentences: List of sentences
        min_chars: Minimum characters for a standalone sentence
        
    Returns:
        List of sentences with short ones merged
    """
    if not sentences:
        return []
    
    result = []
    buffer = ""
    
    for sent in sentences:
        if len(sent) < min_chars and buffer:
            # Merge with previous
            buffer = buffer + " " + sent
        elif len(sent) < min_chars and not buffer:
            # Start buffering
            buffer = sent
        else:
            if buffer:
                # Merge buffer with this sentence
                result.append(buffer + " " + sent)
                buffer = ""
            else:
                result.append(sent)
    
    # Don't forget any remaining buffer
    if buffer:
        if result:
            result[-1] = result[-1] + " " + buffer
        else:
            result.append(buffer)
    
    return result


def clean_text_for_sentences(text: str) -> str:
    """
    Pre-clean text before sentence detection.
    
    Fixes common issues that confuse spaCy:
    - Multiple spaces
    - Unusual whitespace characters
    - Common OCR errors
    """
    if not text:
        return ""
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Fix common OCR issues
    text = text.replace('…', '...')  # Normalize ellipsis
    text = text.replace(''', "'")    # Smart quotes
    text = text.replace(''', "'")
    text = text.replace('"', '"')
    text = text.replace('"', '"')
    
    return text.strip()


def split_long_sentence(sentence: str, max_chars: int = 250) -> List[str]:
    """
    Split a very long sentence at natural clause boundaries.
    
    Used for TTS sections where we need shorter chunks.
    Only splits at: commas, semicolons, colons, dashes.
    
    Args:
        sentence: A single long sentence
        max_chars: Maximum characters per chunk
        
    Returns:
        List of sentence fragments (only if necessary)
    """
    if len(sentence) <= max_chars:
        return [sentence]
    
    # Split at clause boundaries
    # Priority: semicolon > colon > em-dash > comma
    delimiters = ['; ', ': ', ' — ', ' – ', ' - ', ', ']
    
    for delimiter in delimiters:
        if delimiter in sentence:
            parts = sentence.split(delimiter)
            chunks = []
            current = ""
            
            for i, part in enumerate(parts):
                # Add delimiter back (except for last part)
                if i < len(parts) - 1:
                    part = part + delimiter.rstrip()
                
                if len(current) + len(part) + 1 > max_chars:
                    if current:
                        chunks.append(current.strip())
                    current = part
                else:
                    current = (current + " " + part).strip() if current else part
            
            if current:
                chunks.append(current.strip())
            
            # Only use this split if it actually helped
            if all(len(c) <= max_chars for c in chunks):
                return chunks
    
    # Last resort: word-based splitting (should rarely happen)
    words = sentence.split()
    chunks = []
    current = ""
    
    for word in words:
        if len(current) + len(word) + 1 > max_chars:
            if current:
                chunks.append(current.strip())
            current = word
        else:
            current = (current + " " + word).strip() if current else word
    
    if current:
        chunks.append(current.strip())
    
    return chunks
