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
from app.audio_segments import (
    process_segments,
    group_segments,
    get_audio_duration_ms,
    concat_group_audio,
    upload_group_audio,
    save_groups_to_supabase,
    update_chapter_audio_version,
    create_chapter_build,          # TTS-First v3.1
    generate_paragraph_spans       # TTS-First v3.1
)

logger = get_logger(__name__)


def clean_display_title(title: str, node_type: str = None) -> str:
    """
    Clean a chapter title for display by removing 'Chapter X -' prefix.
    
    Examples:
        'Chapter 0 - Prefatory Note' -> 'Prefatory Note'
        'Chapter 1 - The Introduction' -> 'The Introduction'
        'Chapter 5 - The Contents' -> 'The Contents'
        'The Stone of the Philosophers' -> 'The Stone of the Philosophers'
    
    Args:
        title: Raw chapter title
        node_type: Optional node type for context
    
    Returns:
        Cleaned title for display
    """
    import re
    
    if not title:
        return title
    
    # Pattern: "Chapter X -" or "Chapter X:" where X is number or roman numeral
    pattern = r'^Chapter\s+[\dIVXLCDM]+\s*[-–:]\s*'
    cleaned = re.sub(pattern, '', title, flags=re.IGNORECASE)
    
    # If cleaning removed everything, keep original
    if not cleaned.strip():
        return title
    
    return cleaned.strip()


