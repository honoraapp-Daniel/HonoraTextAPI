-- =====================================================
-- TTS-FIRST v3.1 - PHASE 1 ONLY
-- Run this FIRST before any other phases
-- =====================================================

-- CREATE chapter_builds TABLE
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

-- Verify it worked:
SELECT 'chapter_builds created successfully!' as status;
