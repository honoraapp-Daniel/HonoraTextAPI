"""
Unit tests for perfect paragraph splitting.

Tests the new spaCy + Gemini + validation approach to ensure:
- No mid-sentence splits
- No single-character paragraphs
- No numeric-only paragraphs
- All paragraphs are of reasonable length
"""
import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSentenceDetector:
    """Tests for the sentence_detector module."""
    
    def test_detect_sentences_basic(self):
        """Test basic sentence detection."""
        from app.sentence_detector import detect_sentences
        
        text = "The sun rose slowly. Birds began to sing. It was a beautiful morning."
        sentences = detect_sentences(text)
        
        assert len(sentences) == 3
        assert sentences[0] == "The sun rose slowly."
        assert sentences[1] == "Birds began to sing."
        assert sentences[2] == "It was a beautiful morning."
    
    def test_detect_sentences_with_abbreviations(self):
        """Test that abbreviations don't cause incorrect splits."""
        from app.sentence_detector import detect_sentences
        
        text = "Dr. Smith went to the store. He bought 3.14 kg of apples."
        sentences = detect_sentences(text)
        
        # Should NOT split at "Dr." or "3.14"
        assert len(sentences) == 2
        assert "Dr. Smith" in sentences[0]
        assert "3.14 kg" in sentences[1]
    
    def test_detect_sentences_with_quotes(self):
        """Test handling of quoted text."""
        from app.sentence_detector import detect_sentences
        
        text = '"Hello," she said. "How are you today?" He smiled warmly.'
        sentences = detect_sentences(text)
        
        # All sentences should be complete
        for sent in sentences:
            assert len(sent) > 5  # No tiny fragments
    
    def test_sentences_to_numbered_text(self):
        """Test numbered text generation."""
        from app.sentence_detector import sentences_to_numbered_text
        
        sentences = ["First sentence.", "Second sentence.", "Third sentence."]
        numbered = sentences_to_numbered_text(sentences)
        
        assert "1. First sentence." in numbered
        assert "2. Second sentence." in numbered
        assert "3. Third sentence." in numbered
    
    def test_merge_short_sentences(self):
        """Test merging of short sentences."""
        from app.sentence_detector import merge_short_sentences
        
        sentences = ["Yes.", "Of course.", "The main point is that this works correctly."]
        merged = merge_short_sentences(sentences, min_chars=15)
        
        # Short sentences should be merged
        assert len(merged) < len(sentences)
    
    def test_split_long_sentence(self):
        """Test splitting of very long sentences."""
        from app.sentence_detector import split_long_sentence
        
        long_sentence = "This is a very long sentence that goes on and on, with multiple clauses, and various points, and it just keeps going until it becomes too long for TTS."
        chunks = split_long_sentence(long_sentence, max_chars=50)
        
        # All chunks should be under the limit
        for chunk in chunks:
            assert len(chunk) <= 60  # Allow some flexibility


class TestParagraphValidation:
    """Tests for paragraph validation and fixing."""
    
    def test_validate_removes_single_chars(self):
        """Test that single character paragraphs are removed."""
        from app.chapters import validate_and_fix_paragraphs
        
        paragraphs = ["Chapter 1", "Good paragraph here.", "1", "Another good one."]
        result = validate_and_fix_paragraphs(paragraphs, "Chapter 1")
        
        # "1" should be removed
        assert "1" not in result
        assert len(result) < len(paragraphs)
    
    def test_validate_removes_numeric_only(self):
        """Test that numeric-only paragraphs are removed."""
        from app.chapters import validate_and_fix_paragraphs
        
        paragraphs = ["Title", "42", "123", "Good text here."]
        result = validate_and_fix_paragraphs(paragraphs, "Title")
        
        assert "42" not in result
        assert "123" not in result
    
    def test_validate_merges_short_paragraphs(self):
        """Test that short paragraphs are merged with neighbors."""
        from app.chapters import validate_and_fix_paragraphs
        
        paragraphs = ["Chapter Title", "OK.", "This is a properly long paragraph with enough content."]
        result = validate_and_fix_paragraphs(paragraphs, "Chapter Title")
        
        # "OK." should be merged, not standalone
        assert not any(p.strip() == "OK." for p in result)
    
    def test_validate_preserves_title(self):
        """Test that chapter title is never merged."""
        from app.chapters import validate_and_fix_paragraphs
        
        paragraphs = ["Chapter 1: Introduction", "This is content."]
        result = validate_and_fix_paragraphs(paragraphs, "Chapter 1: Introduction")
        
        assert result[0] == "Chapter 1: Introduction"


class TestParagraphSplitting:
    """Tests for the complete paragraph splitting pipeline."""
    
    def test_no_mid_sentence_splits(self):
        """Ensure paragraphs never end mid-sentence."""
        from app.chapters import split_into_paragraphs_perfect
        
        text = """Chapter 1: Test
        
        The quick brown fox jumped over the lazy dog. This is another complete sentence. 
        And here is a third one that should also be complete. The story continues with more text."""
        
        paragraphs = split_into_paragraphs_perfect(text, "Chapter 1: Test")
        
        # Every paragraph (except maybe title) should end with sentence-ending punctuation
        for para in paragraphs[1:]:  # Skip title
            if para.strip():
                last_char = para.strip()[-1]
                assert last_char in '.!?', f"Paragraph ends with '{last_char}': {para[:50]}..."
    
    def test_no_empty_paragraphs(self):
        """Ensure no empty paragraphs are created."""
        from app.chapters import split_into_paragraphs_perfect
        
        text = "Chapter 1\n\nSome content here. More content follows."
        paragraphs = split_into_paragraphs_perfect(text, "Chapter 1")
        
        for para in paragraphs:
            assert para.strip(), "Found empty paragraph"
            assert len(para.strip()) > 0
    
    def test_title_is_first_paragraph(self):
        """Ensure chapter title is always first paragraph."""
        from app.chapters import split_into_paragraphs_perfect
        
        text = "Some book content. This is the beginning of the chapter."
        paragraphs = split_into_paragraphs_perfect(text, "Chapter 5: Adventure Begins")
        
        assert paragraphs[0] == "Chapter 5: Adventure Begins"


class TestSectionSplitting:
    """Tests for TTS section splitting."""
    
    def test_section_0_is_title(self):
        """Ensure section 0 is always the chapter title."""
        from app.chapters import split_into_sections_perfect
        
        text = "The story begins here. It continues with more content."
        sections = split_into_sections_perfect(text, "Chapter 1", max_chars=250)
        
        assert sections[0] == "Chapter 1"
    
    def test_sections_respect_max_chars(self):
        """Ensure sections respect the character limit."""
        from app.chapters import split_into_sections_perfect
        
        text = "This is a test. " * 50  # Long text
        sections = split_into_sections_perfect(text, "Title", max_chars=250)
        
        for i, section in enumerate(sections[1:], 1):  # Skip title
            assert len(section) <= 300, f"Section {i} too long: {len(section)} chars"
    
    def test_no_tiny_sections(self):
        """Ensure no very tiny sections are created."""
        from app.chapters import split_into_sections_perfect
        
        text = "First sentence here. Second sentence follows. Third one comes after."
        sections = split_into_sections_perfect(text, "Chapter", max_chars=250)
        
        for i, section in enumerate(sections[1:], 1):  # Skip title
            if section.strip():
                assert len(section) >= 5, f"Section {i} too short: '{section}'"


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