def load_mapping_file(json_file_path: str, json_data: Dict = None) -> Optional[Dict]:
    """
    Check for and load a manual mapping file (_mapping.json) or embedded mapping.
    
    The Mapping Editor saves manual changes to {filename}_mapping.json
    alongside the original JSON. If this file exists, it contains
    user-curated node types, titles, and hierarchy.
    
    For V3 Pipeline on Railway, the mapping can also be embedded directly
    in the JSON file under the 'manual_mapping' key (via /api/mapping/export).
    
    Args:
        json_file_path: Path to the original book JSON file
        json_data: Optional pre-loaded JSON data to check for embedded mapping
        
    Returns:
        Mapping dict with 'nodes' array if found, None otherwise
    """
    # First check for embedded mapping in JSON data (from /api/mapping/export)
    if json_data and json_data.get('manual_mapping'):
        mapping = json_data.get('manual_mapping')
        if mapping and mapping.get('nodes'):
            logger.info(f"[V3] ✅ Found embedded mapping in JSON ({len(mapping['nodes'])} nodes)")
            return mapping
        else:
            logger.warning(f"[V3] Embedded mapping exists but has no nodes")
    
    # Fall back to external _mapping.json file
    if not json_file_path:
        return None
    
    # Construct mapping file path: book.json -> book_mapping.json
    mapping_path = json_file_path.replace('.json', '_mapping.json')
    
    if os.path.exists(mapping_path):
        try:
            with open(mapping_path, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
            
            if mapping and mapping.get('nodes'):
                logger.info(f"[V3] ✅ Found external mapping: {os.path.basename(mapping_path)} ({len(mapping['nodes'])} nodes)")
                return mapping
            else:
                logger.warning(f"[V3] Mapping file exists but has no nodes: {mapping_path}")
        except Exception as e:
            logger.error(f"[V3] Error loading mapping file: {e}")
    
    return None


def apply_mapping_to_chapters(chapters: List[Dict], mapping: Dict) -> List[Dict]:
    """
    Apply manual mapping overrides to extracted chapters.
    
    Matches chapters to mapping nodes by source_title or order,
    then applies display_title, node_type, and exclusion flags.
    
    Args:
        chapters: List of chapter dicts from extraction
        mapping: Mapping dict with 'nodes' array
        
    Returns:
        Updated chapters list with mapping applied
    """
    if not mapping or not mapping.get('nodes'):
        return chapters
    
    nodes = mapping['nodes']
    
    # Build lookup by source_title and chapter_index
    node_by_source = {}
    node_by_index = {}
    
    for node in nodes:
        if node.get('source_title'):
            node_by_source[node['source_title']] = node
        if node.get('chapter_index') is not None:
            node_by_index[node['chapter_index']] = node
    
    # Apply mapping to each chapter
    mapped_count = 0
    for ch in chapters:
        original_title = ch.get('title', '')
        chapter_index = ch.get('index')
        
        # Try to find matching node
        node = None
        if original_title in node_by_source:
            node = node_by_source[original_title]
        elif chapter_index is not None and chapter_index in node_by_index:
            node = node_by_index[chapter_index]
        
        if node:
            # Apply mapping overrides
            ch['display_title'] = node.get('display_title', original_title)
            ch['content_type'] = node.get('node_type', ch.get('content_type', 'chapter'))
            ch['exclude_from_frontend'] = node.get('exclude_from_frontend', False)
            ch['exclude_from_audio'] = node.get('exclude_from_audio', False)
            ch['has_content'] = node.get('has_content', True)
            ch['order_key'] = node.get('order_key')
            ch['parent_order_key'] = node.get('parent_order_key')
            
            mapped_count += 1
            
            # Log significant changes
            if node.get('display_title') != original_title:
                logger.info(f"[V3] Mapping: '{original_title}' -> '{node.get('display_title')}' (type: {ch['content_type']})")
    
    logger.info(f"[V3] Applied mapping to {mapped_count}/{len(chapters)} chapters")
    return chapters


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


def update_v3_job_metadata(job_id: str, metadata_updates: Dict) -> Dict:
    """
    Update metadata for a V3 job (allows manual editing before Supabase upload).
    
    Args:
        job_id: The job UUID
        metadata_updates: Dict with fields to update (title, author, year, etc.)
    
    Returns:
        Updated metadata dict
    """
    state = get_v3_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    # Update metadata fields
    current_metadata = state.get("metadata", {})
    
    # Allow updating these fields
    editable_fields = [
        "title", "author", "year", "publishing_year", "publisher",
        "language", "original_language", "category", "synopsis",
        "book_of_the_day_quote"
    ]
    
    for field in editable_fields:
        if field in metadata_updates:
            value = metadata_updates[field]
            # Convert year to int if possible
            if field in ["year", "publishing_year"] and value:
                try:
                    value = int(value) if value else None
                except (ValueError, TypeError):
                    value = None
            current_metadata[field] = value
    
    state["metadata"] = current_metadata
    save_v3_job_state(job_id, state)
    
    logger.info(f"[V3] Updated metadata for job {job_id[:8]}: {list(metadata_updates.keys())}")
    return current_metadata


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
                    "raw_content": ch.get("content") or ch.get("text") or "",
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
        
        # ============================================
        # APPLY MANUAL MAPPING (if exists)
        # ============================================
        # Check for embedded mapping in JSON or external _mapping.json file
        json_data = data if file_type == "json" else None
        mapping = load_mapping_file(file_path, json_data)
        if mapping:
            # Apply manual overrides to chapters
            chapters = apply_mapping_to_chapters(chapters, mapping)
            
            # Store mapping info in state for later reference
            state["has_manual_mapping"] = True
            state["mapping_version"] = mapping.get("version", 1)
            state["mapping_created_at"] = mapping.get("createdAt")
            # Store full mapping nodes for upload (includes container nodes)
            state["mapping_nodes"] = mapping.get("nodes", [])
        else:
            state["has_manual_mapping"] = False
            state["mapping_nodes"] = []
        
        state["chapters"] = chapters
        state["parts"] = parts
        state["treatises"] = treatises if 'treatises' in dir() else []
        state["metadata"] = metadata
        state["progress"]["total_chapters"] = len(chapters)
        state["progress"]["total_parts"] = len(parts)
        state["progress"]["total_treatises"] = len(treatises) if 'treatises' in dir() else 0
        state["phase"] = "extracted"
        save_v3_job_state(job_id, state)
        
        mapping_info = " (with manual mapping)" if mapping else ""
        parts_info = f" ({len(parts)} parts)" if parts else ""
        treatises_info = f" ({len(treatises)} treatises)" if treatises else ""
        logger.info(f"[V3] Extracted {len(chapters)} chapters{parts_info}{treatises_info}{mapping_info} from {file_type}")
        return {"success": True, "chapters": len(chapters), "parts": len(parts), "treatises": len(treatises) if 'treatises' in dir() else 0, "metadata": metadata, "has_mapping": bool(mapping)}
    
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
# TTS AUDIO GENERATION (v3.1 Architecture)
# ============================================

async def v3_generate_tts_audio(
    job_id: str,
    engine: str = "runpod",  # "runpod", "local", "piper"
    voice: str = "default",
    language: str = "en"
) -> Dict:
    """
    Generate TTS audio for all chapters using the v3.1 segment/group architecture.
    
    This phase:
    1. Takes sections from GLM processing
    2. Merges short segments (<60 chars) and clamps long ones (>420 chars)
    3. Generates TTS audio for each segment
    4. Measures actual audio duration
    5. Groups segments into ~35 second audio_groups
    6. Concatenates group audio files
    7. Uploads to Supabase (tts_segments, audio_groups tables)
    
    Args:
        job_id: Pipeline job ID
        engine: TTS engine to use ("runpod", "local", "piper")
        voice: Voice to use for TTS
        language: Language code (e.g., "en", "da")
    
    Returns:
        Dict with success status and stats
    """
    import tempfile
    import sys
    
    # Add HonoraLocalTTS to path for TTS engines
    tts_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "HonoraLocalTTS")
    if tts_path not in sys.path:
        sys.path.insert(0, tts_path)
    
    from tts_engines import XTTSRunPodEngine, XTTSLocalEngine, PiperEngine
    
    state = get_v3_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    if state["phase"] not in ["chapters_processed", "complete", "uploaded"]:
        raise ValueError(f"Chapters not processed yet. Current phase: {state['phase']}")
    
    state["phase"] = "generating_tts"
    save_v3_job_state(job_id, state)
    
    # Initialize TTS engine
    if engine == "runpod":
        tts_engine = XTTSRunPodEngine()
    elif engine == "local":
        tts_engine = XTTSLocalEngine()
    elif engine == "piper":
        tts_engine = PiperEngine()
    else:
        raise ValueError(f"Unknown TTS engine: {engine}")
    
    logger.info(f"[V3.1] Starting TTS generation with {engine} engine")
    
    # Stats
    total_segments = 0
    total_groups = 0
    total_chapters_processed = 0
    errors = []
    
    chapters = state.get("chapters", [])
    
    # Create temp directory for audio files
    with tempfile.TemporaryDirectory() as temp_dir:
        for ch_idx, chapter in enumerate(chapters):
            chapter_title = chapter.get("title", f"Chapter {ch_idx + 1}")
            
            # Skip if no sections
            sections = chapter.get("sections", [])
            if not sections:
                logger.warning(f"[V3.1] No sections for chapter: {chapter_title}")
                continue
            
            # Skip if excluded from audio
            if chapter.get("exclude_from_audio"):
                logger.info(f"[V3.1] Skipping excluded chapter: {chapter_title}")
                continue
            
            logger.info(f"[V3.1] Processing chapter {ch_idx + 1}/{len(chapters)}: {chapter_title}")
            
            try:
                # Step 1: Process sections into segments (merge short, clamp long)
                section_texts = [s.get("text", "") for s in sections if s.get("text")]
                segments = process_segments(section_texts)
                
                logger.info(f"[V3.1] {len(section_texts)} sections -> {len(segments)} segments")
                
                # Step 2: Generate TTS for each segment
                for seg_idx, segment in enumerate(segments):
                    seg_text = segment["text"]
                    audio_path = os.path.join(temp_dir, f"seg_{ch_idx}_{seg_idx}.wav")
                    
                    # Generate TTS
                    success = tts_engine.generate(
                        text=seg_text,
                        voice=voice,
                        language=language,
                        output_path=audio_path
                    )
                    
                    if success and os.path.exists(audio_path):
                        # Measure actual duration
                        duration_ms = get_audio_duration_ms(audio_path)
                        segment["audio_path"] = audio_path
                        segment["duration_ms"] = duration_ms
                        logger.debug(f"[V3.1] Segment {seg_idx}: {duration_ms}ms")
                    else:
                        logger.error(f"[V3.1] TTS failed for segment {seg_idx}")
                        segment["duration_ms"] = 5000  # Fallback estimate
                
                # Step 3: Group segments by duration (~35 sec per group)
                groups = group_segments(segments)
                
                logger.info(f"[V3.1] Created {len(groups)} audio groups")
                
                # Step 4: Concatenate each group's audio
                chapter_id = chapter.get("db_chapter_id")  # Will be set during upload
                
                for group in groups:
                    try:
                        group_audio_path = concat_group_audio(group, temp_dir)
                        group["local_audio_path"] = group_audio_path
                        
                        # Measure final group duration
                        group["duration_ms"] = get_audio_duration_ms(group_audio_path)
                    except Exception as e:
                        logger.error(f"[V3.1] Failed to concat group {group['group_index']}: {e}")
                
                # Store groups in chapter for later upload
                chapter["audio_groups"] = groups
                chapter["segments"] = segments
                total_segments += len(segments)
                total_groups += len(groups)
                total_chapters_processed += 1
                
            except Exception as e:
                logger.error(f"[V3.1] Error processing chapter {chapter_title}: {e}")
                errors.append({"chapter": chapter_title, "error": str(e)})
        
        # Save state with TTS data
        state["chapters"] = chapters
        state["phase"] = "tts_generated"
        state["tts_stats"] = {
            "engine": engine,
            "voice": voice,
            "language": language,
            "total_segments": total_segments,
            "total_groups": total_groups,
            "chapters_processed": total_chapters_processed,
            "errors": errors
        }
        save_v3_job_state(job_id, state)
    
    logger.info(f"[V3.1] TTS generation complete: {total_segments} segments, {total_groups} groups")
    
    return {
        "success": len(errors) == 0,
        "total_segments": total_segments,
        "total_groups": total_groups,
        "chapters_processed": total_chapters_processed,
        "errors": errors
    }


