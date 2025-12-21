-- =====================================================
-- HONORA 3NF MIGRATION - PHASE 1
-- Run this in Supabase SQL Editor
-- =====================================================

-- 1. CREATE LOOKUP TABLES
-- =====================================================

-- Authors table
CREATE TABLE IF NOT EXISTS authors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Categories table (17 fixed genres)
CREATE TABLE IF NOT EXISTS categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE
);

-- Languages table
CREATE TABLE IF NOT EXISTS languages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    code TEXT UNIQUE  -- "en", "da", etc.
);

-- Publishers table
CREATE TABLE IF NOT EXISTS publishers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. CREATE JUNCTION TABLE
-- =====================================================

CREATE TABLE IF NOT EXISTS book_authors (
    book_id UUID REFERENCES books(id) ON DELETE CASCADE,
    author_id UUID REFERENCES authors(id) ON DELETE RESTRICT,
    author_order INT DEFAULT 0,
    PRIMARY KEY (book_id, author_id)
);

-- 3. SEED CATEGORIES (17 genres)
-- =====================================================

INSERT INTO categories (name, slug) VALUES
    ('Fiction', 'fiction'),
    ('Non-Fiction', 'non-fiction'),
    ('Mystery', 'mystery'),
    ('Romance', 'romance'),
    ('Fantasy', 'fantasy'),
    ('Science Fiction', 'science-fiction'),
    ('Biography', 'biography'),
    ('Self-Help', 'self-help'),
    ('History', 'history'),
    ('Philosophy', 'philosophy'),
    ('Business', 'business'),
    ('Classic Literature', 'classic-literature'),
    ('Children', 'children'),
    ('Young Adult', 'young-adult'),
    ('Poetry', 'poetry'),
    ('Religion', 'religion'),
    ('Science', 'science')
ON CONFLICT (name) DO NOTHING;

-- 4. ADD FOREIGN KEY COLUMNS TO BOOKS
-- =====================================================

ALTER TABLE books 
    ADD COLUMN IF NOT EXISTS category_id UUID REFERENCES categories(id),
    ADD COLUMN IF NOT EXISTS language_id UUID REFERENCES languages(id),
    ADD COLUMN IF NOT EXISTS original_language_id UUID REFERENCES languages(id),
    ADD COLUMN IF NOT EXISTS publisher_id UUID REFERENCES publishers(id);

-- 5. MIGRATE EXISTING DATA
-- =====================================================

-- 5a. Migrate languages
INSERT INTO languages (name)
SELECT DISTINCT language FROM books 
WHERE language IS NOT NULL AND language != ''
ON CONFLICT (name) DO NOTHING;

INSERT INTO languages (name)
SELECT DISTINCT original_language FROM books 
WHERE original_language IS NOT NULL AND original_language != ''
ON CONFLICT (name) DO NOTHING;

-- 5b. Migrate publishers
INSERT INTO publishers (name)
SELECT DISTINCT publisher FROM books 
WHERE publisher IS NOT NULL AND publisher != ''
ON CONFLICT (name) DO NOTHING;

-- 5c. Migrate authors (handling comma-separated names)
INSERT INTO authors (name)
SELECT DISTINCT TRIM(unnest(string_to_array(author, ','))) as name
FROM books 
WHERE author IS NOT NULL AND author != '' AND author != 'Unknown'
ON CONFLICT (name) DO NOTHING;

-- 5d. Link books to categories
UPDATE books b
SET category_id = c.id
FROM categories c
WHERE b.category = c.name AND b.category_id IS NULL;

-- 5e. Link books to languages
UPDATE books b
SET language_id = l.id
FROM languages l
WHERE b.language = l.name AND b.language_id IS NULL;

UPDATE books b
SET original_language_id = l.id
FROM languages l
WHERE b.original_language = l.name AND b.original_language_id IS NULL;

-- 5f. Link books to publishers
UPDATE books b
SET publisher_id = p.id
FROM publishers p
WHERE b.publisher = p.name AND b.publisher_id IS NULL;

-- 5g. Create book_authors relationships
INSERT INTO book_authors (book_id, author_id, author_order)
SELECT 
    b.id as book_id,
    a.id as author_id,
    row_number() OVER (PARTITION BY b.id ORDER BY a.name) - 1 as author_order
FROM books b
CROSS JOIN LATERAL unnest(string_to_array(b.author, ',')) WITH ORDINALITY AS x(author_name, ord)
JOIN authors a ON TRIM(x.author_name) = a.name
WHERE b.author IS NOT NULL AND b.author != '' AND b.author != 'Unknown'
ON CONFLICT (book_id, author_id) DO NOTHING;

-- 6. CREATE DENORMALIZED VIEW FOR APP
-- =====================================================

CREATE OR REPLACE VIEW books_full AS
SELECT 
    b.id,
    b.title,
    b.synopsis,
    b.book_of_the_day_quote,
    b.publishing_year,
    b.cover_art_url,
    b.play_time_seconds,
    b.created_at,
    -- Joined data (new 3NF style)
    c.name AS category,
    c.slug AS category_slug,
    l.name AS language,
    l.code AS language_code,
    ol.name AS original_language,
    p.name AS publisher,
    -- Authors as comma-separated string (backwards compatible)
    COALESCE(
        (SELECT string_agg(a.name, ', ' ORDER BY ba.author_order)
         FROM book_authors ba
         JOIN authors a ON a.id = ba.author_id
         WHERE ba.book_id = b.id),
        b.author  -- Fallback to old column
    ) AS author,
    -- Authors as array (for app use)
    (SELECT array_agg(a.name ORDER BY ba.author_order)
     FROM book_authors ba
     JOIN authors a ON a.id = ba.author_id
     WHERE ba.book_id = b.id) AS authors_array
FROM books b
LEFT JOIN categories c ON c.id = b.category_id
LEFT JOIN languages l ON l.id = b.language_id
LEFT JOIN languages ol ON ol.id = b.original_language_id
LEFT JOIN publishers p ON p.id = b.publisher_id;

-- 7. GRANT PERMISSIONS (for anon/authenticated access)
-- =====================================================

GRANT SELECT ON authors TO anon, authenticated;
GRANT SELECT ON categories TO anon, authenticated;
GRANT SELECT ON languages TO anon, authenticated;
GRANT SELECT ON publishers TO anon, authenticated;
GRANT SELECT ON book_authors TO anon, authenticated;
GRANT SELECT ON books_full TO anon, authenticated;

-- =====================================================
-- VERIFICATION QUERIES (run after migration)
-- =====================================================

-- Check lookup tables are populated
-- SELECT 'authors' as table_name, COUNT(*) FROM authors
-- UNION ALL SELECT 'categories', COUNT(*) FROM categories
-- UNION ALL SELECT 'languages', COUNT(*) FROM languages
-- UNION ALL SELECT 'publishers', COUNT(*) FROM publishers;

-- Check books_full view works
-- SELECT * FROM books_full LIMIT 5;
