"""
Pipeline V2: Chapter-by-chapter processing with preview and approval.

This module implements the new pipeline architecture where:
1. PDF is converted to Markdown via Marker API
2. Chapters are detected from Markdown headers
3. Each chapter is processed individually
4. User can preview, edit, and approve each chapter
5. Final commit uploads all approved data to Supabase

This replaces the previous "all-at-once" approach with a more granular,
error-resistant flow.
"""
import os
import json
import uuid
from typing import Optional

# Import existing modules
from app.marker import extract_pdf_to_markdown, parse_chapters_from_markdown, extract_chapter_text
from app.metadata import extract_book_metadata, generate_synopsis_and_category
from app.cover_art import generate_cover_image, update_book_cover_url
from app.chapters import (
    split_into_paragraphs_gpt,
    split_into_paragraphs_perfect,
    split_into_sections_tts,
    split_into_sections_perfect,
    ensure_paragraph_0_is_title,
    write_sections_to_supabase,
    write_paragraphs_to_supabase,
    create_book_in_supabase,
    write_chapters_to_supabase,
    clean_section_text
)
from app.cleaner import clean_page_text

# Temporary storage directory
TEMP_DIR = "/tmp/honora_v2"
os.makedirs(TEMP_DIR, exist_ok=True)


# ============================================
# JOB STATE MANAGEMENT (file-based for now)
# ============================================

def create_job(file_path: str) -> str:
    """Create a new processing job and return job_id.
    
    Supports both PDF and JSON files:
    - PDF: Will use Marker API for extraction
    - JSON: Direct parsing from HonoraWebScraper output (faster, more reliable)
    
    The source file is COPIED to the job directory to ensure persistence.
    """
    import shutil
    
    job_id = str(uuid.uuid4())
    job_dir = f"{TEMP_DIR}/{job_id}"
    os.makedirs(job_dir, exist_ok=True)
    
    # Detect file type
    is_json = file_path.endswith('.json')
    file_ext = '.json' if is_json else '.pdf'
    
    # Copy file to job directory for persistence
    job_file_path = f"{job_dir}/source{file_ext}"
    shutil.copy2(file_path, job_file_path)
    print(f"[PIPELINE_V2] Copied source file to: {job_file_path}")
    
    job_state = {
        "job_id": job_id,
        "status": "created",
        "phase": "upload",
        "file_path": job_file_path,  # Use the copied file
        "file_type": "json" if is_json else "pdf",
        "pdf_path": job_file_path if not is_json else None,
        "json_path": job_file_path if is_json else None,
        "json_data": None,  # Will be loaded when needed
        "markdown": None,
        "metadata": None,
        "cover_urls": None,
        "chapters": [],
        "error": None
    }
    
    # For JSON files, verify it's readable and log chapter count
    if is_json:
        try:
            with open(job_file_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)
            chapter_count = json_data.get('chapterCount', len(json_data.get('chapters', [])))
            job_state["phase"] = "json_loaded"
            print(f"[PIPELINE_V2] Created job from JSON: {job_id} ({chapter_count} chapters)")
        except Exception as e:
            print(f"[PIPELINE_V2] Warning: Could not pre-load JSON: {e}")
            print(f"[PIPELINE_V2] Created job from JSON: {job_id}")
    else:
        print(f"[PIPELINE_V2] Created job from PDF: {job_id}")
    
    save_job_state(job_id, job_state)
    return job_id


def get_job_state(job_id: str) -> dict:
    """Load job state from disk."""
    state_path = f"{TEMP_DIR}/{job_id}/state.json"
    if not os.path.exists(state_path):
        return None
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_job_state(job_id: str, state: dict):
    """Save job state to disk."""
    job_dir = f"{TEMP_DIR}/{job_id}"
    os.makedirs(job_dir, exist_ok=True)
    state_path = f"{job_dir}/state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def update_job_phase(job_id: str, phase: str, **kwargs):
    """Update job phase and any additional fields."""
    state = get_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    state["phase"] = phase
    state.update(kwargs)
    save_job_state(job_id, state)
    print(f"[PIPELINE_V2] Job {job_id[:8]}... → Phase: {phase}")


