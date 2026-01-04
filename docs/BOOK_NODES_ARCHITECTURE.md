# Book Nodes Architecture - Implementation Plan

> **Version:** 1.0  
> **Status:** PLANNING  
> **Date:** 2026-01-04

---

## Executive Summary

This document describes a complete restructuring of how book structure is stored and navigated in Honora. The goal is to move from fragmented tables (`chapters`, `stories`, `parts`) to a **unified tree-based structure** using `book_nodes`.

### The Three Layers (Must Remain Separate)

| Layer | Purpose | Current Table | Target |
|-------|---------|---------------|--------|
| **Structure** | Navigation (TOC) | `chapters`, `stories`, `parts` | → `book_nodes` |
| **UI Text** | Display & highlighting | `paragraphs` | → Keep as-is |
| **TTS Input** | Audio generation | `sections` | → Rename to `tts_chunks` |

---

## Part 1: Current State Analysis

### 1.1 Existing Tables

```
books (id, title, author, ...)
  └── parts (id, book_id, part_index, title)       ← fragmented structure
  └── stories (id, book_id, story_index, title)    ← fragmented structure  
  └── chapters (id, book_id, chapter_index, title, text, story_id?, part_id?, content_type?)
        └── sections (id, chapter_id, section_index, text_ref, start_ms, end_ms)  ← TTS CHUNKS
        └── paragraphs (id, chapter_id, paragraph_index, text, start_ms, end_ms)  ← UI TEXT
```

### 1.2 Current Problems

1. **"Chapter 0" hack** for introductions/prefaces
2. **Separate tables** for parts, stories, treatises - all doing similar things
3. **Flat chapter_index** cannot represent hierarchy (Part I → Chapter 1, 2, 3)
4. **Ambiguous naming**: "sections" sounds like book sections, but they're TTS chunks
5. **No TOC representation** - structure is implicit

### 1.3 What's Working (DO NOT BREAK)

- `paragraphs` → Perfect for UI highlighting
- `sections` → TTS chunks work correctly, just named badly
- Existing books in production with current schema

---

## Part 2: Target Architecture

### 2.1 New Table: `book_nodes`

```sql
CREATE TABLE book_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    parent_id UUID REFERENCES book_nodes(id) ON DELETE CASCADE,
    
    -- Node identity
    node_type TEXT NOT NULL CHECK (node_type IN (
        'front_matter', 'toc', 'preface', 'foreword', 'introduction',
        'dedication', 'acknowledgments', 'prologue',
        'part', 'book', 'section', 'chapter', 'subsection',
        'main_work', 'treatise', 'fragment', 'letter', 'discourse',
        'epilogue', 'appendix', 'glossary', 'bibliography', 'index',
        'back_matter', 'notes', 'afterword', 'postscript'
    )),
    
    -- Ordering (lexicographic sort)
    order_key TEXT NOT NULL,  -- e.g., "0001", "0002.0001", "0002.0002"
    
    -- Titles
    display_title TEXT NOT NULL,      -- What user sees: "Chapter 1: The Beginning"
    source_title TEXT,                -- Raw from TOC: "CHAPTER I. THE BEGINNING"
    
    -- Flags
    exclude_from_frontend BOOLEAN DEFAULT FALSE,  -- Hide from app navigation
    exclude_from_audio BOOLEAN DEFAULT FALSE,     -- Skip during TTS generation
    has_content BOOLEAN DEFAULT TRUE,             -- Does this node have text?
    
    -- Metadata
    confidence REAL DEFAULT 1.0,      -- AI detection confidence (0-1)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    UNIQUE(book_id, order_key)
);

-- Critical index for sorting
CREATE INDEX idx_book_nodes_order ON book_nodes(book_id, order_key);
CREATE INDEX idx_book_nodes_parent ON book_nodes(parent_id);
CREATE INDEX idx_book_nodes_type ON book_nodes(book_id, node_type);
```

### 2.2 Order Key Design

The `order_key` is a lexicographically sortable string that preserves hierarchy:

```
Book: "The Hermetic Writings"
├── 0001       → Preface (type: preface)
├── 0002       → Introduction (type: introduction)
├── 0003       → Part I: Historical (type: part)
│   ├── 0003.0001 → Chapter 1: Origins (type: chapter)
│   ├── 0003.0002 → Chapter 2: Development (type: chapter)
│   └── 0003.0003 → Chapter 3: Decline (type: chapter)
├── 0004       → Part II: Practical (type: part)
│   ├── 0004.0001 → The Stone of the Philosophers (type: treatise)
│   │   ├── 0004.0001.0001 → Section I (type: section)
│   │   └── 0004.0001.0002 → Section II (type: section)
│   └── 0004.0002 → The Virgin of the World (type: treatise)
├── 0005       → Appendix A: Glossary (type: appendix)
└── 0006       → Bibliography (type: bibliography)
```

**Rules:**
- 4 digits per level (supports 9999 items per level)
- Dot separator between levels
- Simple string comparison gives correct order
- No renumbering needed when inserting

### 2.3 Join Table: `book_node_paragraphs`

Links structural nodes to their paragraph content:

```sql
CREATE TABLE book_node_paragraphs (
    node_id UUID NOT NULL REFERENCES book_nodes(id) ON DELETE CASCADE,
    paragraph_id UUID NOT NULL REFERENCES paragraphs(id) ON DELETE CASCADE,
    position_in_node INT NOT NULL,  -- Order within this node
    
    PRIMARY KEY (node_id, paragraph_id)
);

CREATE INDEX idx_bnp_node ON book_node_paragraphs(node_id, position_in_node);
CREATE INDEX idx_bnp_paragraph ON book_node_paragraphs(paragraph_id);
```

### 2.4 Rename: `sections` → `tts_chunks` (View-based)

**Backward-compatible approach using a view:**

```sql
-- Create alias view (new preferred name)
CREATE VIEW tts_chunks AS 
SELECT 
    id,
    chapter_id,
    section_index AS chunk_index,
    text_ref AS text,
    start_ms,
    end_ms
FROM sections;

-- Keep old table name for existing code
-- GRANT permissions
GRANT SELECT ON tts_chunks TO anon, authenticated;
```

### 2.5 Join Table: `paragraph_tts_chunks`

Links paragraphs to their TTS chunks for playback synchronization:

```sql
CREATE TABLE paragraph_tts_chunks (
    paragraph_id UUID NOT NULL REFERENCES paragraphs(id) ON DELETE CASCADE,
    tts_chunk_id UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    position_in_paragraph INT NOT NULL,  -- Order within paragraph
    
    PRIMARY KEY (paragraph_id, tts_chunk_id)
);

CREATE INDEX idx_ptc_paragraph ON paragraph_tts_chunks(paragraph_id, position_in_paragraph);
CREATE INDEX idx_ptc_chunk ON paragraph_tts_chunks(tts_chunk_id);
```

---

## Part 3: Migration Strategy

### Phase 1: Additive (No Breaking Changes)

1. Create `book_nodes` table
2. Create `book_node_paragraphs` join table
3. Create `tts_chunks` VIEW over `sections`
4. Create `paragraph_tts_chunks` join table
5. Create compatibility views

**All existing code continues to work.**

### Phase 2: Data Migration

For existing books, generate `book_nodes` from current structure:

```sql
-- Migrate existing chapters to book_nodes
INSERT INTO book_nodes (book_id, parent_id, node_type, order_key, display_title, source_title)
SELECT 
    book_id,
    NULL as parent_id,
    CASE 
        WHEN content_type = 'prefatory' THEN 'preface'
        WHEN content_type = 'appendix' THEN 'appendix'
        WHEN content_type = 'book' THEN 'book'
        ELSE 'chapter'
    END as node_type,
    LPAD(chapter_index::text, 4, '0') as order_key,
    title as display_title,
    title as source_title
FROM chapters
WHERE book_id IN (SELECT id FROM books);

-- Link paragraphs to nodes via chapters
INSERT INTO book_node_paragraphs (node_id, paragraph_id, position_in_node)
SELECT 
    bn.id as node_id,
    p.id as paragraph_id,
    p.paragraph_index as position_in_node
FROM paragraphs p
JOIN chapters c ON c.id = p.chapter_id
JOIN book_nodes bn ON bn.book_id = c.book_id 
    AND bn.order_key = LPAD(c.chapter_index::text, 4, '0');
```

### Phase 3: Pipeline Updates

Update scraper and pipeline to output `book_nodes` directly.

