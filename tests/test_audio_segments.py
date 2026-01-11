"""
Unit tests for audio_segments module
Tests: merge, clamp, grouping, duration reading
"""

import pytest
from app.audio_segments import (
    merge_short_segments,
    clamp_long_segments,
    split_at_sentences,
    process_segments,
    group_segments,
    MIN_CHARS,
    MAX_CHARS
)


class TestMergeShortSegments:
    """Tests for merge_short_segments function."""
    
    def test_merges_single_word(self):
        """Single words should be merged with adjacent text."""
        sections = ["Hello.", "World is beautiful today."]
        result = merge_short_segments(sections)
        assert len(result) == 1
        assert "Hello." in result[0]["text"]
        assert "World" in result[0]["text"]
    
    def test_keeps_long_segments(self):
        """Segments >= MIN_CHARS stay separate."""
        long_text = "A" * MIN_CHARS + " some more words to make it long enough."
        sections = [long_text, long_text]
        result = merge_short_segments(sections)
        assert len(result) == 2
    
    def test_cascading_merge(self):
        """Multiple short segments cascade into one."""
        sections = ["Hi.", "There.", "How are you?", "I am fine."]
        result = merge_short_segments(sections)
        assert len(result) == 1
        assert "Hi" in result[0]["text"]
        assert "fine" in result[0]["text"]
    
    def test_empty_input(self):
        """Empty list returns empty."""
        assert merge_short_segments([]) == []
    
    def test_whitespace_sections(self):
        """Whitespace-only sections are skipped."""
        sections = ["  ", "Hello world this is a longer segment.", "   "]
        result = merge_short_segments(sections)
        assert len(result) == 1


class TestSplitAtSentences:
    """Tests for split_at_sentences function."""
    
    def test_no_split_needed(self):
        """Text under max_chars stays intact."""
        text = "Short sentence."
        result = split_at_sentences(text, 100)
        assert result == [text]
    
    def test_splits_at_period(self):
        """Splits at sentence boundary."""
        text = "First sentence. Second sentence."
        result = split_at_sentences(text, 20)
        assert len(result) == 2
        assert "First" in result[0]
        assert "Second" in result[1]
    
    def test_splits_at_question_mark(self):
        """Splits at ? boundary."""
        text = "Is this right? Yes it is."
        result = split_at_sentences(text, 18)
        assert len(result) == 2
    
    def test_force_split_long_sentence(self):
        """Very long sentence without punctuation is force-split."""
        text = "A" * 100
        result = split_at_sentences(text, 40)
        assert all(len(s) <= 40 for s in result)


class TestClampLongSegments:
    """Tests for clamp_long_segments function."""
    
    def test_no_clamp_needed(self):
        """Segments under MAX_CHARS stay intact."""
        segments = [{"text": "Short text."}]
        result = clamp_long_segments(segments)
        assert len(result) == 1
    
    def test_clamps_long_segment(self):
        """Long segments are split."""
        long_text = "This is a sentence. " * 30  # ~600 chars
        segments = [{"text": long_text}]
        result = clamp_long_segments(segments)
        assert len(result) > 1
        assert all(len(seg["text"]) <= MAX_CHARS + 50 for seg in result)  # Allow some tolerance


class TestProcessSegments:
    """Tests for full process_segments pipeline."""
    
    def test_merge_then_clamp(self):
        """Short segments merge, then long ones clamp."""
        raw = [
            "Hi.",
            "Hello.",
            "This is a very long sentence that goes on and on. " * 15
        ]
        result = process_segments(raw)
        
        # All segments should have segment_index
        assert all("segment_index" in seg for seg in result)
        
        # No mega-segments
        assert all(len(seg["text"]) <= MAX_CHARS + 50 for seg in result)
    
    def test_assigns_sequential_indices(self):
        """segment_index is sequential starting from 0."""
        raw = ["Sentence one is long enough now.", "Sentence two is also long enough."]
        result = process_segments(raw)
        indices = [seg["segment_index"] for seg in result]
        assert indices == list(range(len(result)))


class TestGroupSegments:
    """Tests for group_segments function."""
    
    def test_groups_by_duration(self):
        """Segments are grouped by target duration."""
        segments = [
            {"segment_index": i, "text": f"Segment {i}", "duration_ms": 10000}
            for i in range(10)
        ]
        groups = group_segments(segments)
        
        # Should create ~3 groups (10 * 10s = 100s, target 35s each)
        assert 2 <= len(groups) <= 4
    
    def test_start_time_ms_calculated(self):
        """start_time_ms is prefix sum of durations."""
        segments = [
            {"segment_index": 0, "text": "A", "duration_ms": 10000},
            {"segment_index": 1, "text": "B", "duration_ms": 10000},
            {"segment_index": 2, "text": "C", "duration_ms": 10000},
            {"segment_index": 3, "text": "D", "duration_ms": 10000},
        ]
        groups = group_segments(segments)
        
        assert groups[0]["start_time_ms"] == 0
        if len(groups) > 1:
            assert groups[1]["start_time_ms"] == groups[0]["duration_ms"]
    
    def test_offset_in_group_ms(self):
        """Each segment has correct offset within its group."""
        segments = [
            {"segment_index": i, "text": f"Seg {i}", "duration_ms": 5000}
            for i in range(4)
        ]
        groups = group_segments(segments)
        
        for group in groups:
            expected_offset = 0
            for seg in group["segments"]:
                assert seg["offset_in_group_ms"] == expected_offset
                expected_offset += seg["duration_ms"]
    
    def test_segment_index_ranges(self):
        """Groups have correct start/end segment indices."""
        segments = [
            {"segment_index": i, "text": f"Seg {i}", "duration_ms": 20000}
            for i in range(5)
        ]
        groups = group_segments(segments)
        
        for group in groups:
            assert group["start_segment_index"] <= group["end_segment_index"]
            segs = group["segments"]
            assert group["start_segment_index"] == segs[0]["segment_index"]
            assert group["end_segment_index"] == segs[-1]["segment_index"]
    
    def test_single_large_segment(self):
        """Single segment forms its own group."""
        segments = [{"segment_index": 0, "text": "Only one", "duration_ms": 50000}]
        groups = group_segments(segments)
        assert len(groups) == 1
        assert groups[0]["duration_ms"] == 50000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