# ============================================
# PHASE 1: PDF EXTRACTION (Marker API) or JSON (skip)
# ============================================

def load_json_data(state: dict) -> dict:
    """Load JSON data from file path. More reliable than storing in state."""
    json_path = state.get("json_path")
    if not json_path or not os.path.exists(json_path):
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[PIPELINE_V2] Error loading JSON: {e}")
        return None


async def phase_extract_pdf(job_id: str) -> dict:
    """
    Extract content from uploaded file.
    
    For JSON files: Skip - data already loaded during create_job
    For PDF files: Use Marker API to convert to Markdown
    
    Returns:
        {"success": True, "pages": N, "markdown_preview": "..."}
    """
    state = get_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    try:
        # For JSON files, skip extraction - load data from file
        if state.get("file_type") == "json":
            json_data = load_json_data(state)
            if json_data:
                print(f"[PIPELINE_V2] Skipping extraction for JSON file (loading from {state.get('json_path')})")
                update_job_phase(
                    job_id, 
                    "extracted",
                    status="JSON data loaded (no extraction needed)",
                    pages=0,
                    json_data=json_data  # Store it now for later phases
                )
                return {
                    "success": True,
                    "file_type": "json",
                    "pages": 0,
                    "chapter_count": json_data.get("chapterCount", len(json_data.get("chapters", []))),
                    "message": "JSON file loaded directly - no Marker API needed"
                }
            else:
                raise ValueError(f"Failed to load JSON data from {state.get('json_path')}")
        
        # For PDF files, use Marker API
        pdf_path = state.get("pdf_path")
        if not pdf_path:
            raise ValueError("No PDF path found for extraction")
        
        update_job_phase(job_id, "extracting", status="Extracting PDF with Marker API...")
        
        # Call Marker API
        result = extract_pdf_to_markdown(pdf_path)
        
        markdown = result.get("markdown", "")
        pages = result.get("pages", 0)
        
        # Save markdown to job
        update_job_phase(
            job_id, 
            "extracted",
            status="PDF extracted successfully",
            markdown=markdown,
            pages=pages
        )
        
        return {
            "success": True,
            "file_type": "pdf",
            "pages": pages,
            "markdown_preview": markdown[:500] + "..." if len(markdown) > 500 else markdown,
            "markdown_length": len(markdown)
        }
        
    except Exception as e:
        update_job_phase(job_id, "error", status="Extraction failed", error=str(e))
        raise


# ============================================
# PHASE 2: METADATA & COVER ART
# ============================================

