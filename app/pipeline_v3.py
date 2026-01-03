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
    """
    state = get_v3_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    file_path = state["file_path"]
    file_type = state["file_type"]
    
    chapters = []
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
            
            for ch in data.get("chapters", []):
                chapters.append({
                    "index": ch.get("index", len(chapters)),
                    "title": ch.get("title", f"Chapter {len(chapters)+1}"),
                    "raw_content": ch.get("content", ""),
                    "paragraphs": [],
                    "sections": [],
                    "processed": False
                })
        
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
            from app.chapters import smart_extract_chapters
            _, extracted = smart_extract_chapters(markdown)
            
            for i, ch in enumerate(extracted):
                chapters.append({
                    "index": i,
                    "title": ch.get("title", f"Chapter {i+1}"),
                    "raw_content": ch.get("content", ""),
                    "paragraphs": [],
                    "sections": [],
                    "processed": False
                })
        
        state["chapters"] = chapters
        state["metadata"] = metadata
        state["progress"]["total_chapters"] = len(chapters)
        state["phase"] = "extracted"
        save_v3_job_state(job_id, state)
        
        logger.info(f"[V3] Extracted {len(chapters)} chapters from {file_type}")
        return {"success": True, "chapters": len(chapters), "metadata": metadata}
    
    except Exception as e:
        logger.error(f"[V3] Extraction error: {e}")
        state["phase"] = "error"
        state["error"] = str(e)
        save_v3_job_state(job_id, state)
        raise


# ============================================
# GLM PROCESSING PHASE
# ============================================

async def v3_process_chapters(job_id: str) -> Dict:
    """
    Process all chapters through GLM 4.7.
    Creates paragraphs and sections for each chapter.
    """
    state = get_v3_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    state["phase"] = "processing"
    save_v3_job_state(job_id, state)
    
    total = len(state["chapters"])
    processed = 0
    
    for i, chapter in enumerate(state["chapters"]):
        if chapter.get("processed"):
            processed += 1
            continue
        
        state["progress"]["current_chapter"] = chapter["title"]
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
                # Only fill in missing fields
                for key in ["author", "year", "publisher", "category"]:
                    if not metadata.get(key) and ai_metadata.get(key):
                        metadata[key] = ai_metadata[key]
                results["metadata_lookup"] = True
    
    except Exception as e:
        logger.error(f"[V3] Metadata lookup error: {e}")
        results["metadata_error"] = str(e)
    
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
# SUPABASE UPLOAD (PLACEHOLDER)
# ============================================

async def v3_upload_to_supabase(job_id: str) -> Dict:
    """
    Upload processed book data to Supabase.
    Called after pipeline is complete.
    """
    state = get_v3_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    if state["phase"] != "complete":
        raise ValueError(f"Pipeline not complete. Current phase: {state['phase']}")
    
    # TODO: Implement Supabase upload
    # - Create book record
    # - Create chapter records
    # - Create section records
    # - Create paragraph records
    
    logger.info(f"[V3] Ready for Supabase upload: {job_id[:8]}")
    return {"ready": True, "job_id": job_id}
