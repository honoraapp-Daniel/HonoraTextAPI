-- =====================================================
-- HONORA STORIES TABLE MIGRATION
-- Run this in Supabase SQL Editor
-- =====================================================

-- 1. CREATE STORIES TABLE (for anthologies/collections)
-- =====================================================
CREATE TABLE IF NOT EXISTS stories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    story_index INT NOT NULL,
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(book_id, story_index)
);

-- 2. ADD STORY_ID TO CHAPTERS
-- =====================================================
ALTER TABLE chapters 
    ADD COLUMN IF NOT EXISTS story_id UUID REFERENCES stories(id) ON DELETE CASCADE;

-- 3. CREATE INDEX FOR PERFORMANCE
-- =====================================================
CREATE INDEX IF NOT EXISTS idx_stories_book ON stories(book_id);
CREATE INDEX IF NOT EXISTS idx_chapters_story ON chapters(story_id);

-- 4. GRANT PERMISSIONS
-- =====================================================
GRANT SELECT ON stories TO anon, authenticated;

-- 5. CREATE VIEW FOR APP (includes story info)
-- =====================================================
CREATE OR REPLACE VIEW chapters_full AS
SELECT 
    c.id,
    c.book_id,
    c.chapter_index,
    c.title,
    c.text,
    c.audio_url,
    c.duration_seconds,
    c.created_at,
    s.id AS story_id,
    s.title AS story_title,
    s.story_index
FROM chapters c
LEFT JOIN stories s ON s.id = c.story_id;

-- =====================================================
-- VERIFICATION
-- Run: SELECT * FROM stories LIMIT 5;
-- Run: SELECT * FROM chapters_full LIMIT 5;
-- =====================================================