async def phase_metadata(job_id: str) -> dict:
    """
    Extract metadata and generate cover art.
    
    For JSON files: Use metadata directly from json_data
    For PDF files: Extract with GPT from markdown
    
    Returns:
        {"metadata": {...}, "cover_urls": {...}}
    """
    state = get_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    try:
        update_job_phase(job_id, "metadata", status="Extracting metadata...")
        
        metadata = None
        
        # For JSON files, use metadata directly + generate synopsis/category
        if state.get("file_type") == "json" and state.get("json_data"):
            json_data = state["json_data"]
            print(f"[PIPELINE_V2] Using metadata from JSON: {json_data.get('title')}")
            
            # Generate synopsis and category from chapter content
            print("[PIPELINE_V2] Generating synopsis and category from chapter content...")
            chapter_sample = "\n\n".join([
                ch.get("content", "")[:2000] 
                for ch in json_data.get("chapters", [])[:3]
            ])
            source_url = json_data.get("sourceUrl")
            
            generated = generate_synopsis_and_category(chapter_sample, source_url)
            print(f"[PIPELINE_V2] Generated: category='{generated.get('category')}', synopsis length={len(generated.get('synopsis') or '')}")
            
            metadata = {
                "title": json_data.get("title", "Unknown"),
                "author": json_data.get("author", "Unknown"),
                "publishing_year": json_data.get("year", None),
                "publisher": json_data.get("publisher", None),
                "language": "English",
                "original_language": "English",
                "category": generated.get("category", "Spirituality & Religion"),
                "subcategory": generated.get("subcategory"),
                "synopsis": generated.get("synopsis"),
                "book_of_the_day_quote": generated.get("book_of_the_day_quote"),
                "translated": False,
                "explicit": False
            }
        
        # For PDF files, use GPT extraction
        elif state.get("markdown"):
            markdown = state["markdown"]
            first_portion = markdown[:int(len(markdown) * 0.15)]
            metadata = extract_book_metadata(first_portion)
        else:
            raise ValueError("No data available for metadata extraction")
        
        update_job_phase(job_id, "cover_art", status="Generating cover art...")
        
        # Generate cover art and upload to Supabase
        cover_urls = None
        try:
            cover_urls = generate_cover_image(metadata, upload=True)
            # Copy cover URLs into metadata so editor can find them
            if cover_urls.get("cover_art_url"):
                metadata["cover_art_url"] = cover_urls.get("cover_art_url")
            if cover_urls.get("cover_art_url_16x9"):
                metadata["cover_art_url_16x9"] = cover_urls.get("cover_art_url_16x9")
        except Exception as cover_err:
            print(f"[PIPELINE_V2] ⚠️ Cover art generation failed: {cover_err}")
            print("[PIPELINE_V2] Continuing without cover art (you can add it later)")
            cover_urls = {
                "cover_art_url": None,
                "cover_art_url_16x9": None,
                "error": str(cover_err)
            }
        
        update_job_phase(
            job_id,
            "metadata_complete",
            status="Metadata ready" + (" (cover art skipped)" if cover_urls.get("error") else " with cover art"),
            metadata=metadata,
            cover_urls=cover_urls
        )
        
        return {
            "metadata": metadata,
            "cover_urls": cover_urls
        }
        
    except Exception as e:
        update_job_phase(job_id, "error", status="Metadata extraction failed", error=str(e))
        raise


# ============================================
# PHASE 3: CHAPTER DETECTION
# ============================================

async def phase_detect_chapters(job_id: str) -> dict:
    """
    Detect chapters from the uploaded file.
    
    For JSON files: Direct extraction from json_data.chapters (100% reliable)
    For PDF files: Parse from Markdown headers (uses Marker API output)
    
    Returns:
        {"chapters": [{"index": 1, "title": "...", ...}, ...]}
    """
    state = get_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    try:
        update_job_phase(job_id, "detecting_chapters", status="Detecting chapters...")
        
        chapters = []
        
        # Check if this is a JSON file (direct extraction)
        if state.get("file_type") == "json" and state.get("json_data"):
            json_data = state["json_data"]
            print(f"[PIPELINE_V2] Using JSON chapters: {json_data.get('chapterCount', 0)} chapters")
            
            # Extract chapters directly from JSON
            for ch in json_data.get("chapters", []):
                content = ch.get("content", "")
                chapters.append({
                    "index": ch.get("index", len(chapters) + 1),
                    "title": ch.get("title", f"Chapter {len(chapters) + 1}"),
                    "content": content,  # Store full content for later processing
                    "status": "pending",
                    "char_count": len(content),
                    "preview": content[:200] + "..." if len(content) > 200 else content,
                    "sections": None,
                    "paragraphs": None
                })
        
        # Fallback to PDF/Markdown parsing
        elif state.get("markdown"):
            markdown = state["markdown"]
            print(f"[PIPELINE_V2] Parsing chapters from Markdown...")
            
            # Parse chapters from markdown headers
            raw_chapters = parse_chapters_from_markdown(markdown)
            
            # Add status and preview to each chapter
            for ch in raw_chapters:
                text = extract_chapter_text(markdown, ch)
                ch["content"] = text
                ch["status"] = "pending"
                ch["char_count"] = len(text)
                ch["preview"] = text[:200] + "..." if len(text) > 200 else text
                ch["sections"] = None
                ch["paragraphs"] = None
                chapters.append(ch)
        else:
            raise ValueError("No data available: neither json_data nor markdown found")
        
        update_job_phase(
            job_id,
            "chapters_detected",
            status=f"Found {len(chapters)} chapters",
            chapters=chapters
        )
        
        print(f"[PIPELINE_V2] Detected {len(chapters)} chapters:")
        for ch in chapters[:5]:
            print(f"[PIPELINE_V2]   {ch['index']}. {ch['title']} ({ch['char_count']} chars)")
        if len(chapters) > 5:
            print(f"[PIPELINE_V2]   ... and {len(chapters) - 5} more")
        
        return {
            "chapters": chapters,
            "total": len(chapters)
        }
        
    except Exception as e:
        update_job_phase(job_id, "error", status="Chapter detection failed", error=str(e))
        raise