async def v3_upload_audio_to_supabase(job_id: str) -> Dict:
    """
    Upload generated TTS audio groups to Supabase.
    
    TTS-First v3.1: Now creates chapter_build and paragraph_spans.
    
    This uploads:
    - Audio files to Supabase Storage (audio bucket)
    - Creates chapter_build (atomic versioning)
    - tts_segments records (with build_id)
    - audio_groups records (with build_id)
    - paragraph_spans records (links paragraphs to segments)
    - Updates chapter.audio_version to "v2"
    
    Should be called after v3_generate_tts_audio.
    """
    state = get_v3_job_state(job_id)
    if not state:
        raise ValueError(f"Job not found: {job_id}")
    
    if state["phase"] != "tts_generated":
        raise ValueError(f"TTS not generated yet. Current phase: {state['phase']}")
    
    state["phase"] = "uploading_audio"
    save_v3_job_state(job_id, state)
    
    chapters = state.get("chapters", [])
    total_groups_uploaded = 0
    total_segments_saved = 0
    total_spans_created = 0
    
    for chapter in chapters:
        groups = chapter.get("audio_groups", [])
        if not groups:
            continue
        
        chapter_id = chapter.get("db_chapter_id")
        if not chapter_id:
            logger.warning(f"[V3.1] No chapter_id for {chapter.get('title')}, skipping audio upload")
            continue
        
        logger.info(f"[V3.1] Uploading audio for: {chapter.get('title')}")
        
        # Upload each group's audio file
        for group in groups:
            local_path = group.get("local_audio_path")
            if local_path and os.path.exists(local_path):
                audio_url = upload_group_audio(local_path, chapter_id, group["group_index"])
                group["audio_url"] = audio_url
                total_groups_uploaded += 1
        
        # TTS-First v3.1: Create chapter_build for atomic versioning
        segments = chapter.get("segments", [])
        build_id = create_chapter_build(chapter_id, segments)
        
        # Build paragraph_id_map (segment_index -> paragraph_id)
        paragraphs = chapter.get("paragraphs", [])
        paragraph_id_map = {}
        
        # Simple 1:1 mapping if same count, otherwise proportional
        if len(paragraphs) == len(segments):
            for i, p in enumerate(paragraphs):
                if p.get("db_paragraph_id"):
                    paragraph_id_map[i] = p["db_paragraph_id"]
        else:
            # Proportional mapping
            if paragraphs and segments:
                for seg_idx in range(len(segments)):
                    para_idx = int(seg_idx * len(paragraphs) / len(segments))
                    if para_idx < len(paragraphs) and paragraphs[para_idx].get("db_paragraph_id"):
                        paragraph_id_map[seg_idx] = paragraphs[para_idx]["db_paragraph_id"]
        
        # Save to Supabase tables (with build_id)
        group_ids = save_groups_to_supabase(chapter_id, build_id, groups, paragraph_id_map)
        total_segments_saved += sum(len(g.get("segments", [])) for g in groups)
        
        # TTS-First v3.1: Generate paragraph_spans
        span_ids = generate_paragraph_spans(chapter_id, build_id, paragraphs, segments)
        total_spans_created += len(span_ids)
        
        # Update chapter audio_version (with build_id link)
        update_chapter_audio_version(chapter_id, build_id, "v2")
    
    state["phase"] = "audio_uploaded"
    state["audio_upload_stats"] = {
        "groups_uploaded": total_groups_uploaded,
        "segments_saved": total_segments_saved,
        "spans_created": total_spans_created
    }
    save_v3_job_state(job_id, state)
    
    logger.info(f"[V3.1] Audio upload complete: {total_groups_uploaded} groups, {total_segments_saved} segments, {total_spans_created} spans")
    
    return {
        "success": True,
        "groups_uploaded": total_groups_uploaded,
        "segments_saved": total_segments_saved,
        "spans_created": total_spans_created
    }


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

