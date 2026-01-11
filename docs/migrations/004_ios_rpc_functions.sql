-- =====================================================
-- iOS RPC FUNCTIONS - TTS-First v3.1
-- Run in Supabase SQL Editor
-- =====================================================

-- =====================================================
-- get_chapter_with_spans: O(1) paragraph rendering
-- Returns segments array + spans array for direct slicing
-- =====================================================

CREATE OR REPLACE FUNCTION get_chapter_with_spans(p_chapter_id UUID)
RETURNS JSONB AS $$
DECLARE
    v_build_id UUID;
    v_use_spans BOOLEAN;
BEGIN
    -- Get current build and span flag for chapter
    SELECT current_build_id, use_paragraph_spans 
    INTO v_build_id, v_use_spans
    FROM chapters WHERE id = p_chapter_id;
    
    -- Return error if no build exists
    IF v_build_id IS NULL THEN
        RETURN jsonb_build_object(
            'success', false,
            'error', 'No active build for chapter'
        );
    END IF;
    
    RETURN jsonb_build_object(
        'success', true,
        'build_id', v_build_id,
        'use_spans', COALESCE(v_use_spans, false),
        
        -- Contiguous segment array (ordered by segment_index)
        -- iOS can slice directly: segments[span.start...span.end]
        'segments', COALESCE(
            (SELECT jsonb_agg(
                jsonb_build_object(
                    'i', segment_index,           -- index for O(1) access
                    't', text,                     -- display text
                    'd', duration_ms,              -- duration for highlighting
                    'g', group_id,                 -- audio group reference
                    'o', offset_in_group_ms        -- offset within group
                ) ORDER BY segment_index
            )
            FROM tts_segments WHERE build_id = v_build_id),
            '[]'::jsonb
        ),
        
        -- Paragraph spans (Gemini-assigned segment ranges)
        -- iOS renders paragraph N by: segments[spans[N].s ... spans[N].e]
        'spans', COALESCE(
            (SELECT jsonb_agg(
                jsonb_build_object(
                    'p', paragraph_index,          -- paragraph number
                    's', start_segment_index,      -- start segment (inclusive)
                    'e', end_segment_index         -- end segment (inclusive)
                ) ORDER BY paragraph_index
            )
            FROM paragraph_spans WHERE build_id = v_build_id),
            '[]'::jsonb
        ),
        
        -- Audio groups for playback
        'groups', COALESCE(
            (SELECT jsonb_agg(
                jsonb_build_object(
                    'id', id,
                    'idx', group_index,
                    'url', audio_url,
                    'dur', duration_ms,
                    'start', start_time_ms
                ) ORDER BY group_index
            )
            FROM audio_groups WHERE build_id = v_build_id),
            '[]'::jsonb
        )
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_chapter_with_spans IS 
'Returns chapter data for iOS O(1) paragraph rendering. 
Segments are contiguous; spans define [start,end] ranges for each paragraph.
iOS renders paragraph N as: segments[spans[N].s ... spans[N].e].join(" ")';

-- =====================================================
-- get_paragraph_text: Utility for rendering single paragraph
-- Returns joined text from segment range
-- =====================================================

CREATE OR REPLACE FUNCTION get_paragraph_text(
    p_build_id UUID,
    p_paragraph_index INT
) RETURNS TEXT AS $$
DECLARE
    v_start INT;
    v_end INT;
    v_text TEXT;
BEGIN
    -- Get span boundaries
    SELECT start_segment_index, end_segment_index INTO v_start, v_end
    FROM paragraph_spans 
    WHERE build_id = p_build_id AND paragraph_index = p_paragraph_index;
    
    IF v_start IS NULL THEN
        RETURN NULL;
    END IF;
    
    -- Join segment texts with space
    SELECT string_agg(text, ' ' ORDER BY segment_index) INTO v_text
    FROM tts_segments
    WHERE build_id = p_build_id 
      AND segment_index BETWEEN v_start AND v_end;
    
    RETURN v_text;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- GRANTS
-- =====================================================

GRANT EXECUTE ON FUNCTION get_chapter_with_spans(UUID) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION get_paragraph_text(UUID, INT) TO anon, authenticated;

-- =====================================================
-- VERIFICATION
-- =====================================================

SELECT 'iOS RPC functions created!' as status;

-- Test query (will return empty if no data):
-- SELECT get_chapter_with_spans('your-chapter-uuid');
