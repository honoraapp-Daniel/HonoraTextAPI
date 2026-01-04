"""
V3 Pipeline: GLM 4.7 + Gemini
- GLM handles: paragraphs, sections (TTS), text cleaning
- Gemini handles: cover art, metadata (in parallel)
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime
import uuid

from app.logger import get_logger
from app.glm_processor import process_full_chapter
from app.cover_art import generate_cover_image
from app.metadata import extract_metadata_with_gemini

logger = get_logger(__name__)

# ============================================
# JOB STATE MANAGEMENT
# ============================================

V3_JOBS_DIR = "data/v3_jobs"
os.makedirs(V3_JOBS_DIR, exist_ok=True)


def get_v3_job_state(job_id: str) -> Optional[Dict]:
    """Get V3 job state from disk."""
    path = os.path.join(V3_JOBS_DIR, f"{job_id}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_v3_job_state(job_id: str, state: Dict):
    """Save V3 job state to disk."""
    path = os.path.join(V3_JOBS_DIR, f"{job_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def create_v3_job(file_path: str, file_type: str) -> str:
    """Create a new V3 pipeline job."""
    job_id = str(uuid.uuid4())
    
    state = {
        "job_id": job_id,
        "file_path": file_path,
        "file_type": file_type,
        "phase": "created",
        "created_at": datetime.now().isoformat(),
        "chapters": [],
        "metadata": {},
        "cover_urls": {},
        "progress": {
            "total_chapters": 0,
            "processed_chapters": 0,
            "current_chapter": None
        }
    }
    
    save_v3_job_state(job_id, state)
    logger.info(f"[V3] Created job {job_id[:8]}...")
    return job_id


# ============================================
# EXTRACTION PHASE
# ============================================

async def v3_extract_chapters(job_id: str) -> Dict:
    """
    Extract chapters from uploaded file.
    Supports JSON (from scraper) and PDF files.
    Now also extracts 'parts' for multi-part books.
    """
    state = get_v3_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    file_path = state["file_path"]
    file_type = state["file_type"]
    
    chapters = []
    parts = []
    metadata = {}
    
    try:
        if file_type == "json":
            # Load JSON from scraper
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            metadata = {
                "title": data.get("title", "Unknown"),
                "author": data.get("author", "Unknown"),
                "year": data.get("year", ""),
                "publisher": data.get("publisher", ""),
                "language": data.get("language", "English")
            }
            
            # Extract parts if present
            for p in data.get("parts", []):
                parts.append({
                    "part_index": p.get("index", len(parts) + 1),
                    "title": p.get("title", f"Part {len(parts) + 1}")
                })
            
            # Extract treatises if present (for anthology-style books)
            treatises = []
            for t in data.get("treatises", []):
                treatises.append({
                    "treatise_index": t.get("index", len(treatises) + 1),
                    "title": t.get("title", f"Treatise {len(treatises) + 1}")
                })
            
            # Build lookup tables for chapter linking
            part_titles = {p["part_index"]: p["title"] for p in parts}
            treatise_titles = {t["treatise_index"]: t["title"] for t in treatises}
            
            # Extract chapters with optional part/treatise linking and content_type
            for ch in data.get("chapters", []):
                chapter_data = {
                    "index": ch.get("index", len(chapters)),
                    "title": ch.get("title", f"Chapter {len(chapters)+1}"),
                    "raw_content": ch.get("content", ""),
                    "content_type": ch.get("content_type", "chapter"),  # prefatory, chapter, book, appendix
                    "paragraphs": [],
                    "sections": [],
                    "processed": False
                }
                
                # Link to part if specified
                if "part_index" in ch:
                    chapter_data["parent_part"] = part_titles.get(ch["part_index"])
                elif "part" in ch:
                    chapter_data["parent_part"] = ch["part"]
                
                # Link to treatise if specified (anthology-style books)
                if "treatise_index" in ch:
                    chapter_data["parent_treatise"] = treatise_titles.get(ch["treatise_index"])
                elif "treatise" in ch:
                    chapter_data["parent_treatise"] = ch["treatise"]
                
                chapters.append(chapter_data)
        
        elif file_type == "pdf":
            # Use Marker API for PDF extraction
            import httpx
            
            with open(file_path, "rb") as f:
                pdf_bytes = f.read()
            
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    "https://www.datalab.to/api/v1/marker",
                    headers={"X-Api-Key": os.getenv("MARKER_API_KEY", "")},
                    files={"file": ("book.pdf", pdf_bytes, "application/pdf")},
                    data={"output_format": "markdown"}
                )
                
                if response.status_code != 200:
                    raise ValueError(f"Marker API error: {response.status_code}")
                
                result = response.json()
                markdown = result.get("markdown", "")
            
            # Extract chapters from markdown
            from app.chapters import extract_chapters_smart
            _, extracted = extract_chapters_smart(markdown)
            
            for i, ch in enumerate(extracted):
                chapters.append({
                    "index": i,
                    "title": ch.get("title", f"Chapter {i+1}"),
                    "raw_content": ch.get("content", ""),
                    "content_type": "chapter",
                    "paragraphs": [],
                    "sections": [],
                    "processed": False
                })
            
            treatises = []  # PDFs don't have treatise detection yet
        
        state["chapters"] = chapters
        state["parts"] = parts
        state["treatises"] = treatises if 'treatises' in dir() else []
        state["metadata"] = metadata
        state["progress"]["total_chapters"] = len(chapters)
        state["progress"]["total_parts"] = len(parts)
        state["progress"]["total_treatises"] = len(treatises) if 'treatises' in dir() else 0
        state["phase"] = "extracted"
        save_v3_job_state(job_id, state)
        
        parts_info = f" ({len(parts)} parts)" if parts else ""
        treatises_info = f" ({len(treatises)} treatises)" if treatises else ""
        logger.info(f"[V3] Extracted {len(chapters)} chapters{parts_info}{treatises_info} from {file_type}")
        return {"success": True, "chapters": len(chapters), "parts": len(parts), "treatises": len(treatises) if 'treatises' in dir() else 0, "metadata": metadata}
    
    except Exception as e:
        logger.error(f"[V3] Extraction error: {e}")
        state["phase"] = "error"
        state["error"] = str(e)
        save_v3_job_state(job_id, state)
        raise


# ============================================
# GLM PROCESSING PHASE
# ============================================

# Batch size for context refresh - prevents model degradation on large books
BATCH_SIZE = 5


async def v3_process_chapters(job_id: str) -> Dict:
    """
    Process all chapters through Gemini.
    Creates paragraphs and sections for each chapter.
    
    BATCH PROCESSING: Every 5 chapters, we "refresh" the model context
    by re-initializing the Gemini client. This prevents quality degradation
    on large books (35+ chapters) where the model might start producing
    poor paragraph splits after many consecutive calls.
    """
    state = get_v3_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    state["phase"] = "processing"
    save_v3_job_state(job_id, state)
    
    total = len(state["chapters"])
    processed = 0
    
    # Import for context refresh
    from app.glm_processor import _gemini_configured
    import app.glm_processor as glm_module
    
    for i, chapter in enumerate(state["chapters"]):
        if chapter.get("processed"):
            processed += 1
            continue
        
        # BATCH CONTEXT REFRESH every 5 chapters
        if i > 0 and i % BATCH_SIZE == 0:
            logger.info(f"[V3] 🔄 Refreshing Gemini context at chapter {i+1} (batch boundary)")
            # Reset the configured flag to force re-initialization
            glm_module._gemini_configured = False
        
        state["progress"]["current_chapter"] = chapter["title"]
        state["progress"]["batch_info"] = f"Batch {(i // BATCH_SIZE) + 1} of {(total // BATCH_SIZE) + 1}"
        save_v3_job_state(job_id, state)
        
        logger.info(f"[V3] Processing chapter {i+1}/{total}: {chapter['title']}")
        
        try:
            # Call GLM to process chapter
            result = process_full_chapter(
                chapter_title=chapter["title"],
                chapter_text=chapter["raw_content"]
            )
            
            chapter["paragraphs"] = result["paragraphs"]
            chapter["sections"] = result["sections"]
            chapter["processed"] = True
            processed += 1
            
            # Log paragraph stats for monitoring
            para_count = len(result["paragraphs"])
            avg_words = sum(len(p["text"].split()) for p in result["paragraphs"]) / max(para_count, 1)
            logger.info(f"[V3] Chapter {i+1}: {para_count} paragraphs, avg {avg_words:.1f} words per paragraph")
            
            state["progress"]["processed_chapters"] = processed
            save_v3_job_state(job_id, state)
            
        except Exception as e:
            logger.error(f"[V3] Error processing chapter {chapter['title']}: {e}")
            chapter["error"] = str(e)
            save_v3_job_state(job_id, state)
    
    state["phase"] = "chapters_processed"
    save_v3_job_state(job_id, state)
    
    logger.info(f"[V3] Processed {processed}/{total} chapters")
    return {"success": True, "processed": processed, "total": total}



# ============================================
# GEMINI METADATA & COVER ART (PARALLEL)
# ============================================

async def v3_generate_metadata_and_cover(job_id: str) -> Dict:
    """
    Generate cover art and enrich metadata using Gemini.
    Can run in parallel with chapter processing.
    """
    state = get_v3_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    metadata = state.get("metadata", {})
    
    # Run cover art and metadata lookup in parallel
    results = {}
    
    try:
        # Generate cover art
        logger.info(f"[V3] Generating cover art for: {metadata.get('title')}")
        cover_urls = generate_cover_image(metadata, upload=True)
        
        if cover_urls:
            state["cover_urls"] = cover_urls
            metadata["cover_art_url"] = cover_urls.get("cover_art_url")
            metadata["cover_art_url_16x9"] = cover_urls.get("cover_art_url_16x9")
            results["cover_art"] = True
    
    except Exception as e:
        logger.error(f"[V3] Cover art error: {e}")
        results["cover_art_error"] = str(e)
    
    try:
        # Enrich metadata with AI
        if metadata.get("title"):
            logger.info(f"[V3] Looking up metadata for: {metadata.get('title')}")
            ai_metadata = extract_metadata_with_gemini(metadata.get("title"))
            
            if ai_metadata:
                # Copy all AI-extracted fields (only fill in missing ones)
                ai_fields = [
                    "author", "publisher", "category", "language",
                    "original_language", "publishing_year"
                ]
                for key in ai_fields:
                    if not metadata.get(key) and ai_metadata.get(key):
                        metadata[key] = ai_metadata[key]
                results["metadata_lookup"] = True
    
    except Exception as e:
        logger.error(f"[V3] Metadata lookup error: {e}")
        results["metadata_error"] = str(e)
    
    # Generate synopsis and quote from chapter content
    try:
        from app.metadata import generate_synopsis_and_category
        
        # Get first chapter content for synopsis
        chapters = state.get("chapters", [])
        if chapters and chapters[0].get("raw_content"):
            sample_text = chapters[0]["raw_content"][:5000]  # First 5000 chars
            
            logger.info(f"[V3] Generating synopsis for: {metadata.get('title')}")
            synopsis_data = generate_synopsis_and_category(sample_text)
            
            if synopsis_data:
                metadata["synopsis"] = synopsis_data.get("synopsis", "")
                # Use correct field name for Supabase
                metadata["book_of_the_day_quote"] = synopsis_data.get("book_of_the_day_quote", "")
                if not metadata.get("category") and synopsis_data.get("category"):
                    metadata["category"] = synopsis_data.get("category")
                results["synopsis"] = True
    
    except Exception as e:
        logger.error(f"[V3] Synopsis generation error: {e}")
    
    state["metadata"] = metadata
    save_v3_job_state(job_id, state)
    
    return results


# ============================================
# FULL PIPELINE EXECUTION
# ============================================

async def run_v3_pipeline(job_id: str) -> Dict:
    """
    Run the complete V3 pipeline:
    1. Extract chapters
    2. Process chapters through GLM (paragraphs, sections)
    3. Generate cover art and metadata with Gemini (parallel)
    4. Return ready-for-Supabase data
    """
    state = get_v3_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    logger.info(f"[V3] Starting pipeline for job {job_id[:8]}...")
    
    try:
        # Phase 1: Extract
        if state["phase"] == "created":
            await v3_extract_chapters(job_id)
            state = get_v3_job_state(job_id)
        
        # Phase 2 & 3: Run GLM and Gemini in parallel
        if state["phase"] == "extracted":
            # Start both tasks
            glm_task = asyncio.create_task(v3_process_chapters(job_id))
            gemini_task = asyncio.create_task(v3_generate_metadata_and_cover(job_id))
            
            # Wait for both
            glm_result, gemini_result = await asyncio.gather(
                glm_task, gemini_task, return_exceptions=True
            )
            
            if isinstance(glm_result, Exception):
                logger.error(f"[V3] GLM task failed: {glm_result}")
            if isinstance(gemini_result, Exception):
                logger.error(f"[V3] Gemini task failed: {gemini_result}")
        
        # Final state
        state = get_v3_job_state(job_id)
        state["phase"] = "complete"
        state["completed_at"] = datetime.now().isoformat()
        save_v3_job_state(job_id, state)
        
        logger.info(f"[V3] Pipeline complete for job {job_id[:8]}")
        
        return {
            "success": True,
            "job_id": job_id,
            "chapters": len(state["chapters"]),
            "metadata": state["metadata"],
            "cover_urls": state.get("cover_urls", {})
        }
    
    except Exception as e:
        logger.error(f"[V3] Pipeline error: {e}")
        state = get_v3_job_state(job_id)
        state["phase"] = "error"
        state["error"] = str(e)
        save_v3_job_state(job_id, state)
        raise


# ============================================
# SUPABASE UPLOAD
# ============================================

async def v3_upload_to_supabase(job_id: str) -> Dict:
    """
    Upload processed V3 book data to Supabase.
    
    Creates:
    - Book record (with metadata, cover art URLs)
    - Chapter records
    - Section records
    - Paragraph records
    """
    from app.chapters import (
        create_book_in_supabase,
        write_chapters_to_supabase,
        write_sections_to_supabase,
        write_paragraphs_to_supabase
    )
    from app.cover_art import update_book_cover_url
    
    state = get_v3_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    if state["phase"] != "complete":
        raise ValueError(f"Pipeline not complete. Current phase: {state['phase']}")
    
    metadata = state.get("metadata", {})
    chapters = state.get("chapters", [])
    parts = state.get("parts", [])
    treatises = state.get("treatises", [])
    cover_urls = state.get("cover_urls", {})
    
    try:
        logger.info(f"[V3] Starting Supabase upload for: {metadata.get('title')}")
        
        # Step 1: Create book record
        book_id = create_book_in_supabase(metadata)
        logger.info(f"[V3] Created book: {book_id}")
        
        # Step 2: Update cover art URLs
        if cover_urls:
            update_book_cover_url(book_id, cover_urls)
            logger.info(f"[V3] Updated cover art URLs")
        
        # Step 3: Create parts (if any)
        part_id_map = {}
        if parts:
            from app.chapters import write_parts_to_supabase
            part_id_map = write_parts_to_supabase(book_id, parts)
            logger.info(f"[V3] Created {len(parts)} parts")
        
        # Step 3b: Create treatises (if any) - for anthology-style books
        treatise_id_map = {}
        if treatises:
            from app.chapters import write_treatises_to_supabase
            treatise_id_map = write_treatises_to_supabase(book_id, treatises)
            logger.info(f"[V3] Created {len(treatises)} treatises")
        
        # Step 4: Create chapters with sections and paragraphs
        total_sections = 0
        total_paragraphs = 0
        
        for ch in chapters:
            logger.info(f"[V3] Uploading chapter {ch['index']+1}/{len(chapters)}: {ch['title']}")
            
            # Create chapter record with parent_part, parent_treatise, and content_type
            chapter_data = [{
                "chapter_index": ch["index"],
                "title": ch["title"],
                "text": ch.get("raw_content", ""),
                "content_type": ch.get("content_type", "chapter"),
                "parent_part": ch.get("parent_part"),
                "parent_story": ch.get("parent_treatise")  # Treatises use story_id in DB
            }]
            
            db_chapters = write_chapters_to_supabase(
                book_id, chapter_data, 
                story_id_map=treatise_id_map,  # Treatises map to story_id
                part_id_map=part_id_map
            )
            
            if db_chapters:
                chapter_id = db_chapters[0]["id"]
                
                # Write sections (expects list of strings)
                sections = ch.get("sections", [])
                if sections:
                    # Extract just text strings for Supabase
                    section_texts = [s["text"] for s in sections if s.get("text")]
                    write_sections_to_supabase(chapter_id, section_texts)
                    total_sections += len(section_texts)
                    logger.info(f"[V3] Wrote {len(section_texts)} sections")
                
                # Write paragraphs (expects list of strings)
                paragraphs = ch.get("paragraphs", [])
                if paragraphs:
                    # Extract just text strings for Supabase
                    paragraph_texts = [p["text"] for p in paragraphs if p.get("text")]
                    write_paragraphs_to_supabase(chapter_id, paragraph_texts)
                    total_paragraphs += len(paragraph_texts)
                    logger.info(f"[V3] Wrote {len(paragraph_texts)} paragraphs")
        
        # Update job state
        state["phase"] = "uploaded"
        state["book_id"] = book_id
        state["upload_stats"] = {
            "parts": len(parts),
            "chapters": len(chapters),
            "sections": total_sections,
            "paragraphs": total_paragraphs
        }
        save_v3_job_state(job_id, state)
        
        parts_info = f"{len(parts)} parts, " if parts else ""
        logger.info(f"[V3] ✅ Upload complete: {parts_info}{len(chapters)} chapters, {total_sections} sections, {total_paragraphs} paragraphs")
        
        return {
            "success": True,
            "book_id": book_id,
            "parts": len(parts),
            "chapters": len(chapters),
            "sections": total_sections,
            "paragraphs": total_paragraphs,
            "cover_urls": cover_urls
        }
        
    except Exception as e:
        logger.error(f"[V3] Supabase upload error: {e}")
        state["phase"] = "upload_error"
        state["error"] = str(e)
        save_v3_job_state(job_id, state)
        raise

