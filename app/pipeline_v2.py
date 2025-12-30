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
from app.metadata import extract_book_metadata
from app.cover_art import generate_cover_image, update_book_cover_url
from app.chapters import (
    split_into_paragraphs_gpt,
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

def create_job(pdf_path: str) -> str:
    """Create a new processing job and return job_id."""
    job_id = str(uuid.uuid4())
    job_dir = f"{TEMP_DIR}/{job_id}"
    os.makedirs(job_dir, exist_ok=True)
    
    job_state = {
        "job_id": job_id,
        "status": "created",
        "phase": "upload",
        "pdf_path": pdf_path,
        "markdown": None,
        "metadata": None,
        "cover_urls": None,
        "chapters": [],
        "error": None
    }
    
    save_job_state(job_id, job_state)
    print(f"[PIPELINE_V2] Created job: {job_id}")
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
# PHASE 1: PDF EXTRACTION (Marker API)
# ============================================

async def phase_extract_pdf(job_id: str) -> dict:
    """
    Extract PDF to Markdown using Marker API.
    
    Returns:
        {"success": True, "pages": N, "markdown_preview": "..."}
    """
    state = get_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    pdf_path = state["pdf_path"]
    
    try:
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
    Extract metadata with GPT and generate cover art with Nano Banana.
    
    Returns:
        {"metadata": {...}, "cover_urls": {...}}
    """
    state = get_job_state(job_id)
    if not state or not state.get("markdown"):
        raise ValueError(f"Job not found or no markdown: {job_id}")
    
    try:
        update_job_phase(job_id, "metadata", status="Extracting metadata...")
        
        # Use first 15% of markdown for metadata extraction
        markdown = state["markdown"]
        first_portion = markdown[:int(len(markdown) * 0.15)]
        
        # Extract metadata using existing GPT-based extraction
        metadata = extract_book_metadata(first_portion)
        
        update_job_phase(job_id, "cover_art", status="Generating cover art...")
        
        # Generate cover art (without uploading yet)
        cover_urls = generate_cover_image(metadata, upload=False)
        
        update_job_phase(
            job_id,
            "metadata_complete",
            status="Metadata and cover art ready",
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
    Detect chapter boundaries from Markdown headers.
    
    Returns:
        {"chapters": [{"index": 1, "title": "...", ...}, ...]}
    """
    state = get_job_state(job_id)
    if not state or not state.get("markdown"):
        raise ValueError(f"Job not found or no markdown: {job_id}")
    
    try:
        update_job_phase(job_id, "detecting_chapters", status="Detecting chapters...")
        
        markdown = state["markdown"]
        
        # Parse chapters from markdown headers
        chapters = parse_chapters_from_markdown(markdown)
        
        # Add status and preview to each chapter
        for ch in chapters:
            ch["status"] = "pending"
            text = extract_chapter_text(markdown, ch)
            ch["char_count"] = len(text)
            ch["preview"] = text[:200] + "..." if len(text) > 200 else text
            ch["sections"] = None
            ch["paragraphs"] = None
        
        update_job_phase(
            job_id,
            "chapters_detected",
            status=f"Found {len(chapters)} chapters",
            chapters=chapters
        )
        
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
        
        # Extract chapter text
        markdown = state["markdown"]
        chapter_text = extract_chapter_text(markdown, chapter)
        
        # Clean the text (remove markdown artifacts)
        cleaned_text = clean_markdown_text(chapter_text)
        
        # Create sections using GPT semantic splitting
        sections = split_into_paragraphs_gpt(cleaned_text)
        
        # Apply final TTS cleanup to each section
        sections = [clean_section_text(s) for s in sections if s.strip()]
        
        # Paragraphs are the same as sections (semantic splitting)
        paragraphs = sections.copy()
        
        # Update chapter with results
        chapter["status"] = "ready"
        chapter["sections"] = sections
        chapter["paragraphs"] = paragraphs
        chapter["section_count"] = len(sections)
        chapter["paragraph_count"] = len(paragraphs)
        
        save_job_state(job_id, state)
        
        print(f"[PIPELINE_V2] ✅ Chapter {chapter_index} complete: {len(sections)} sections")
        
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
    Clean markdown artifacts from text.
    Removes headers like # and ##, preserves content.
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
    
    # Normalize whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
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
            print(f"[PIPELINE_V2] ⚠️ Cover art upload failed: {cover_error}")
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
            chapter_data = [{
                "chapter_index": ch["index"],
                "title": ch["title"],
                "text": extract_chapter_text(state["markdown"], ch)
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
