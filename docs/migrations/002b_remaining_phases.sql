-- =====================================================
-- TTS-FIRST v3.1 - PHASE 2-10 (after phase 1 is done)
-- Run this ONLY after 002a_phase1_chapter_builds.sql
-- =====================================================

-- PHASE 2: ATOMIC VERSION ASSIGNMENT RPC
CREATE OR REPLACE FUNCTION create_chapter_build(
    p_chapter_id UUID,
    p_canonical_text TEXT,
    p_canonical_hash TEXT
) RETURNS UUID AS $$
DECLARE
    v_build_id UUID := gen_random_uuid();
    v_next_version INT;
BEGIN
    PERFORM 1 FROM chapters WHERE id = p_chapter_id FOR UPDATE;
    SELECT COALESCE(MAX(canonical_version), 0) + 1 INTO v_next_version
    FROM chapter_builds WHERE chapter_id = p_chapter_id;
    INSERT INTO chapter_builds (id, chapter_id, canonical_text, canonical_hash, canonical_version)
    VALUES (v_build_id, p_chapter_id, p_canonical_text, p_canonical_hash, v_next_version);
    RETURN v_build_id;
END;
$$ LANGUAGE plpgsql;

-- PHASE 3: MODIFY chapters TABLE
ALTER TABLE chapters ADD COLUMN IF NOT EXISTS current_build_id UUID REFERENCES chapter_builds(id);
ALTER TABLE chapters ADD COLUMN IF NOT EXISTS use_paragraph_spans BOOLEAN DEFAULT false;

-- PHASE 4: MODIFY tts_segments TABLE
ALTER TABLE tts_segments ADD COLUMN IF NOT EXISTS build_id UUID REFERENCES chapter_builds(id) ON DELETE CASCADE;
ALTER TABLE tts_segments ADD COLUMN IF NOT EXISTS text_normalized TEXT;
ALTER TABLE tts_segments ADD COLUMN IF NOT EXISTS start_char_offset INT;
ALTER TABLE tts_segments ADD COLUMN IF NOT EXISTS end_char_offset INT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'tts_segments_chapter_id_segment_index_key'
    ) THEN
        ALTER TABLE tts_segments DROP CONSTRAINT tts_segments_chapter_id_segment_index_key;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'tts_segments_chapter_segment_build_unique'
    ) THEN
        ALTER TABLE tts_segments ADD CONSTRAINT tts_segments_chapter_segment_build_unique 
            UNIQUE(chapter_id, segment_index, build_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_tts_segments_build ON tts_segments(build_id, segment_index);
CREATE INDEX IF NOT EXISTS idx_tts_segments_offsets ON tts_segments(build_id, start_char_offset);

-- PHASE 5: CREATE paragraph_spans TABLE
CREATE TABLE IF NOT EXISTS paragraph_spans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id UUID NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    build_id UUID NOT NULL REFERENCES chapter_builds(id) ON DELETE CASCADE,
    paragraph_index INT NOT NULL,
    start_segment_index INT NOT NULL,
    end_segment_index INT NOT NULL,
    start_char_offset INT,
    end_char_offset INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(chapter_id, paragraph_index, build_id),
    CHECK (start_segment_index >= 0),
    CHECK (end_segment_index >= start_segment_index)
);

CREATE INDEX IF NOT EXISTS idx_paragraph_spans_build ON paragraph_spans(build_id, paragraph_index);
CREATE INDEX IF NOT EXISTS idx_paragraph_spans_chapter ON paragraph_spans(chapter_id, paragraph_index);

-- PHASE 6: MODIFY paragraphs TABLE
ALTER TABLE paragraphs ADD COLUMN IF NOT EXISTS source_hash TEXT;
ALTER TABLE paragraphs ADD COLUMN IF NOT EXISTS span_id UUID REFERENCES paragraph_spans(id) ON DELETE SET NULL;
ALTER TABLE paragraphs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- PHASE 7: MODIFY audio_groups TABLE
ALTER TABLE audio_groups ADD COLUMN IF NOT EXISTS build_id UUID REFERENCES chapter_builds(id) ON DELETE CASCADE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'audio_groups_chapter_id_group_index_key'
    ) THEN
        ALTER TABLE audio_groups DROP CONSTRAINT audio_groups_chapter_id_group_index_key;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'audio_groups_chapter_group_build_unique'
    ) THEN
        ALTER TABLE audio_groups ADD CONSTRAINT audio_groups_chapter_group_build_unique 
            UNIQUE(chapter_id, group_index, build_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_audio_groups_build ON audio_groups(build_id, group_index);

-- PHASE 8: RENAME sections → raw_chunks (if exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'sections') THEN
        ALTER TABLE sections RENAME TO raw_chunks;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'raw_chunks') THEN
        ALTER TABLE raw_chunks ADD COLUMN IF NOT EXISTS is_canonical BOOLEAN DEFAULT false;
        COMMENT ON TABLE raw_chunks IS 'AUDIT ONLY: Original GLM output before TTS processing.';
    END IF;
END $$;

-- PHASE 9: VALIDATION FUNCTIONS
CREATE OR REPLACE FUNCTION validate_segment_normalization(p_build_id UUID)
RETURNS TABLE(segment_id UUID, text_differs BOOLEAN) AS $$
BEGIN
    RETURN QUERY
    SELECT ts.id, (regexp_replace(ts.text, '\s+', ' ', 'g') != ts.text_normalized) as text_differs
    FROM tts_segments ts
    WHERE ts.build_id = p_build_id AND ts.text_normalized IS NOT NULL
      AND regexp_replace(ts.text, '\s+', ' ', 'g') != ts.text_normalized;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION validate_span_coverage(p_build_id UUID)
RETURNS TABLE(uncovered_segment_index INT) AS $$
BEGIN
    RETURN QUERY
    SELECT ts.segment_index FROM tts_segments ts
    WHERE ts.build_id = p_build_id
      AND NOT EXISTS (
          SELECT 1 FROM paragraph_spans ps
          WHERE ps.build_id = ts.build_id
            AND ts.segment_index BETWEEN ps.start_segment_index AND ps.end_segment_index
      );
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION validate_no_span_overlaps(p_build_id UUID)
RETURNS TABLE(para1 INT, para2 INT) AS $$
BEGIN
    RETURN QUERY
    SELECT ps1.paragraph_index, ps2.paragraph_index
    FROM paragraph_spans ps1
    JOIN paragraph_spans ps2 ON ps1.build_id = ps2.build_id
      AND ps1.paragraph_index < ps2.paragraph_index
      AND ps1.end_segment_index >= ps2.start_segment_index
    WHERE ps1.build_id = p_build_id;
END;
$$ LANGUAGE plpgsql;

-- PHASE 10: GRANTS
GRANT SELECT ON chapter_builds TO anon, authenticated;
GRANT SELECT ON paragraph_spans TO anon, authenticated;
GRANT EXECUTE ON FUNCTION create_chapter_build(UUID, TEXT, TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION validate_segment_normalization(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION validate_span_coverage(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION validate_no_span_overlaps(UUID) TO authenticated;

-- VERIFICATION
SELECT 'All phases completed!' as status;
