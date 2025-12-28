"""
TTS Text Formatter for Honora

Prepares section text for speech synthesis.
Handles IPA pronunciation tags, special characters, and text normalization.
"""

import re
from typing import Optional


def format_for_tts(text: str, output_format: str = "plain") -> str:
    """
    Converts section text to TTS-ready format.
    
    Args:
        text: Raw section text (may contain IPA tags)
        output_format: One of:
            - "plain": Remove IPA tags, keep word only (default)
            - "ssml": Convert to SSML phoneme tags (for SSML-capable TTS)
            
    Returns:
        TTS-ready text string
    """
    if not text:
        return ""
    
    if output_format == "ssml":
        return _format_ssml(text)
    else:
        return _format_plain(text)


def _format_plain(text: str) -> str:
    """
    Remove all IPA pronunciation tags, keeping only the word.
    TTS engine will use its default pronunciation.
    """
    # Old format: <word<<IPA:/pronunciation/>>>
    text = re.sub(r'<(\w+)<<IPA:[^>]+>>>', r'\1', text)
    
    # New format: <word|IPA:/pronunciation/>
    text = re.sub(r'<(\w+)\|IPA:[^>]+>', r'\1', text)
    
    # Clean any stray angle brackets
    text = re.sub(r'<\s*>', '', text)
    
    return text.strip()


def _format_ssml(text: str) -> str:
    """
    Convert IPA tags to SSML phoneme elements.
    For use with SSML-capable TTS engines (e.g., Amazon Polly, Google TTS).
    
    Example output:
        <phoneme alphabet="ipa" ph="prɑː.nə">Prana</phoneme>
    """
    def convert_ipa_tag(match):
        word = match.group(1)
        ipa = match.group(2)
        # Remove the leading/trailing slashes from IPA
        ipa = ipa.strip('/')
        return f'<phoneme alphabet="ipa" ph="{ipa}">{word}</phoneme>'
    
    # Old format: <word<<IPA:/pronunciation/>>>
    text = re.sub(
        r'<(\w+)<<IPA:(/[^/]+/)>>>',
        convert_ipa_tag,
        text
    )
    
    # New format: <word|IPA:/pronunciation/>
    text = re.sub(
        r'<(\w+)\|IPA:(/[^/]+/)>',
        convert_ipa_tag,
        text
    )
    
    return text.strip()


def extract_ipa_words(text: str) -> list[dict]:
    """
    Extract all words with IPA pronunciation hints from text.
    Useful for building a pronunciation dictionary.
    
    Returns:
        List of dicts with 'word' and 'ipa' keys
    """
    words = []
    
    # Old format
    for match in re.finditer(r'<(\w+)<<IPA:(/[^/]+/)>>>', text):
        words.append({
            'word': match.group(1),
            'ipa': match.group(2).strip('/')
        })
    
    # New format
    for match in re.finditer(r'<(\w+)\|IPA:(/[^/]+/)>', text):
        words.append({
            'word': match.group(1),
            'ipa': match.group(2).strip('/')
        })
    
    return words


def normalize_for_tts(text: str) -> str:
    """
    Full TTS normalization pipeline:
    1. Remove IPA tags
    2. Normalize whitespace
    3. Remove problematic characters
    """
    # Remove IPA tags
    text = _format_plain(text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove or replace problematic characters for TTS
    # Curly quotes -> straight quotes
    text = text.replace('"', '"').replace('"', '"')
    text = text.replace(''', "'").replace(''', "'")
    
    # Em/en dashes -> simple dash
    text = text.replace('—', '-').replace('–', '-')
    
    return text.strip()
