-- =====================================================
-- TTS SEGMENT & GROUP ARCHITECTURE v3.1
-- Audio playback restructuring for seamless streaming
-- =====================================================

-- =====================================================
-- PHASE 1: ADD audio_version TO chapters
-- =====================================================

ALTER TABLE chapters ADD COLUMN IF NOT EXISTS audio_version TEXT DEFAULT 'v1';
-- 'v1' = paragraph/chunk flow (legacy)
-- 'v2' = segment + group flow (new)

COMMENT ON COLUMN chapters.audio_version IS 'Audio architecture version: v1=legacy chunks, v2=segments+groups';

-- =====================================================
-- PHASE 2: CREATE audio_groups TABLE
-- =====================================================

CREATE TABLE IF NOT EXISTS audio_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id UUID NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    group_index INT NOT NULL,
    audio_url TEXT NOT NULL,
    duration_ms INT NOT NULL CHECK (duration_ms > 0),
    start_time_ms INT NOT NULL CHECK (start_time_ms >= 0),
    start_segment_index INT NOT NULL,
    end_segment_index INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(chapter_id, group_index)
);

CREATE INDEX IF NOT EXISTS idx_audio_groups_chapter ON audio_groups(chapter_id, group_index);

COMMENT ON TABLE audio_groups IS 'Concatenated audio files for seamless playback (20-60s each)';
COMMENT ON COLUMN audio_groups.start_time_ms IS 'Prefix-sum: absolute start time in chapter timeline for O(1) resume';

-- =====================================================
-- PHASE 3: CREATE tts_segments TABLE
-- =====================================================

CREATE TABLE IF NOT EXISTS tts_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id UUID NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    segment_index INT NOT NULL,
    text TEXT NOT NULL,
    paragraph_id UUID REFERENCES paragraphs(id),
    duration_ms INT NOT NULL CHECK (duration_ms > 0),
    group_id UUID NOT NULL REFERENCES audio_groups(id) ON DELETE CASCADE,
    offset_in_group_ms INT NOT NULL CHECK (offset_in_group_ms >= 0),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(chapter_id, segment_index)
);

CREATE INDEX IF NOT EXISTS idx_tts_segments_chapter ON tts_segments(chapter_id, segment_index);
CREATE INDEX IF NOT EXISTS idx_tts_segments_group ON tts_segments(group_id, offset_in_group_ms);
CREATE INDEX IF NOT EXISTS idx_tts_segments_paragraph ON tts_segments(paragraph_id);

COMMENT ON TABLE tts_segments IS 'Text segments for TTS generation and UI highlighting (60-420 chars)';
COMMENT ON COLUMN tts_segments.offset_in_group_ms IS 'Start time within group audio file for highlighting sync';

-- =====================================================
-- PHASE 4: CREATE user_audio_progress TABLE
-- =====================================================

CREATE TABLE IF NOT EXISTS user_audio_progress (
    user_id UUID NOT NULL,
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_id UUID REFERENCES chapters(id) ON DELETE SET NULL,
    chapter_time_ms INT DEFAULT 0 CHECK (chapter_time_ms >= 0),
    playback_speed REAL DEFAULT 1.0 CHECK (playback_speed > 0 AND playback_speed <= 3.0),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    PRIMARY KEY (user_id, book_id)
);

CREATE INDEX IF NOT EXISTS idx_user_progress_user ON user_audio_progress(user_id);

COMMENT ON TABLE user_audio_progress IS 'User playback position - single source of truth';
COMMENT ON COLUMN user_audio_progress.chapter_time_ms IS 'Absolute position in chapter timeline (not chunk-based)';

-- RLS for user_audio_progress
ALTER TABLE user_audio_progress ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own progress" ON user_audio_progress
    FOR SELECT USING (auth.uid() = user_id);
    
CREATE POLICY "Users write own progress" ON user_audio_progress
    FOR INSERT WITH CHECK (auth.uid() = user_id);
    
CREATE POLICY "Users update own progress" ON user_audio_progress
    FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- =====================================================
-- PHASE 5: RPC FUNCTIONS
-- =====================================================

-- get_chapter_manifest_v3: Returns all data needed for playback
CREATE OR REPLACE FUNCTION get_chapter_manifest_v3(p_chapter_id UUID)
RETURNS JSONB AS $$
BEGIN
    RETURN jsonb_build_object(
        'chapter_id', p_chapter_id,
        'audio_version', (SELECT audio_version FROM chapters WHERE id = p_chapter_id),
        'groups', COALESCE(
            (SELECT jsonb_agg(
                jsonb_build_object(
                    'group_id', id,
                    'group_index', group_index,
                    'audio_url', audio_url,
                    'duration_ms', duration_ms,
                    'start_time_ms', start_time_ms,
                    'start_segment_index', start_segment_index,
                    'end_segment_index', end_segment_index
                ) ORDER BY group_index
            ) FROM audio_groups WHERE chapter_id = p_chapter_id),
            '[]'::jsonb
        )
    );
END;
$$ LANGUAGE plpgsql;

-- get_group_segments: Returns segments for UI highlighting (lazy load)
CREATE OR REPLACE FUNCTION get_group_segments(p_group_id UUID)
RETURNS JSONB AS $$
BEGIN
    RETURN COALESCE(
        (SELECT jsonb_agg(
            jsonb_build_object(
                'segment_index', segment_index,
                'paragraph_id', paragraph_id,
                'offset_in_group_ms', offset_in_group_ms,
                'duration_ms', duration_ms,
                'text', text
            ) ORDER BY segment_index
        ) FROM tts_segments WHERE group_id = p_group_id),
        '[]'::jsonb
    );
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- PHASE 6: GRANTS
-- =====================================================

GRANT SELECT ON audio_groups TO anon, authenticated;
GRANT SELECT ON tts_segments TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON user_audio_progress TO authenticated;
GRANT EXECUTE ON FUNCTION get_chapter_manifest_v3(UUID) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION get_group_segments(UUID) TO anon, authenticated;

-- =====================================================
-- VERIFICATION QUERIES
-- =====================================================

-- Check tables exist:
-- SELECT table_name FROM information_schema.tables 
-- WHERE table_schema = 'public' AND table_name IN ('audio_groups', 'tts_segments', 'user_audio_progress');

-- Check audio_version column:
-- SELECT column_name, data_type FROM information_schema.columns 
-- WHERE table_name = 'chapters' AND column_name = 'audio_version';

-- Check RPC functions:
-- SELECT routine_name FROM information_schema.routines 
-- WHERE routine_schema = 'public' AND routine_name IN ('get_chapter_manifest_v3', 'get_group_segments');
