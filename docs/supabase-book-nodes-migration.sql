-- =====================================================
-- HONORA BOOK NODES MIGRATION
-- Complete restructuring of book structure
-- 
-- Run this in Supabase SQL Editor AFTER deleting test data
-- =====================================================

-- =====================================================
-- PHASE 1: CLEANUP OLD STRUCTURE TABLES
-- =====================================================

-- Drop old fragmented tables (they're empty after cleanup)
DROP TABLE IF EXISTS parts CASCADE;
DROP TABLE IF EXISTS stories CASCADE;

-- Drop old columns from chapters that will be replaced
ALTER TABLE chapters DROP COLUMN IF EXISTS story_id;
ALTER TABLE chapters DROP COLUMN IF EXISTS part_id;
ALTER TABLE chapters DROP COLUMN IF EXISTS content_type;

-- =====================================================
-- PHASE 2: RENAME sections → tts_chunks
-- =====================================================

-- Rename the table
ALTER TABLE sections RENAME TO tts_chunks;

-- Rename the index column for clarity
ALTER TABLE tts_chunks RENAME COLUMN section_index TO chunk_index;

-- Update indexes
DROP INDEX IF EXISTS idx_sections_chapter;
CREATE INDEX IF NOT EXISTS idx_tts_chunks_chapter ON tts_chunks(chapter_id, chunk_index);

-- =====================================================
-- PHASE 3: CREATE book_nodes TABLE (THE CORE)
-- =====================================================

CREATE TABLE book_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    parent_id UUID REFERENCES book_nodes(id) ON DELETE CASCADE,
    
    -- Node identity
    node_type TEXT NOT NULL CHECK (node_type IN (
        -- Front matter
        'front_matter', 'toc', 'preface', 'foreword', 'introduction',
        'dedication', 'acknowledgments', 'prologue', 'authors_note',
        -- Main content
        'part', 'book', 'volume', 'section', 'chapter', 'subsection',
        'main_work', 'treatise', 'fragment', 'letter', 'discourse',
        'essay', 'sermon', 'dialogue', 'meditation',
        -- Back matter
        'epilogue', 'appendix', 'glossary', 'bibliography', 'index',
        'back_matter', 'notes', 'afterword', 'postscript', 'endnotes'
    )),
    
    -- Ordering (lexicographic sort, max 5 levels)
    order_key TEXT NOT NULL,  -- e.g., "0001", "0002.0001", "0002.0001.0001"
    depth INT GENERATED ALWAYS AS (
        CARDINALITY(STRING_TO_ARRAY(order_key, '.'))
    ) STORED,
    
    -- Titles
    display_title TEXT NOT NULL,      -- What user sees: "Chapter 1: The Beginning"
    source_title TEXT,                -- Raw from TOC: "CHAPTER I. THE BEGINNING"
    
    -- Flags
    exclude_from_frontend BOOLEAN DEFAULT FALSE,  -- Hide from app navigation
    exclude_from_audio BOOLEAN DEFAULT FALSE,     -- Skip during TTS generation
    has_content BOOLEAN DEFAULT TRUE,             -- Does this node have paragraphs?
    
    -- Metadata
    confidence REAL DEFAULT 1.0,      -- AI detection confidence (0-1)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    UNIQUE(book_id, order_key),
    CHECK (depth <= 5)  -- Max 5 levels of nesting
);

-- Critical indexes
CREATE INDEX idx_book_nodes_book_order ON book_nodes(book_id, order_key);
CREATE INDEX idx_book_nodes_parent ON book_nodes(parent_id);
CREATE INDEX idx_book_nodes_type ON book_nodes(book_id, node_type);
CREATE INDEX idx_book_nodes_navigable ON book_nodes(book_id) 
    WHERE exclude_from_frontend = FALSE AND has_content = TRUE;

-- =====================================================
-- PHASE 4: CREATE JOIN TABLE book_node_paragraphs
-- =====================================================

-- Links structural nodes to their paragraph content
CREATE TABLE book_node_paragraphs (
    node_id UUID NOT NULL REFERENCES book_nodes(id) ON DELETE CASCADE,
    paragraph_id UUID NOT NULL REFERENCES paragraphs(id) ON DELETE CASCADE,
    position_in_node INT NOT NULL,  -- Order within this node (0-indexed)
    
    PRIMARY KEY (node_id, paragraph_id),
    UNIQUE (node_id, position_in_node)  -- Ensure no duplicate positions
);

CREATE INDEX idx_bnp_node_order ON book_node_paragraphs(node_id, position_in_node);
CREATE INDEX idx_bnp_paragraph ON book_node_paragraphs(paragraph_id);

-- =====================================================
-- PHASE 5: CREATE JOIN TABLE paragraph_tts_chunks
-- =====================================================

-- Links paragraphs to their TTS audio chunks
CREATE TABLE paragraph_tts_chunks (
    paragraph_id UUID NOT NULL REFERENCES paragraphs(id) ON DELETE CASCADE,
    tts_chunk_id UUID NOT NULL REFERENCES tts_chunks(id) ON DELETE CASCADE,
    position_in_paragraph INT NOT NULL,  -- Order within paragraph (0-indexed)
    
    PRIMARY KEY (paragraph_id, tts_chunk_id),
    UNIQUE (paragraph_id, position_in_paragraph)
);

