-- =====================================================
-- TTS-FIRST ARCHITECTURE v3.1 MIGRATION
-- Schema changes for paragraph_spans + build versioning
-- =====================================================
-- 
-- PREREQUISITES: Run 001_tts_segments_groups.sql first
-- 
-- This migration implements:
-- 1. chapter_builds table (immutable builds with atomic versioning)
-- 2. Modify chapters (current_build_id, use_paragraph_spans)
-- 3. Modify tts_segments (text_normalized, char offsets, build_id)
-- 4. paragraph_spans table (Gemini-driven segment grouping)
-- 5. Modify paragraphs (cache with source_hash)
-- 6. Modify audio_groups (build_id)
-- 7. Rename sections → raw_chunks
-- =====================================================

-- =====================================================
-- PHASE 1: CREATE chapter_builds TABLE
-- =====================================================

CREATE TABLE IF NOT EXISTS chapter_builds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id UUID NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    canonical_text TEXT NOT NULL,
    canonical_hash TEXT NOT NULL,
    canonical_version INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(chapter_id, canonical_version)
);

CREATE INDEX IF NOT EXISTS idx_chapter_builds_chapter ON chapter_builds(chapter_id, canonical_version DESC);

COMMENT ON TABLE chapter_builds IS 'Immutable build snapshots with atomic versioning per chapter';
COMMENT ON COLUMN chapter_builds.canonical_text IS 'Joined text_normalized from segments - immutable per build';
COMMENT ON COLUMN chapter_builds.canonical_hash IS 'SHA256 of canonical_text for integrity checks';
COMMENT ON COLUMN chapter_builds.canonical_version IS 'Atomic per-chapter version (1, 2, 3...)';

-- =====================================================
-- PHASE 2: ATOMIC VERSION ASSIGNMENT RPC
-- =====================================================

CREATE OR REPLACE FUNCTION create_chapter_build(
    p_chapter_id UUID,
    p_canonical_text TEXT,
    p_canonical_hash TEXT
) RETURNS UUID AS $$
DECLARE
    v_build_id UUID := gen_random_uuid();
    v_next_version INT;
BEGIN
    -- Lock chapter row to prevent concurrent version assignment
    PERFORM 1 FROM chapters WHERE id = p_chapter_id FOR UPDATE;
    
    -- Compute next version atomically
    SELECT COALESCE(MAX(canonical_version), 0) + 1 INTO v_next_version
    FROM chapter_builds WHERE chapter_id = p_chapter_id;
    
    -- Insert new build
    INSERT INTO chapter_builds (id, chapter_id, canonical_text, canonical_hash, canonical_version)
    VALUES (v_build_id, p_chapter_id, p_canonical_text, p_canonical_hash, v_next_version);
    
    RETURN v_build_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_chapter_build IS 'Atomic build creation with row-level locking for version assignment';

-- =====================================================
-- PHASE 3: MODIFY chapters TABLE
-- =====================================================

ALTER TABLE chapters ADD COLUMN IF NOT EXISTS current_build_id UUID REFERENCES chapter_builds(id);
ALTER TABLE chapters ADD COLUMN IF NOT EXISTS use_paragraph_spans BOOLEAN DEFAULT false;

COMMENT ON COLUMN chapters.current_build_id IS 'Active build for this chapter - all queries filter by this';
COMMENT ON COLUMN chapters.use_paragraph_spans IS 'Feature flag: true=use spans, false=legacy paragraphs';

-- =====================================================
-- PHASE 4: MODIFY tts_segments TABLE
-- =====================================================

-- Add build_id reference
ALTER TABLE tts_segments ADD COLUMN IF NOT EXISTS build_id UUID REFERENCES chapter_builds(id) ON DELETE CASCADE;

-- Add text_normalized (semantic equivalent to text, whitespace-only difference)
ALTER TABLE tts_segments ADD COLUMN IF NOT EXISTS text_normalized TEXT;

-- Add character offsets
ALTER TABLE tts_segments ADD COLUMN IF NOT EXISTS start_char_offset INT;
ALTER TABLE tts_segments ADD COLUMN IF NOT EXISTS end_char_offset INT;

