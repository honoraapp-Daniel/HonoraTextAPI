-- =====================================================
-- HONORA COLLECTIONS MIGRATION
-- Run this in Supabase SQL Editor
-- =====================================================

-- 1. DROP OLD SELECTIONS TABLES (if empty)
-- =====================================================
-- First verify they're empty, then drop
DROP TABLE IF EXISTS book_selections;
DROP TABLE IF EXISTS selections;

-- 2. CREATE COLLECTIONS TABLE (with hierarchy)
-- =====================================================
CREATE TABLE IF NOT EXISTS collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE,
    description TEXT,
    parent_id UUID REFERENCES collections(id) ON DELETE SET NULL,
    display_order INT DEFAULT 0,
    icon_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. CREATE JUNCTION TABLE
-- =====================================================
CREATE TABLE IF NOT EXISTS book_collections (
    book_id UUID REFERENCES books(id) ON DELETE CASCADE,
    collection_id UUID REFERENCES collections(id) ON DELETE CASCADE,
    display_order INT DEFAULT 0,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (book_id, collection_id)
);

-- 4. CREATE INDEXES
-- =====================================================
CREATE INDEX IF NOT EXISTS idx_collections_parent ON collections(parent_id);
CREATE INDEX IF NOT EXISTS idx_collections_slug ON collections(slug);
CREATE INDEX IF NOT EXISTS idx_book_collections_collection ON book_collections(collection_id);

-- 5. GRANT PERMISSIONS
-- =====================================================
GRANT SELECT ON collections TO anon, authenticated;
GRANT SELECT ON book_collections TO anon, authenticated;

-- 6. SEED COLLECTIONS (with hierarchy)
-- =====================================================

-- === MAIN SECTIONS (parent_id = NULL) ===
INSERT INTO collections (name, slug, description, display_order) VALUES
    ('Forbidden Books', 'forbidden-books', 'Books that challenge conventional wisdom and push boundaries', 1),
    ('Grimoires & Magic', 'grimoires-magic', 'Practical mysticism and ritual texts', 2),
    ('Hidden History', 'hidden-history', 'What they don''t teach in schools', 3),
    ('Mind & Reality', 'mind-reality', 'Exploring consciousness and existence', 4),
    ('The Unexplained', 'the-unexplained', 'Fortean phenomena and mysteries', 5),
    ('Sacred Traditions', 'sacred-traditions', 'Religious and spiritual wisdom', 6),
    ('Myths & Legends', 'myths-legends', 'Stories that shaped humanity', 7),
    ('Uncomfortable Truths', 'uncomfortable-truths', 'Books that challenge and disturb', 8),
    ('Honora Originals', 'honora-originals', 'Curated by the Honora team', 9)
ON CONFLICT (slug) DO NOTHING;

-- === SUB-COLLECTIONS ===

-- Under "Forbidden Books"
INSERT INTO collections (name, slug, parent_id, display_order)
SELECT name, slug, p.id, display_order FROM (VALUES
    ('Lost Knowledge', 'lost-knowledge', 1),
    ('Initiation Texts', 'initiation-texts', 2),
    ('Not for Everyone', 'not-for-everyone', 3),
    ('The Dark Path', 'the-dark-path', 4),
    ('The Light Path', 'the-light-path', 5)
) AS sub(name, slug, display_order)
CROSS JOIN (SELECT id FROM collections WHERE slug = 'forbidden-books') p
ON CONFLICT (slug) DO NOTHING;

-- Under "Grimoires & Magic"
INSERT INTO collections (name, slug, parent_id, display_order)
SELECT name, slug, p.id, display_order FROM (VALUES
    ('Grimoires & Rituals', 'grimoires-rituals', 1),
    ('Hermetic Wisdom', 'hermetic-wisdom', 2),
    ('Alchemy of the Self', 'alchemy-of-the-self', 3),
    ('Symbols & Codes', 'symbols-codes', 4),
    ('Sacred Sexuality', 'sacred-sexuality-collection', 5)
) AS sub(name, slug, display_order)
CROSS JOIN (SELECT id FROM collections WHERE slug = 'grimoires-magic') p
ON CONFLICT (slug) DO NOTHING;