def create_nodes_from_mapping(book_id: str, mapping_nodes: List[Dict]) -> Dict[str, str]:
    """
    Create book_nodes in Supabase from mapping structure.
    
    This handles the complex tree structure from the Mapping Editor,
    including container nodes (has_content=False) and proper parent-child
    relationships via order_key.
    
    Args:
        book_id: The book UUID
        mapping_nodes: List of mapping node dicts from mapping.json
        
    Returns:
        Dict mapping order_key -> node_id for chapter content linking
    """
    from app.chapters import create_book_node
    
    # Sort by order_key to ensure parents are created before children
    sorted_nodes = sorted(mapping_nodes, key=lambda n: n.get('order_key', '9999'))
    
    # Map order_key -> node_id for parent lookups
    order_key_to_id = {}
    
    for node in sorted_nodes:
        order_key = node.get('order_key')
        parent_order_key = node.get('parent_order_key')
        
        # Resolve parent_id from parent_order_key
        parent_id = order_key_to_id.get(parent_order_key) if parent_order_key else None
        
        # Get node properties with defaults
        node_type = node.get('node_type', 'chapter')
        display_title = node.get('display_title', 'Untitled')
        source_title = node.get('source_title', display_title)
        has_content = node.get('has_content', True)
        exclude_from_frontend = node.get('exclude_from_frontend', False)
        exclude_from_audio = node.get('exclude_from_audio', False)
        
        # Create the node
        created_node = create_book_node(
            book_id=book_id,
            node_type=node_type,
            display_title=display_title,
            source_title=source_title,
            parent_id=parent_id,
            order_key=order_key,  # Use the order_key from mapping!
            has_content=has_content,
            exclude_from_frontend=exclude_from_frontend,
            exclude_from_audio=exclude_from_audio
        )
        
        # Store mapping
        order_key_to_id[order_key] = created_node['id']
        
        logger.info(f"[V3] Created node: {node_type} '{display_title}' (order: {order_key}, parent: {parent_order_key or 'root'})")
    
    return order_key_to_id