CREATE INDEX idx_ptc_paragraph_order ON paragraph_tts_chunks(paragraph_id, position_in_paragraph);
CREATE INDEX idx_ptc_chunk ON paragraph_tts_chunks(tts_chunk_id);

-- =====================================================
-- PHASE 6: UPDATE chapters TABLE
-- =====================================================

-- Add foreign key to link chapters to their book_node
-- This allows gradual migration - chapters can still exist independently
ALTER TABLE chapters 
    ADD COLUMN IF NOT EXISTS node_id UUID REFERENCES book_nodes(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_chapters_node ON chapters(node_id);

-- =====================================================
-- PHASE 7: CREATE VIEWS FOR APP COMPATIBILITY
-- =====================================================

-- Main view: Full node information with parent context
CREATE OR REPLACE VIEW nodes_full AS
SELECT 
    bn.id,
    bn.book_id,
    bn.parent_id,
    bn.node_type,
    bn.order_key,
    bn.depth,
    bn.display_title,
    bn.source_title,
    bn.exclude_from_frontend,
    bn.exclude_from_audio,
    bn.has_content,
    bn.confidence,
    bn.created_at,
    -- Parent info
    parent.display_title AS parent_title,
    parent.node_type AS parent_type,
    parent.order_key AS parent_order_key,
    -- Paragraph count
    (SELECT COUNT(*) FROM book_node_paragraphs bnp WHERE bnp.node_id = bn.id) AS paragraph_count,
    -- TTS chunk count (via paragraphs)
    (SELECT COUNT(*) 
     FROM paragraph_tts_chunks ptc 
     JOIN book_node_paragraphs bnp ON bnp.paragraph_id = ptc.paragraph_id 
     WHERE bnp.node_id = bn.id) AS tts_chunk_count
FROM book_nodes bn
LEFT JOIN book_nodes parent ON parent.id = bn.parent_id
ORDER BY bn.book_id, bn.order_key;

-- Navigation view: Only navigable nodes (for app TOC)
CREATE OR REPLACE VIEW nodes_navigation AS
SELECT 
    bn.id,
    bn.book_id,
    bn.parent_id,
    bn.node_type,
    bn.order_key,
    bn.depth,
    bn.display_title,
    bn.has_content,
    -- Children count
    (SELECT COUNT(*) FROM book_nodes child 
     WHERE child.parent_id = bn.id AND child.exclude_from_frontend = FALSE) AS children_count
FROM book_nodes bn
WHERE bn.exclude_from_frontend = FALSE
ORDER BY bn.book_id, bn.order_key;

-- Playback view: Ordered content for a node (paragraphs + chunks)
CREATE OR REPLACE VIEW node_playback_content AS
SELECT 
    bn.id AS node_id,
    bn.book_id,
    bn.display_title AS node_title,
    bnp.position_in_node AS paragraph_position,
    p.id AS paragraph_id,
    p.text AS paragraph_text,
    ptc.position_in_paragraph AS chunk_position,
    tc.id AS tts_chunk_id,
    tc.text_ref AS chunk_text,
    tc.start_ms,
    tc.end_ms
FROM book_nodes bn
JOIN book_node_paragraphs bnp ON bnp.node_id = bn.id
JOIN paragraphs p ON p.id = bnp.paragraph_id
LEFT JOIN paragraph_tts_chunks ptc ON ptc.paragraph_id = p.id
LEFT JOIN tts_chunks tc ON tc.id = ptc.tts_chunk_id
WHERE bn.exclude_from_audio = FALSE
ORDER BY bn.order_key, bnp.position_in_node, ptc.position_in_paragraph;

-- Book structure tree view (for debugging/admin)
CREATE OR REPLACE VIEW book_structure_tree AS
WITH RECURSIVE tree AS (
    -- Root nodes (no parent)
    SELECT 
        id, book_id, parent_id, node_type, order_key, depth,
        display_title,
        display_title AS path,
        ARRAY[order_key] AS order_path
    FROM book_nodes
    WHERE parent_id IS NULL
    
    UNION ALL
    
    -- Child nodes
    SELECT 
        bn.id, bn.book_id, bn.parent_id, bn.node_type, bn.order_key, bn.depth,
        bn.display_title,
        tree.path || ' > ' || bn.display_title,
        tree.order_path || bn.order_key
    FROM book_nodes bn
    JOIN tree ON tree.id = bn.parent_id
)
SELECT 
    id, book_id, parent_id, node_type, order_key, depth,
    display_title,
    path AS full_path,
    REPEAT('  ', depth - 1) || display_title AS indented_title
FROM tree
ORDER BY book_id, order_path;

-- =====================================================
-- PHASE 8: HELPER FUNCTIONS
-- =====================================================

-- Function to generate next order_key at a given level
CREATE OR REPLACE FUNCTION generate_order_key(
    p_book_id UUID,
    p_parent_id UUID DEFAULT NULL
) RETURNS TEXT AS $$
DECLARE
    v_max_key TEXT;
    v_prefix TEXT;
    v_next_num INT;
BEGIN
    -- Get parent's order_key as prefix
    IF p_parent_id IS NOT NULL THEN
        SELECT order_key INTO v_prefix FROM book_nodes WHERE id = p_parent_id;
        v_prefix := v_prefix || '.';
    ELSE
        v_prefix := '';
    END IF;
    
    -- Find highest existing key at this level
    SELECT MAX(order_key) INTO v_max_key
    FROM book_nodes
    WHERE book_id = p_book_id
      AND (p_parent_id IS NULL AND parent_id IS NULL 
           OR parent_id = p_parent_id);
    
    IF v_max_key IS NULL THEN
        v_next_num := 1;
    ELSE
        -- Extract last segment and increment
        v_next_num := CAST(
            SPLIT_PART(v_max_key, '.', 
                CARDINALITY(STRING_TO_ARRAY(v_max_key, '.'))
            ) AS INT
        ) + 1;
    END IF;
    
    RETURN v_prefix || LPAD(v_next_num::TEXT, 4, '0');
END;
$$ LANGUAGE plpgsql;

-- Function to get all paragraphs for a node in playback order
CREATE OR REPLACE FUNCTION get_node_paragraphs(p_node_id UUID)
RETURNS TABLE (
    para_id UUID,
    content_text TEXT,
    pos INT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.id,
        p.text,
        bnp.position_in_node
    FROM paragraphs p
    JOIN book_node_paragraphs bnp ON bnp.paragraph_id = p.id
    WHERE bnp.node_id = p_node_id
    ORDER BY bnp.position_in_node;
END;
$$ LANGUAGE plpgsql;

-- Function to get all TTS chunks for a node in playback order
CREATE OR REPLACE FUNCTION get_node_tts_chunks(p_node_id UUID)
RETURNS TABLE (
    chunk_id UUID,
    chunk_text TEXT,
    chunk_start_ms INT,
    chunk_end_ms INT,
    para_id UUID,
    para_pos INT,
    chunk_pos INT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        tc.id,
        tc.text_ref,
        tc.start_ms,
        tc.end_ms,
        p.id,
        bnp.position_in_node,
        ptc.position_in_paragraph
    FROM book_node_paragraphs bnp
    JOIN paragraphs p ON p.id = bnp.paragraph_id
    JOIN paragraph_tts_chunks ptc ON ptc.paragraph_id = p.id
    JOIN tts_chunks tc ON tc.id = ptc.tts_chunk_id
    WHERE bnp.node_id = p_node_id
    ORDER BY bnp.position_in_node, ptc.position_in_paragraph;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- PHASE 9: TRIGGERS FOR updated_at
-- =====================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER book_nodes_updated_at
    BEFORE UPDATE ON book_nodes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- =====================================================
-- PHASE 10: GRANT PERMISSIONS
-- =====================================================

GRANT SELECT ON book_nodes TO anon, authenticated;
GRANT SELECT ON book_node_paragraphs TO anon, authenticated;
GRANT SELECT ON paragraph_tts_chunks TO anon, authenticated;
GRANT SELECT ON tts_chunks TO anon, authenticated;
GRANT SELECT ON nodes_full TO anon, authenticated;
GRANT SELECT ON nodes_navigation TO anon, authenticated;
GRANT SELECT ON node_playback_content TO anon, authenticated;
GRANT SELECT ON book_structure_tree TO anon, authenticated;

-- =====================================================
-- PHASE 11: ADD RLS POLICIES (optional, for future)
-- =====================================================

-- Enable RLS on new tables
ALTER TABLE book_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE book_node_paragraphs ENABLE ROW LEVEL SECURITY;
ALTER TABLE paragraph_tts_chunks ENABLE ROW LEVEL SECURITY;

-- Allow public read access (same as existing pattern)
CREATE POLICY "Public read access" ON book_nodes FOR SELECT USING (true);
CREATE POLICY "Public read access" ON book_node_paragraphs FOR SELECT USING (true);
CREATE POLICY "Public read access" ON paragraph_tts_chunks FOR SELECT USING (true);

-- =====================================================
-- VERIFICATION QUERIES (run after migration)
-- =====================================================

-- Check tables exist
-- SELECT table_name FROM information_schema.tables 
-- WHERE table_schema = 'public' 
-- AND table_name IN ('book_nodes', 'book_node_paragraphs', 'paragraph_tts_chunks', 'tts_chunks');

-- Check views exist
-- SELECT table_name FROM information_schema.views 
-- WHERE table_schema = 'public'
-- AND table_name IN ('nodes_full', 'nodes_navigation', 'node_playback_content', 'book_structure_tree');

-- Check functions exist
-- SELECT routine_name FROM information_schema.routines 
-- WHERE routine_schema = 'public'
-- AND routine_name IN ('generate_order_key', 'get_node_paragraphs', 'get_node_tts_chunks');

-- =====================================================
-- DONE! 
-- Next: Update pipeline code to use book_nodes
-- =====================================================