-- Under "Hidden History"
INSERT INTO collections (name, slug, parent_id, display_order)
SELECT name, slug, p.id, display_order FROM (VALUES
    ('Lost Civilizations', 'lost-civilizations', 1),
    ('Maps That Shouldn''t Exist', 'maps-that-shouldnt-exist', 2),
    ('Before Official History', 'before-official-history', 3)
) AS sub(name, slug, display_order)
CROSS JOIN (SELECT id FROM collections WHERE slug = 'hidden-history') p
ON CONFLICT (slug) DO NOTHING;

-- Under "Mind & Reality"
INSERT INTO collections (name, slug, parent_id, display_order)
SELECT name, slug, p.id, display_order FROM (VALUES
    ('What Is Reality?', 'what-is-reality', 1),
    ('The Nature of Evil', 'nature-of-evil', 2),
    ('Beyond Death', 'beyond-death', 3),
    ('Prophets & Prophecies', 'prophets-prophecies', 4)
) AS sub(name, slug, display_order)
CROSS JOIN (SELECT id FROM collections WHERE slug = 'mind-reality') p
ON CONFLICT (slug) DO NOTHING;

-- Under "The Unexplained"
INSERT INTO collections (name, slug, parent_id, display_order)
SELECT name, slug, p.id, display_order FROM (VALUES
    ('Fortean Files', 'fortean-files', 1),
    ('UFOs & Other Worlds', 'ufos-other-worlds', 2),
    ('Parapsychology', 'parapsychology-collection', 3)
) AS sub(name, slug, display_order)
CROSS JOIN (SELECT id FROM collections WHERE slug = 'the-unexplained') p
ON CONFLICT (slug) DO NOTHING;

-- Under "Sacred Traditions"
INSERT INTO collections (name, slug, parent_id, display_order)
SELECT name, slug, p.id, display_order FROM (VALUES
    ('Sacred Foundations', 'sacred-foundations', 1),
    ('Mystics Within Religion', 'mystics-within-religion', 2),
    ('Comparative Faiths', 'comparative-faiths', 3),
    ('The East Knows Something', 'the-east-knows-something', 4)
) AS sub(name, slug, display_order)
CROSS JOIN (SELECT id FROM collections WHERE slug = 'sacred-traditions') p
ON CONFLICT (slug) DO NOTHING;

-- Under "Myths & Legends"
INSERT INTO collections (name, slug, parent_id, display_order)
SELECT name, slug, p.id, display_order FROM (VALUES
    ('Legends & Sagas', 'legends-sagas-collection', 1),
    ('Mythical Creatures', 'mythical-creatures', 2),
    ('Poets, Playwrights & Prophets', 'poets-playwrights-prophets', 3)
) AS sub(name, slug, display_order)
CROSS JOIN (SELECT id FROM collections WHERE slug = 'myths-legends') p
ON CONFLICT (slug) DO NOTHING;

-- Under "Uncomfortable Truths"
INSERT INTO collections (name, slug, parent_id, display_order)
SELECT name, slug, p.id, display_order FROM (VALUES
    ('Books That Make People Uncomfortable', 'uncomfortable-books', 1),
    ('Identity & Power', 'identity-power', 2),
    ('Science Before Science', 'science-before-science', 3)
) AS sub(name, slug, display_order)
CROSS JOIN (SELECT id FROM collections WHERE slug = 'uncomfortable-truths') p
ON CONFLICT (slug) DO NOTHING;

-- Under "Honora Originals"
INSERT INTO collections (name, slug, parent_id, display_order)
SELECT name, slug, p.id, display_order FROM (VALUES
    ('Honora Essentials', 'honora-essentials', 1),
    ('Editor''s Picks', 'editors-picks', 2),
    ('Deep Dive Series', 'deep-dive-series', 3),
    ('For Late Night Listening', 'late-night-listening', 4)
) AS sub(name, slug, display_order)
CROSS JOIN (SELECT id FROM collections WHERE slug = 'honora-originals') p
ON CONFLICT (slug) DO NOTHING;

-- =====================================================
-- VERIFICATION
-- =====================================================
-- Run this to verify:
-- SELECT c.name, c.slug, p.name as parent FROM collections c LEFT JOIN collections p ON c.parent_id = p.id ORDER BY c.display_order, c.name;