async def v3_upload_to_supabase(job_id: str) -> Dict:
    """
    Upload processed V3 book data to Supabase using book_nodes tree structure.
    
    Creates:
    - Book record (with metadata, cover art URLs)
    - book_nodes (tree structure: parts → chapters)
    - chapters (legacy, linked to nodes)
    - tts_chunks (TTS audio chunks)
    - paragraphs (UI text for highlighting)
    - book_node_paragraphs (links nodes to paragraphs)
    - paragraph_tts_chunks (links paragraphs to TTS chunks)
    """
    from app.chapters import (
        create_book_in_supabase,
        write_chapters_to_supabase,
        write_sections_to_supabase,  # Now uses tts_chunks table
        write_paragraphs_to_supabase,
        create_book_node,
        link_node_paragraphs,
        link_paragraph_tts_chunks,
        map_content_type_to_node_type
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
    has_manual_mapping = state.get("has_manual_mapping", False)
    mapping_nodes = state.get("mapping_nodes", [])
    
    try:
        logger.info(f"[V3] Starting Supabase upload for: {metadata.get('title')}")
        
        # Step 1: Create book record
        book_id = create_book_in_supabase(metadata)
        logger.info(f"[V3] Created book: {book_id}")
        
        # Step 2: Update cover art URLs
        if cover_urls:
            update_book_cover_url(book_id, cover_urls)
            logger.info(f"[V3] Updated cover art URLs")
        
        # Step 3 & 4: Create book_nodes and link content
        total_tts_chunks = 0
        total_paragraphs = 0
        total_nodes_created = 0
        
        # Build a lookup: chapter_index -> chapter data (for content linking)
        chapter_by_index = {ch.get('index'): ch for ch in chapters}
        
        if has_manual_mapping and mapping_nodes:
            # ============================================
            # MAPPING-BASED UPLOAD (uses full tree structure)
            # ============================================
            logger.info(f"[V3] Using manual mapping with {len(mapping_nodes)} nodes")
            
            # Create all nodes from mapping (including containers)
            order_key_to_node_id = create_nodes_from_mapping(book_id, mapping_nodes)
            total_nodes_created = len(order_key_to_node_id)
            
            # Now link chapter content to nodes
            # Mapping nodes have chapter_index pointing to which chapter's content they use
            for map_node in mapping_nodes:
                chapter_index = map_node.get('chapter_index')
                order_key = map_node.get('order_key')
                node_id = order_key_to_node_id.get(order_key)
                
                # Skip nodes without chapter_index (containers or manually added)
                if chapter_index is None or node_id is None:
                    continue
                
                # Find the corresponding chapter with content
                ch = chapter_by_index.get(chapter_index)
                if not ch:
                    logger.warning(f"[V3] No chapter found for index {chapter_index}")
                    continue
                
                # Skip if completely excluded
                if map_node.get('exclude_from_frontend') and map_node.get('exclude_from_audio'):
                    logger.info(f"[V3] Skipping excluded node: {map_node.get('display_title')}")
                    continue
                
                logger.info(f"[V3] Linking content for: {map_node.get('display_title')} (chapter_index={chapter_index})")
                
                # Create legacy chapter record (for backwards compatibility)
                chapter_data = [{
                    "chapter_index": ch["index"],
                    "title": ch["title"],
                    "text": ch.get("raw_content", ""),
                    "node_id": node_id  # Link to book_node
                }]
                
                db_chapters = write_chapters_to_supabase(book_id, chapter_data)
                
                if db_chapters:
                    chapter_id = db_chapters[0]["id"]
                    
                    # Store chapter_id for TTS audio upload
                    ch["db_chapter_id"] = chapter_id
                    
                    # Get paragraph and section data
                    paragraphs = ch.get("paragraphs", [])
                    sections = ch.get("sections", [])
                    
                    # Write paragraphs to Supabase
                    paragraph_ids = []
                    if paragraphs:
                        paragraph_texts = [p["text"] for p in paragraphs if p.get("text")]
                        from app.chapters import get_supabase
                        supabase = get_supabase()
                        
                        for idx, text in enumerate(paragraph_texts):
                            result = supabase.table("paragraphs").insert({
                                "chapter_id": chapter_id,
                                "paragraph_index": idx,
                                "text": text,
                                "start_ms": None,
                                "end_ms": None
                            }).execute()
                            if result.data:
                                paragraph_ids.append(result.data[0]["id"])
                        
                        total_paragraphs += len(paragraph_ids)
                        logger.info(f"[V3] Wrote {len(paragraph_ids)} paragraphs")
                        
                        # Link paragraphs to book_node
                        link_node_paragraphs(node_id, paragraph_ids)
                    
                    # Write TTS chunks and link to paragraphs
                    if sections:
                        section_texts = [s["text"] for s in sections if s.get("text")]
                        tts_chunk_ids = write_sections_to_supabase(chapter_id, section_texts)
                        total_tts_chunks += len(tts_chunk_ids)
                        logger.info(f"[V3] Wrote {len(tts_chunk_ids)} TTS chunks")
                        
                        # Link TTS chunks to paragraphs
                        if paragraph_ids and tts_chunk_ids:
                            chunks_per_para = max(1, len(tts_chunk_ids) // len(paragraph_ids))
                            chunk_idx = 0
                            for para_id in paragraph_ids:
                                para_chunks = tts_chunk_ids[chunk_idx:chunk_idx + chunks_per_para]
                                if para_chunks:
                                    link_paragraph_tts_chunks(para_id, para_chunks)
                                chunk_idx += chunks_per_para
        
        else:
            # ============================================
            # LEGACY UPLOAD (auto-detected structure)
            # ============================================
            logger.info(f"[V3] Using auto-detected structure (no manual mapping)")
            
            # Maps: part_title -> node_id, treatise_title -> node_id
            part_node_map = {}
            treatise_node_map = {}
            
            # Create Part nodes (root level, no content themselves)
            for part in parts:
                node = create_book_node(
                    book_id=book_id,
                    node_type="part",
                    display_title=part.get("title", f"Part {part.get('part_index', 0)}"),
                    source_title=part.get("title"),
                    has_content=False
                )
                part_node_map[part.get("title")] = node["id"]
                total_nodes_created += 1
                logger.info(f"[V3] Created part node: {part.get('title')}")
            
            # Create Treatise nodes (can be root or under parts)
            for treatise in treatises:
                parent_part = treatise.get("parent_part")
                parent_id = part_node_map.get(parent_part) if parent_part else None
                
                node = create_book_node(
                    book_id=book_id,
                    node_type="treatise",
                    display_title=treatise.get("title", f"Treatise {treatise.get('treatise_index', 0)}"),
                    source_title=treatise.get("title"),
                    parent_id=parent_id,
                    has_content=False
                )
                treatise_node_map[treatise.get("title")] = node["id"]
                total_nodes_created += 1
                logger.info(f"[V3] Created treatise node: {treatise.get('title')}")
            
            # Create chapter nodes and content
            for ch in chapters:
                logger.info(f"[V3] Processing chapter {ch['index']+1}/{len(chapters)}: {ch['title']}")
                
                # Skip chapters excluded from frontend AND audio
                if ch.get('exclude_from_frontend') and ch.get('exclude_from_audio'):
                    logger.info(f"[V3] Skipping excluded chapter: {ch['title']}")
                    continue
                
                # Determine parent node
                parent_id = None
                if ch.get("parent_treatise"):
                    parent_id = treatise_node_map.get(ch["parent_treatise"])
                elif ch.get("parent_part"):
                    parent_id = part_node_map.get(ch["parent_part"])
                
                # Determine node_type from content_type
                content_type = ch.get("content_type", "chapter")
                node_type = map_content_type_to_node_type(content_type)
                
                # Use display_title from mapping if set, otherwise clean the raw title
                raw_title = ch["title"]
                if ch.get("display_title"):
                    display_title = ch["display_title"]
                else:
                    display_title = clean_display_title(raw_title, node_type)
                
                has_content = ch.get("has_content", True)
                
                # Create book_node for this chapter
                chapter_node = create_book_node(
                    book_id=book_id,
                    node_type=node_type,
                    display_title=display_title,
                    source_title=raw_title,
                    parent_id=parent_id,
                    has_content=has_content,
                    exclude_from_frontend=ch.get('exclude_from_frontend', False),
                    exclude_from_audio=ch.get('exclude_from_audio', False)
                )
                chapter_node_id = chapter_node["id"]
                total_nodes_created += 1
                
                # Create legacy chapter record
                chapter_data = [{
                    "chapter_index": ch["index"],
                    "title": ch["title"],
                    "text": ch.get("raw_content", ""),
                    "node_id": chapter_node_id
                }]
                
                db_chapters = write_chapters_to_supabase(book_id, chapter_data)
                
                if db_chapters:
                    chapter_id = db_chapters[0]["id"]
                    
                    # Store chapter_id for TTS audio upload
                    ch["db_chapter_id"] = chapter_id
                    
                    paragraphs = ch.get("paragraphs", [])
                    sections = ch.get("sections", [])
                    
                    paragraph_ids = []
                    if paragraphs:
                        paragraph_texts = [p["text"] for p in paragraphs if p.get("text")]
                        from app.chapters import get_supabase
                        supabase = get_supabase()
                        
                        for idx, text in enumerate(paragraph_texts):
                            result = supabase.table("paragraphs").insert({
                                "chapter_id": chapter_id,
                                "paragraph_index": idx,
                                "text": text,
                                "start_ms": None,
                                "end_ms": None
                            }).execute()
                            if result.data:
                                paragraph_ids.append(result.data[0]["id"])
                        
                        total_paragraphs += len(paragraph_ids)
                        logger.info(f"[V3] Wrote {len(paragraph_ids)} paragraphs")
                        
                        link_node_paragraphs(chapter_node_id, paragraph_ids)
                    
                    if sections:
                        section_texts = [s["text"] for s in sections if s.get("text")]
                        tts_chunk_ids = write_sections_to_supabase(chapter_id, section_texts)
                        total_tts_chunks += len(tts_chunk_ids)
                        logger.info(f"[V3] Wrote {len(tts_chunk_ids)} TTS chunks")
                        
                        if paragraph_ids and tts_chunk_ids:
                            chunks_per_para = max(1, len(tts_chunk_ids) // len(paragraph_ids))
                            chunk_idx = 0
                            for para_id in paragraph_ids:
                                para_chunks = tts_chunk_ids[chunk_idx:chunk_idx + chunks_per_para]
                                if para_chunks:
                                    link_paragraph_tts_chunks(para_id, para_chunks)
                                chunk_idx += chunks_per_para
        
        # Update job state
        state["phase"] = "uploaded"
        state["book_id"] = book_id
        state["chapters"] = chapters  # Store updated chapters with db_chapter_id
        state["upload_stats"] = {
            "book_nodes": total_nodes_created,
            "parts": len(parts),
            "treatises": len(treatises),
            "chapters": len(chapters),
            "tts_chunks": total_tts_chunks,
            "paragraphs": total_paragraphs,
            "used_manual_mapping": has_manual_mapping
        }
        save_v3_job_state(job_id, state)
        
        mapping_info = " (with manual mapping)" if has_manual_mapping else ""
        logger.info(f"[V3] ✅ Upload complete{mapping_info}: {total_nodes_created} nodes, {len(chapters)} chapters, {total_tts_chunks} TTS chunks, {total_paragraphs} paragraphs")
        
        return {
            "success": True,
            "book_id": book_id,
            "book_nodes": total_nodes_created,
            "parts": len(parts),
            "treatises": len(treatises),
            "chapters": len(chapters),
            "tts_chunks": total_tts_chunks,
            "paragraphs": total_paragraphs,
            "cover_urls": cover_urls,
            "used_manual_mapping": has_manual_mapping
        }
        
    except Exception as e:
        logger.error(f"[V3] Supabase upload error: {e}")
        state["phase"] = "upload_error"
        state["error"] = str(e)
        save_v3_job_state(job_id, state)
        raise