# ============================================
# PHASE 4: PROCESS SINGLE CHAPTER
# ============================================

async def phase_process_chapter(job_id: str, chapter_index: int) -> dict:
    """
    Process one chapter:
    1. Extract text from markdown
    2. Clean with GPT (optional, Marker output is usually clean)
    3. Create sections (semantic paragraphs)
    4. Create paragraphs (same as sections for now)
    
    Returns:
        {"sections": [...], "paragraphs": [...]}
    """
    state = get_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    chapters = state.get("chapters", [])
    chapter = next((c for c in chapters if c["index"] == chapter_index), None)
    
    if not chapter:
        raise ValueError(f"Chapter {chapter_index} not found")
    
    try:
        # Update chapter status
        chapter["status"] = "processing"
        save_job_state(job_id, state)
        
        print(f"[PIPELINE_V2] Processing chapter {chapter_index}: {chapter['title']}")
        
        # Get chapter text
        # For JSON files, content is already stored in chapter['content']
        # For PDF files, extract from markdown
        if chapter.get("content"):
            chapter_text = chapter["content"]
            print(f"[PIPELINE_V2] Using stored content ({len(chapter_text)} chars)")
        elif state.get("markdown"):
            markdown = state["markdown"]
            chapter_text = extract_chapter_text(markdown, chapter)
            print(f"[PIPELINE_V2] Extracted from markdown ({len(chapter_text)} chars)")
        else:
            raise ValueError("No content available for this chapter")
        
        # Clean the text (remove markdown artifacts)
        cleaned_text = clean_markdown_text(chapter_text)
        
        # Get chapter title for index 0
        chapter_title = chapter.get("title", f"Chapter {chapter_index}")
        
        # =====================================================
        # SECTIONS: TTS-optimized, max ~250 chars
        # Section 0 = chapter title, Section 1+ = content
        # Uses spaCy for sentence-aware splitting (never mid-sentence)
        # =====================================================
        print(f"[PIPELINE_V2] Creating TTS sections with spaCy (max 250 chars)...")
        sections = split_into_sections_perfect(cleaned_text, chapter_title, max_chars=250)
        
        # Apply final TTS cleanup to each section (except title at index 0)
        sections = [sections[0]] + [clean_section_text(s) for s in sections[1:] if s.strip()]
        
        # =====================================================
        # PARAGRAPHS: Perfect splitting with spaCy + Gemini
        # Paragraph 0 = chapter title, Paragraph 1+ = content
        # Guarantees: no mid-sentence splits, no single-char paragraphs
        # =====================================================
        print(f"[PIPELINE_V2] Creating paragraphs with spaCy + Gemini...")
        paragraphs = split_into_paragraphs_perfect(cleaned_text, chapter_title)
        
        # Note: ensure_paragraph_0_is_title is now done inside split_into_paragraphs_perfect
        # paragraphs = ensure_paragraph_0_is_title(paragraphs, chapter_title)
        
        # Update chapter with results
        chapter["status"] = "ready"
        chapter["sections"] = sections
        chapter["paragraphs"] = paragraphs
        chapter["section_count"] = len(sections)
        chapter["paragraph_count"] = len(paragraphs)
        
        save_job_state(job_id, state)
        
        print(f"[PIPELINE_V2] ✅ Chapter {chapter_index} complete: {len(sections)} sections, {len(paragraphs)} paragraphs")
        
        return {
            "chapter_index": chapter_index,
            "sections": sections,
            "paragraphs": paragraphs,
            "section_count": len(sections),
            "paragraph_count": len(paragraphs)
        }
        
    except Exception as e:
        chapter["status"] = "error"
        chapter["error"] = str(e)
        save_job_state(job_id, state)
        raise