### Phase 4: Deprecation (Future)

Once all code uses `book_nodes`, deprecate:
- `chapters.story_id`
- `chapters.part_id`
- `chapters.content_type`
- `stories` table
- `parts` table

---

## Part 4: Compatibility Views

### 4.1 `chapters_full` Replacement: `nodes_full`

```sql
CREATE VIEW nodes_full AS
SELECT 
    bn.id,
    bn.book_id,
    bn.parent_id,
    bn.node_type,
    bn.order_key,
    bn.display_title,
    bn.source_title,
    bn.exclude_from_frontend,
    bn.exclude_from_audio,
    -- Aggregated content
    (SELECT COUNT(*) FROM book_node_paragraphs bnp WHERE bnp.node_id = bn.id) as paragraph_count,
    -- Parent info
    parent.display_title as parent_title,
    parent.node_type as parent_type,
    -- Depth
    (SELECT COUNT(*) FROM (
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_id, 1 as depth FROM book_nodes WHERE id = bn.id
            UNION ALL
            SELECT bn2.id, bn2.parent_id, a.depth + 1
            FROM book_nodes bn2 JOIN ancestors a ON bn2.id = a.parent_id
        )
        SELECT * FROM ancestors
    ) sub) as depth
FROM book_nodes bn
LEFT JOIN book_nodes parent ON parent.id = bn.parent_id
ORDER BY bn.book_id, bn.order_key;
```

### 4.2 Legacy `chapters` Compatibility

```sql
CREATE VIEW chapters_legacy AS
SELECT 
    bn.id,
    bn.book_id,
    CAST(SPLIT_PART(bn.order_key, '.', 1) AS INT) as chapter_index,
    bn.display_title as title,
    '' as text,  -- Content now in paragraphs
    bn.node_type as content_type,
    bn.created_at
FROM book_nodes bn
WHERE bn.node_type IN ('chapter', 'preface', 'introduction', 'appendix', 'book', 'treatise')
  AND bn.parent_id IS NULL OR bn.parent_id IN (
      SELECT id FROM book_nodes WHERE node_type = 'part'
  );
```

---

## Part 5: Playback Order (Critical)

### Algorithm

```python
def get_playback_order(node_id: str) -> List[TTSChunk]:
    """
    Returns TTS chunks in correct playback order for a structural node.
    
    1. Get node's paragraphs (ordered by position_in_node)
    2. For each paragraph, get TTS chunks (ordered by position_in_paragraph)
    3. Flatten into final playback list
    """
    
    # Step 1: Get paragraphs for this node
    paragraphs = db.query("""
        SELECT p.id, p.text
        FROM paragraphs p
        JOIN book_node_paragraphs bnp ON bnp.paragraph_id = p.id
        WHERE bnp.node_id = :node_id
        ORDER BY bnp.position_in_node
    """, node_id=node_id)
    
    # Step 2: Get TTS chunks for each paragraph
    playback_order = []
    for para in paragraphs:
        chunks = db.query("""
            SELECT s.id, s.text_ref as text, s.start_ms, s.end_ms
            FROM sections s
            JOIN paragraph_tts_chunks ptc ON ptc.tts_chunk_id = s.id
            WHERE ptc.paragraph_id = :para_id
            ORDER BY ptc.position_in_paragraph
        """, para_id=para.id)
        
        playback_order.extend(chunks)
    
    return playback_order
```

---

## Part 6: Scraper Updates

### Current Output (bookScraper.js)

```json
{
  "title": "The Hermetic Writings",
  "chapters": [
    {"index": 0, "title": "Introduction", "content_type": "prefatory", ...},
    {"index": 1, "title": "Chapter 1", "content_type": "chapter", "parent_part": "Part I", ...}
  ],
  "parts": [
    {"part_index": 1, "title": "Part I: Historical"}
  ],
  "treatises": [
    {"treatise_index": 1, "title": "The Stone of the Philosophers"}
  ]
}
```

### New Output Format

```json
{
  "title": "The Hermetic Writings",
  "structure": {
    "nodes": [
      {
        "order_key": "0001",
        "node_type": "preface",
        "display_title": "Introduction",
        "source_title": "INTRODUCTION",
        "children": []
      },
      {
        "order_key": "0002",
        "node_type": "part",
        "display_title": "Part I: Historical",
        "source_title": "PART I. HISTORICAL",
        "children": [
          {
            "order_key": "0002.0001",
            "node_type": "chapter",
            "display_title": "Chapter 1: Origins",
            "source_title": "CHAPTER I. ORIGINS",
            "content": "Chapter text here..."
          }
        ]
      }
    ]
  }
}
```