-- Update unique constraint to include build_id
-- First drop existing constraint if exists, then recreate
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'tts_segments_chapter_id_segment_index_key'
    ) THEN
        ALTER TABLE tts_segments DROP CONSTRAINT tts_segments_chapter_id_segment_index_key;
    END IF;
END $$;

-- Create new unique constraint with build_id
ALTER TABLE tts_segments ADD CONSTRAINT tts_segments_chapter_segment_build_unique 
    UNIQUE(chapter_id, segment_index, build_id);

-- Create indexes for offset lookups
CREATE INDEX IF NOT EXISTS idx_tts_segments_build ON tts_segments(build_id, segment_index);
CREATE INDEX IF NOT EXISTS idx_tts_segments_offsets ON tts_segments(build_id, start_char_offset);

COMMENT ON COLUMN tts_segments.build_id IS 'Links segment to specific chapter build';
COMMENT ON COLUMN tts_segments.text_normalized IS 'NFKC + whitespace normalized - MUST equal normalize(text)';
COMMENT ON COLUMN tts_segments.start_char_offset IS 'Start position in canonical_text (cursor-assigned)';
COMMENT ON COLUMN tts_segments.end_char_offset IS 'End position in canonical_text (exclusive)';

-- =====================================================
-- PHASE 5: CREATE paragraph_spans TABLE
-- =====================================================

CREATE TABLE IF NOT EXISTS paragraph_spans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id UUID NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    build_id UUID NOT NULL REFERENCES chapter_builds(id) ON DELETE CASCADE,
    paragraph_index INT NOT NULL,
    
    -- SOURCE OF TRUTH (from Gemini):
    start_segment_index INT NOT NULL,
    end_segment_index INT NOT NULL,
    
    -- DERIVED (computed from segment offsets):
    start_char_offset INT,
    end_char_offset INT,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(chapter_id, paragraph_index, build_id),
    
    -- Ensure valid segment range
    CHECK (start_segment_index >= 0),
    CHECK (end_segment_index >= start_segment_index)
);

CREATE INDEX IF NOT EXISTS idx_paragraph_spans_build ON paragraph_spans(build_id, paragraph_index);
CREATE INDEX IF NOT EXISTS idx_paragraph_spans_chapter ON paragraph_spans(chapter_id, paragraph_index);

COMMENT ON TABLE paragraph_spans IS 'Paragraph definitions as segment ranges - Gemini output is source of truth';
COMMENT ON COLUMN paragraph_spans.start_segment_index IS 'TRUTH: First segment in paragraph (from Gemini)';
COMMENT ON COLUMN paragraph_spans.end_segment_index IS 'TRUTH: Last segment in paragraph (from Gemini)';
COMMENT ON COLUMN paragraph_spans.start_char_offset IS 'DERIVED: Computed from segment offsets';
COMMENT ON COLUMN paragraph_spans.end_char_offset IS 'DERIVED: Computed from segment offsets';

-- =====================================================
-- PHASE 6: MODIFY paragraphs TABLE (CACHE)
-- =====================================================

ALTER TABLE paragraphs ADD COLUMN IF NOT EXISTS source_hash TEXT;
ALTER TABLE paragraphs ADD COLUMN IF NOT EXISTS span_id UUID REFERENCES paragraph_spans(id) ON DELETE SET NULL;
ALTER TABLE paragraphs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

COMMENT ON COLUMN paragraphs.source_hash IS 'SHA256(RENDER(segments)) - for cache invalidation';
COMMENT ON COLUMN paragraphs.span_id IS 'Links to paragraph_spans for regeneration';
COMMENT ON COLUMN paragraphs.text IS 'CACHE: Regenerable from RENDER(segments in span)';

-- =====================================================
-- PHASE 7: MODIFY audio_groups TABLE
-- =====================================================

ALTER TABLE audio_groups ADD COLUMN IF NOT EXISTS build_id UUID REFERENCES chapter_builds(id) ON DELETE CASCADE;