def clean_markdown_text(text: str) -> str:
    """
    Clean markdown artifacts and sacred-texts.com formatting from text.
    - Removes headers like # and ##
    - Removes page markers like "p. 6", "p. 7" from sacred-texts.com
    - Joins sentences that were broken by page markers
    - Normalizes paragraph breaks
    """
    import re
    
    # Remove markdown headers but keep the text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    
    # Remove markdown bold/italic markers
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    
    # Remove markdown links, keep text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    
    # ===========================================
    # SACRED-TEXTS.COM SPECIFIC CLEANING
    # ===========================================
    
    # Remove page markers like "p. 6", "p. 123", etc.
    # These appear on their own lines from sacred-texts.com
    text = re.sub(r'^\s*p\.\s*\d+\s*$', '', text, flags=re.MULTILINE | re.IGNORECASE)
    
    # Also remove inline page markers (sometimes they appear inline)
    text = re.sub(r'\s*p\.\s*\d+\s*', ' ', text)
    
    # ===========================================
    # JOIN BROKEN SENTENCES
    # ===========================================
    
    # Pattern: line ends without sentence-ending punctuation, followed by newline(s),
    # then next line starts with lowercase letter or continues the sentence
    # This joins sentences that were broken by page markers
    
    # First, normalize to single newlines temporarily
    lines = text.split('\n')
    cleaned_lines = []
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            # Keep empty lines as paragraph separators
            if cleaned_lines and cleaned_lines[-1] != '':
                cleaned_lines.append('')
            continue
        
        # Check if we should join with previous line
        if cleaned_lines and cleaned_lines[-1]:
            prev_line = cleaned_lines[-1]
            # Join if:
            # 1. Previous line doesn't end with sentence-ending punctuation
            # 2. Current line starts with lowercase OR continues a quote/sentence
            ends_sentence = prev_line.rstrip()[-1:] in '.!?:;"'
            starts_new = line[0:1].isupper() and not prev_line.rstrip().endswith(',')
            starts_lowercase = line[0:1].islower()
            
            # If previous line doesn't end a sentence and current starts lowercase, join
            if not ends_sentence or starts_lowercase:
                # Join with previous line
                cleaned_lines[-1] = prev_line.rstrip() + ' ' + line.lstrip()
                continue
        
        cleaned_lines.append(line)
    
    # Rebuild text
    text = '\n'.join(cleaned_lines)
    
    # ===========================================
    # NORMALIZE WHITESPACE
    # ===========================================
    
    # Collapse multiple blank lines to just one (paragraph break)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Collapse multiple spaces to single space
    text = re.sub(r' {2,}', ' ', text)
    
    text = text.strip()
    
    return text


# ============================================
# PHASE 5: COMMIT TO SUPABASE
# ============================================