---

## Part 7: Pipeline Updates

### V3 Pipeline Changes

```python
# pipeline_v3.py

def create_book_nodes(book_id: str, structure: dict) -> dict:
    """
    Creates book_nodes from scraper structure output.
    Returns mapping of order_key -> node_id.
    """
    node_id_map = {}
    
    def insert_node(node: dict, parent_id: str = None) -> str:
        result = supabase.table("book_nodes").insert({
            "book_id": book_id,
            "parent_id": parent_id,
            "node_type": node["node_type"],
            "order_key": node["order_key"],
            "display_title": node["display_title"],
            "source_title": node.get("source_title"),
            "has_content": "content" in node
        }).execute()
        
        node_id = result.data[0]["id"]
        node_id_map[node["order_key"]] = node_id
        
        # Recurse for children
        for child in node.get("children", []):
            insert_node(child, parent_id=node_id)
        
        return node_id
    
    for node in structure.get("nodes", []):
        insert_node(node)
    
    return node_id_map
```

---

## Part 8: iOS App Updates

### New SwiftUI Models

```swift
// BookNode.swift
struct BookNode: Codable, Identifiable {
    let id: UUID
    let book_id: UUID
    let parent_id: UUID?
    let node_type: String
    let order_key: String
    let display_title: String
    let source_title: String?
    let exclude_from_frontend: Bool
    let exclude_from_audio: Bool
    let has_content: Bool
    
    // Computed
    var isNavigable: Bool { !exclude_from_frontend && has_content }
    var depth: Int { order_key.components(separatedBy: ".").count }
}

// Navigation
func fetchBookStructure(bookId: UUID) async -> [BookNode] {
    return try await client
        .from("book_nodes")
        .select()
        .eq("book_id", value: bookId.uuidString)
        .eq("exclude_from_frontend", value: false)
        .order("order_key")
        .execute()
        .value
}
```

---

## Part 9: Success Criteria

| Criterion | Current State | Target State |
|-----------|--------------|--------------|
| "Chapter 0" for preface | ❌ Hack | ✅ `node_type: preface` |
| Nested structure | ❌ Flat | ✅ Tree via `parent_id` |
| Table naming clarity | ❌ "sections" = TTS | ✅ `tts_chunks` view |
| 3NF compliance | ✅ | ✅ Maintained |
| Existing data preserved | N/A | ✅ Migration script |
| Playback order deterministic | ~Implicit | ✅ Explicit join tables |
| Developer clarity | ❌ Confusing | ✅ Clear separation |

---

## Part 10: Implementation Order

### Week 1: Database Layer
1. [ ] Create `book_nodes` table in Supabase
2. [ ] Create `book_node_paragraphs` join table
3. [ ] Create `tts_chunks` view
4. [ ] Create `paragraph_tts_chunks` join table
5. [ ] Create compatibility views

### Week 2: Pipeline Updates
6. [ ] Update scraper to output new structure format
7. [ ] Update V3 pipeline to create `book_nodes`
8. [ ] Update paragraph/section linking logic
9. [ ] Test with sample books

### Week 3: Migration & App
10. [ ] Migrate existing books to `book_nodes`
11. [ ] Update iOS app models
12. [ ] Update iOS app navigation views
13. [ ] End-to-end testing

### Week 4: Cleanup
14. [ ] Documentation updates
15. [ ] Deprecation notices on old fields
16. [ ] Performance optimization

---

## Appendix A: Full SQL Migration Script

```sql
-- See: docs/supabase-book-nodes-migration.sql
```

---

## Questions Before Implementation

1. **Batch size for migration?** How many existing books need migration?
2. **View vs Alias preference?** Should `tts_chunks` be a view or should we rename the table?
3. **Depth limit?** Should we cap hierarchy depth (e.g., max 5 levels)?
4. **Content storage?** Keep `content` on `book_nodes` or always join to `paragraphs`?

---

*Document created by Antigravity based on analysis of HonoraTextAPI codebase.*
