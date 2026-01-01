# Gemini Text Rewriter for TTS Special Characters

**Date**: 2026-01-01 16:56  
**Agent**: Codex

## Intent
Add Gemini-powered text rewriting functionality to remove special characters (astrological symbols like ♄ ✶ △ ♂) that TTS cannot read, with UI controls for individual and bulk rewriting of paragraphs/sections.

## Method

### 1. Created `app/text_rewriter.py`
- **`rewrite_text_gemini(text: str)`**: Rewrites text using Gemini 2.0 Flash to replace special characters with written equivalents
  - Handles astrological symbols (♄ → Saturn, ♂ → Mars, etc.)
  - Greek letters (α → alpha, Ω → omega, etc.)
  - Mathematical symbols (△ → triangle, ○ → circle, etc.)
  - Uses comprehensive prompt with examples
  - Returns rewritten text with symbols replaced by words

- **`optimize_paragraphs_gemini(paragraphs: list, chapter_title: str)`**: Analyzes and optimizes paragraphs for TTS
  - Merges short paragraphs (< 50 chars) if semantically related
  - Splits long paragraphs (> 800 chars) at natural boundaries
  - Maintains complete thought units
  - Returns optimized paragraphs + change descriptions + suggestions

### 2. Added API Endpoints to `app/main.py`
- **`POST /v2/job/{job_id}/rewrite-text`**: Rewrite single text snippet
  - Payload: `{"text": "Text with ♄ ✶", "type": "paragraph|section"}`
  - Returns: `{"original": "...", "rewritten": "...", "changes_detected": true/false}`

- **`POST /v2/job/{job_id}/optimize-paragraphs`**: Optimize paragraph structure
  - Payload: `{"paragraphs": [...], "chapter_title": "..."}`
  - Returns: `{"optimized_paragraphs": [...], "changes": [...], "suggestions": [...]}`

- **`PUT /v2/job/{job_id}/chapter/{chapter_index}/sections`**: Bulk update sections
  - Payload: `{"sections": [...], "operation": "replace|append|insert", "insert_at": 2}`
  - Supports section management operations

- **`DELETE /v2/job/{job_id}/chapter/{chapter_index}/section/{section_index}`**: Delete specific section
  - Cannot delete section 0 (chapter title)
  - Maintains proper section ordering after deletion

### 3. Updated `app/static/dashboard_v2.html`

**Added Buttons**:
- **Sections column**:
  - ✨ Rewrite All (Remove Symbols) - bulk rewrite all sections
  - + Add Section - add new section at end
  - ✨ Rewrite - per-section rewrite button
  - 🗑 Delete - per-section delete button (not on title)

- **Paragraphs column**:
  - ✨ Rewrite All (Remove Symbols) - bulk rewrite all paragraphs
  - 🎯 Optimize (Merge/Split) - intelligent paragraph optimization
  - + Add Paragraph - add new paragraph at end
  - ✨ Rewrite - per-paragraph rewrite button
  - + Insert Before - insert new paragraph before current
  - 🗑 Delete - per-paragraph delete button (not on title)

**JavaScript Functions**:
- `rewriteParagraph(index)`: Rewrites single paragraph, shows before/after in alert
- `rewriteSection(index)`: Rewrites single section, updates character count display
- `deleteSection(index)`: Deletes section with confirmation, refreshes UI
- `rewrite-all-paragraphs-btn` handler: Loops through all paragraphs, rewrites each
- `rewrite-all-sections-btn` handler: Loops through all sections, rewrites each
- `optimize-paragraphs-btn` handler: Calls Gemini optimization, shows changes/suggestions
- `add-section-btn` handler: Adds new section to chapter
- `add-paragraph-btn` handler: Adds new paragraph to chapter

**UI Improvements**:
- Rewrite buttons show ⏳ loading state during processing
- Alert dialogs show before/after comparison when rewriting
- Character count updates dynamically after rewriting sections
- Proper numbering maintained after add/delete operations
- Title (index 0) cannot be deleted for both sections and paragraphs

## Reason
User requested buttons to rewrite text using Gemini to remove TTS-unfriendly special characters like "♄ ✶ or △ ♂ If ♄", with support for:
1. Individual paragraph/section rewriting
2. Bulk rewriting of all paragraphs/sections
3. Paragraph optimization (merge/split)
4. Section CRUD operations (add/delete)
5. Proper ordering maintenance

## Files Touched
- **Created**: `app/text_rewriter.py` (new module)
- **Modified**: `app/main.py` (added 4 new endpoints)
- **Modified**: `app/static/dashboard_v2.html` (added buttons and JavaScript handlers)

## Tests
Manual testing recommended:
1. Upload PDF with special characters (e.g., astrological texts)
2. Process chapters
3. Edit chapter
4. Test individual rewrite on paragraph with "♄ ✶ △ ♂"
5. Test bulk rewrite on all paragraphs
6. Test paragraph optimization (merge short, split long)
7. Test section add/delete
8. Verify proper ordering after operations
9. Test special cases: empty text, title protection, etc.

## Example Usage
```javascript
// Rewrite single paragraph
POST /v2/job/{job_id}/rewrite-text
{
  "text": "If ♄ is in conjunction with ♂",
  "type": "paragraph"
}
// Returns: "If Saturn is in conjunction with Mars"

// Optimize paragraphs
POST /v2/job/{job_id}/optimize-paragraphs
{
  "paragraphs": [
    "Very short.",
    "This is a medium length paragraph with good content.",
    "This is an extremely long paragraph that goes on and on and on... (> 800 chars)"
  ],
  "chapter_title": "Chapter 3: The Hermetic Principles"
}
// Returns merged/split paragraphs with optimal lengths
```

## Dependencies
- Requires `GEMINI_API_KEY` environment variable
- Uses Gemini 2.0 Flash (gemini-2.0-flash-exp model)
- Integrates with existing Pipeline V2 job state management

## Notes
- Title (index 0) is protected from deletion in both sections and paragraphs
- Rewriting is non-destructive until user saves changes
- Character count validation runs after section rewrites (250 char TTS limit)
- Optimization preserves all original text content, just reorganizes boundaries
- All operations maintain proper sequential ordering (0, 1, 2, 3...)