async def phase_commit_to_supabase(job_id: str) -> dict:
    """
    Upload all approved preview data to production Supabase tables.
    
    Creates:
    - Book record
    - Chapter records
    - Section records
    - Paragraph records
    - Uploads cover art
    
    Returns:
        {"book_id": "...", "chapters": N, "sections": N, "paragraphs": N}
    """
    state = get_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    metadata = state.get("metadata")
    chapters = state.get("chapters", [])
    cover_urls_preview = state.get("cover_urls", {})
    
    # Check all chapters are approved
    pending = [c for c in chapters if c.get("status") not in ["ready", "approved"]]
    if pending:
        raise ValueError(f"{len(pending)} chapters are not ready/approved")
    
    try:
        update_job_phase(job_id, "committing", status="Creating book in Supabase...")
        
        # Step 1: Create book record
        book_id = create_book_in_supabase(metadata)
        print(f"[PIPELINE_V2] Created book: {book_id}")
        
        # Step 2: Generate and upload cover art
        update_job_phase(job_id, "committing", status="Uploading cover art...")
        try:
            metadata_with_id = dict(metadata)
            metadata_with_id["book_id"] = book_id
            cover_urls = generate_cover_image(metadata_with_id, upload=True)
            update_book_cover_url(book_id, cover_urls)
        except Exception as cover_error:
            import traceback
            print(f"[PIPELINE_V2] ⚠️ Cover art upload failed: {cover_error}")
            traceback.print_exc()
            cover_urls = cover_urls_preview
        
        # Step 3: Create chapters with sections and paragraphs
        total_sections = 0
        total_paragraphs = 0
        
        for ch in chapters:
            update_job_phase(
                job_id, 
                "committing", 
                status=f"Uploading chapter {ch['index']}/{len(chapters)}..."
            )
            
            # Create chapter record
            # For JSON uploads, use stored content; for PDF, extract from markdown
            if state.get("markdown"):
                chapter_text = extract_chapter_text(state["markdown"], ch)
            else:
                # JSON uploads have content stored directly in chapter
                chapter_text = ch.get("content", "") or ch.get("text", "") or ""
            
            chapter_data = [{
                "chapter_index": ch["index"],
                "title": ch["title"],
                "text": chapter_text
            }]
            
            db_chapters = write_chapters_to_supabase(book_id, chapter_data)
            
            if db_chapters:
                chapter_id = db_chapters[0]["id"]
                
                # Write sections
                sections = ch.get("sections", [])
                if sections:
                    write_sections_to_supabase(chapter_id, sections)
                    total_sections += len(sections)
                
                # Write paragraphs
                paragraphs = ch.get("paragraphs", [])
                if paragraphs:
                    write_paragraphs_to_supabase(chapter_id, paragraphs)
                    total_paragraphs += len(paragraphs)
        
        update_job_phase(
            job_id,
            "complete",
            status="Upload complete!",
            book_id=book_id
        )
        
        print(f"[PIPELINE_V2] ✅ Commit complete: {len(chapters)} chapters, {total_sections} sections, {total_paragraphs} paragraphs")
        
        return {
            "book_id": book_id,
            "chapters": len(chapters),
            "sections": total_sections,
            "paragraphs": total_paragraphs,
            "cover_urls": cover_urls
        }
        
    except Exception as e:
        update_job_phase(job_id, "error", status="Commit failed", error=str(e))
        raise


# ============================================
# HELPER: PROCESS ALL CHAPTERS
# ============================================

async def process_all_chapters(job_id: str) -> dict:
    """
    Convenience function to process all chapters in sequence.
    """
    state = get_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    chapters = state.get("chapters", [])
    results = []
    
    for ch in chapters:
        if ch.get("status") in ["ready", "approved"]:
            continue  # Skip already processed
        
        try:
            result = await phase_process_chapter(job_id, ch["index"])
            results.append(result)
        except Exception as e:
            print(f"[PIPELINE_V2] ⚠️ Chapter {ch['index']} failed: {e}")
            results.append({"chapter_index": ch["index"], "error": str(e)})
    
    return {
        "processed": len([r for r in results if "error" not in r]),
        "errors": len([r for r in results if "error" in r]),
        "results": results
    }