-- Update unique constraint
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'audio_groups_chapter_id_group_index_key'
    ) THEN
        ALTER TABLE audio_groups DROP CONSTRAINT audio_groups_chapter_id_group_index_key;
    END IF;
END $$;

ALTER TABLE audio_groups ADD CONSTRAINT audio_groups_chapter_group_build_unique 
    UNIQUE(chapter_id, group_index, build_id);

CREATE INDEX IF NOT EXISTS idx_audio_groups_build ON audio_groups(build_id, group_index);

-- =====================================================
-- PHASE 8: RENAME sections → raw_chunks
-- =====================================================

-- Check if sections table exists before renaming
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'sections') THEN
        ALTER TABLE sections RENAME TO raw_chunks;
    END IF;
END $$;

-- Add is_canonical flag if table exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'raw_chunks') THEN
        ALTER TABLE raw_chunks ADD COLUMN IF NOT EXISTS is_canonical BOOLEAN DEFAULT false;
    END IF;
END $$;

-- Only add comment if raw_chunks exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'raw_chunks') THEN
        COMMENT ON TABLE raw_chunks IS 'AUDIT ONLY: Original GLM output before TTS processing. NOT source of truth.';
    END IF;
END $$;

-- =====================================================
-- PHASE 9: VALIDATION FUNCTIONS
-- =====================================================

-- Function to validate text/text_normalized contract
CREATE OR REPLACE FUNCTION validate_segment_normalization(p_build_id UUID)
RETURNS TABLE(segment_id UUID, text_differs BOOLEAN) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ts.id,
        (regexp_replace(ts.text, '\s+', ' ', 'g') != ts.text_normalized) as text_differs
    FROM tts_segments ts
    WHERE ts.build_id = p_build_id
      AND ts.text_normalized IS NOT NULL
      AND regexp_replace(ts.text, '\s+', ' ', 'g') != ts.text_normalized;
END;
$$ LANGUAGE plpgsql;

-- Function to check segment coverage (no gaps in paragraph_spans)
CREATE OR REPLACE FUNCTION validate_span_coverage(p_build_id UUID)
RETURNS TABLE(uncovered_segment_index INT) AS $$
BEGIN
    RETURN QUERY
    SELECT ts.segment_index
    FROM tts_segments ts
    WHERE ts.build_id = p_build_id
      AND NOT EXISTS (
          SELECT 1 FROM paragraph_spans ps
          WHERE ps.build_id = ts.build_id
            AND ts.segment_index BETWEEN ps.start_segment_index AND ps.end_segment_index
      );
END;
$$ LANGUAGE plpgsql;

-- Function to check no span overlaps
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

-- =====================================================
-- PHASE 10: GRANTS
-- =====================================================

GRANT SELECT ON chapter_builds TO anon, authenticated;
GRANT SELECT ON paragraph_spans TO anon, authenticated;
GRANT EXECUTE ON FUNCTION create_chapter_build(UUID, TEXT, TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION validate_segment_normalization(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION validate_span_coverage(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION validate_no_span_overlaps(UUID) TO authenticated;

-- =====================================================
-- VERIFICATION QUERIES (run after migration)
-- =====================================================

-- Check all new tables exist:
-- SELECT table_name FROM information_schema.tables 
-- WHERE table_schema = 'public' 
--   AND table_name IN ('chapter_builds', 'paragraph_spans', 'raw_chunks');

-- Check new columns on chapters:
-- SELECT column_name FROM information_schema.columns 
-- WHERE table_name = 'chapters' 
--   AND column_name IN ('current_build_id', 'use_paragraph_spans');

-- Check new columns on tts_segments:
-- SELECT column_name FROM information_schema.columns 
-- WHERE table_name = 'tts_segments' 
--   AND column_name IN ('build_id', 'text_normalized', 'start_char_offset', 'end_char_offset');

-- Check RPC functions:
-- SELECT routine_name FROM information_schema.routines 
-- WHERE routine_schema = 'public' 
--   AND routine_name IN ('create_chapter_build', 'validate_segment_normalization', 'validate_span_coverage', 'validate_no_span_overlaps');
