"""
Audio Segments & Groups Module for V3.1 Pipeline
Handles: segment merging, TTS generation, duration reading, grouping, concat, upload
"""

import os
import re
import uuid
import subprocess
import logging
import hashlib
import unicodedata
from typing import List, Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================
# CONFIGURATION
# ============================================

MIN_CHARS = 60          # Minimum segment length
MAX_CHARS = 420         # Maximum segment length (optimal for clone focus)
MIN_WORDS = 3           # Minimum word count
TARGET_GROUP_DURATION_MS = 35000  # 35 seconds per group

# Storage cleanup: False in prod, True in dev/QA
KEEP_SEGMENT_AUDIO = os.getenv("KEEP_SEGMENT_AUDIO", "false").lower() == "true"


# ============================================
# TEXT NORMALIZATION (TTS-First v3.1)
# ============================================

def normalize_text(text: str) -> str:
    """
    NFKC normalize + collapse whitespace.
    text_normalized MUST equal this for the text/text_normalized contract.
    """
    text = unicodedata.normalize('NFKC', text)
    return ' '.join(text.split())  # Collapse all whitespace to single spaces


def create_chapter_build(chapter_id: str, segments: List[Dict]) -> str:
    """
    Create a chapter_build via Supabase RPC for atomic versioning.
    
    Args:
        chapter_id: UUID of the chapter
        segments: List of segment dicts with 'text_normalized' keys
        
    Returns:
        build_id: UUID of the created build
    """
    from app.chapters import get_supabase
    supabase = get_supabase()
    
    # Build canonical_text from normalized segments
    canonical_text = ' '.join(
        s.get('text_normalized', normalize_text(s['text'])) 
        for s in segments
    )
    canonical_hash = hashlib.sha256(canonical_text.encode('utf-8')).hexdigest()
    
    # Call atomic RPC
    result = supabase.rpc('create_chapter_build', {
        'p_chapter_id': chapter_id,
        'p_canonical_text': canonical_text,
        'p_canonical_hash': canonical_hash
    }).execute()
    
    build_id = result.data
    logger.info(f"Created chapter_build {build_id} for chapter {chapter_id}")
    return build_id


# ============================================
# SEGMENT PROCESSING
# ============================================

def merge_short_segments(sections: List[str]) -> List[Dict]:
    """
    Merge segments that are too short (< MIN_CHARS or < MIN_WORDS).
    """
    merged = []
    pending = ""
    
    for text in sections:
        text = text.strip()
        if not text:
            continue
        
        if len(text) < MIN_CHARS or len(text.split()) < MIN_WORDS:
            pending = (pending + " " + text).strip() if pending else text
        else:
            if pending:
                text = pending + " " + text
                pending = ""
            merged.append({"text": text})
    
    # Flush remaining pending
    if pending:
        if merged:
            merged[-1]["text"] += " " + pending
        else:
            merged.append({"text": pending})
    
    return merged


def split_at_sentences(text: str, max_chars: int) -> List[str]:
    """
    Split text at sentence boundaries (.?!) to stay under max_chars.
    """
    if len(text) <= max_chars:
        return [text]
    
    # Split on sentence endings
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    result = []
    current = ""
    
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip() if current else sentence
        else:
            if current:
                result.append(current)
            # If single sentence is too long, force split at max_chars
            if len(sentence) > max_chars:
                while len(sentence) > max_chars:
                    # Find last space before max_chars
                    split_point = sentence[:max_chars].rfind(' ')
                    if split_point == -1:
                        split_point = max_chars
                    result.append(sentence[:split_point].strip())
                    sentence = sentence[split_point:].strip()
                current = sentence
            else:
                current = sentence
    
    if current:
        result.append(current)
    
    return result


def clamp_long_segments(merged: List[Dict]) -> List[Dict]:
    """
    Split segments that exceed MAX_CHARS at sentence boundaries.
    """
    clamped = []
    
    for seg in merged:
        text = seg["text"]
        if len(text) > MAX_CHARS:
            splits = split_at_sentences(text, MAX_CHARS)
            for s in splits:
                clamped.append({"text": s})
        else:
            clamped.append(seg)
    
    return clamped


def process_segments(raw_sections: List[str]) -> List[Dict]:
    """
    Full segment processing pipeline:
    1. Merge short segments
    2. Clamp long segments
    3. Assign segment_index
    4. Add text_normalized (TTS-First v3.1)
    """
    merged = merge_short_segments(raw_sections)
    clamped = clamp_long_segments(merged)
    
    # Assign indices and normalize text
    for i, seg in enumerate(clamped):
        seg["segment_index"] = i
        seg["text_normalized"] = normalize_text(seg["text"])
    
    logger.info(f"Processed {len(raw_sections)} raw sections -> {len(clamped)} segments")
    return clamped


# ============================================
# AUDIO DURATION READING
# ============================================

def get_audio_duration_ms(audio_path: str) -> int:
    """
    Read actual audio duration using ffprobe.
    Returns duration in milliseconds.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        duration_sec = float(result.stdout.strip())
        return int(duration_sec * 1000)
    except Exception as e:
        logger.error(f"Error reading audio duration: {e}")
        # Fallback: estimate from file size (rough)
        return 5000  # Default 5 seconds


# ============================================
# GROUPING
# ============================================

def group_segments(segments: List[Dict]) -> List[Dict]:
    """
    Group segments by target duration (~35 seconds).
    Sets group_id, offset_in_group_ms, and calculates start_time_ms.
    """
    groups = []
    current_group = {
        "group_index": 0,
        "segments": [],
        "duration_ms": 0,
        "start_time_ms": 0
    }
    chapter_time = 0
    
    for seg in segments:
        seg_duration = seg.get("duration_ms", 5000)  # Use measured duration
        
        # Check if adding this segment exceeds target
        if current_group["duration_ms"] + seg_duration > TARGET_GROUP_DURATION_MS and current_group["segments"]:
            # Finalize current group
            groups.append(current_group)
            chapter_time += current_group["duration_ms"]
            
            # Start new group
            current_group = {
                "group_index": len(groups),
                "segments": [],
                "duration_ms": 0,
                "start_time_ms": chapter_time
            }
        
        # Add segment to current group
        seg["offset_in_group_ms"] = current_group["duration_ms"]
        current_group["segments"].append(seg)
        current_group["duration_ms"] += seg_duration
    
    # Add final group
    if current_group["segments"]:
        groups.append(current_group)
    
    # Set segment index ranges
    for group in groups:
        segs = group["segments"]
        group["start_segment_index"] = segs[0]["segment_index"]
        group["end_segment_index"] = segs[-1]["segment_index"]
    
    logger.info(f"Created {len(groups)} groups from {len(segments)} segments")
    return groups


# ============================================
# AUDIO CONCATENATION
# ============================================

def concat_group_audio(group: Dict, output_dir: str) -> str:
    """
    Concatenate segment audio files into a single group audio file.
    Uses AAC/M4A codec via decode -> concat -> re-encode to avoid artifacts.
    
    Returns: path to concatenated audio file
    """
    group_id = str(uuid.uuid4())
    segment_paths = [seg["audio_path"] for seg in group["segments"] if "audio_path" in seg]
    
    if not segment_paths:
        raise ValueError("No audio paths in group segments")
    
    output_path = os.path.join(output_dir, f"{group_id}.m4a")
    
    # Create concat list file
    list_path = os.path.join(output_dir, f"{group_id}_list.txt")
    with open(list_path, "w") as f:
        for path in segment_paths:
            f.write(f"file '{path}'\n")
    
    # FFmpeg: decode, concat, re-encode to AAC/M4A
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", list_path,
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                output_path
            ],
            capture_output=True,
            check=True,
            timeout=120
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg concat error: {e.stderr}")
        raise
    finally:
        # Cleanup list file
        if os.path.exists(list_path):
            os.remove(list_path)
    
    # Storage cleanup (prod mode)
    if not KEEP_SEGMENT_AUDIO:
        for path in segment_paths:
            if os.path.exists(path):
                os.remove(path)
                logger.debug(f"Deleted segment audio: {path}")
    
    logger.info(f"Concatenated {len(segment_paths)} segments -> {output_path}")
    return output_path


# ============================================
# SUPABASE UPLOAD
# ============================================

def upload_group_audio(local_path: str, chapter_id: str, group_index: int) -> str:
    """
    Upload group audio to Supabase Storage.
    Returns public URL.
    """
    from app.chapters import get_supabase
    supabase = get_supabase()
    
    filename = f"{chapter_id}/group_{group_index}.m4a"
    
    with open(local_path, "rb") as f:
        audio_bytes = f.read()
    
    result = supabase.storage.from_("audio").upload(
        filename,
        audio_bytes,
        {"content-type": "audio/mp4"}
    )
    
    # Get public URL
    public_url = supabase.storage.from_("audio").get_public_url(filename)
    
    # Cleanup local file
    if os.path.exists(local_path):
        os.remove(local_path)
    
    logger.info(f"Uploaded group audio: {public_url}")
    return public_url


def save_groups_to_supabase(
    chapter_id: str,
    build_id: str,  # TTS-First v3.1: Required for linking to chapter_build
    groups: List[Dict],
    paragraph_id_map: Dict[int, str]
) -> List[str]:
    """
    Save audio_groups and tts_segments to Supabase.
    
    Args:
        chapter_id: UUID of chapter
        build_id: UUID of chapter_build (TTS-First v3.1)
        groups: List of group dicts with segments
        paragraph_id_map: Maps segment_index -> paragraph_id
    
    Returns: List of created group IDs
    """
    from app.chapters import get_supabase
    supabase = get_supabase()
    
    group_ids = []
    
    for group in groups:
        # Insert audio_group with build_id
        group_result = supabase.table("audio_groups").insert({
            "chapter_id": chapter_id,
            "build_id": build_id,  # TTS-First v3.1
            "group_index": group["group_index"],
            "audio_url": group["audio_url"],
            "duration_ms": group["duration_ms"],
            "start_time_ms": group["start_time_ms"],
            "start_segment_index": group["start_segment_index"],
            "end_segment_index": group["end_segment_index"]
        }).execute()
        
        group_id = group_result.data[0]["id"]
        group_ids.append(group_id)
        
        # Insert segments for this group
        for seg in group["segments"]:
            para_id = paragraph_id_map.get(seg["segment_index"])
            
            supabase.table("tts_segments").insert({
                "chapter_id": chapter_id,
                "build_id": build_id,  # TTS-First v3.1
                "segment_index": seg["segment_index"],
                "text": seg["text"],
                "text_normalized": seg.get("text_normalized"),  # TTS-First v3.1
                "paragraph_id": para_id,
                "duration_ms": seg.get("duration_ms", 0),
                "group_id": group_id,
                "offset_in_group_ms": seg["offset_in_group_ms"]
            }).execute()
    
    logger.info(f"Saved {len(groups)} groups with segments to Supabase (build_id: {build_id})")
    return group_ids


def update_chapter_audio_version(chapter_id: str, build_id: str = None, version: str = "v2"):
    """
    Set chapter.audio_version after successful processing.
    TTS-First v3.1: Also sets current_build_id and use_paragraph_spans.
    """
    from app.chapters import get_supabase
    supabase = get_supabase()
    
    update_data = {"audio_version": version}
    
    # TTS-First v3.1: Link chapter to build
    if build_id:
        update_data["current_build_id"] = build_id
        update_data["use_paragraph_spans"] = True
    
    supabase.table("chapters").update(update_data).eq("id", chapter_id).execute()
    
    logger.info(f"Updated chapter {chapter_id}: audio_version={version}, build_id={build_id}")


def generate_paragraph_spans(
    chapter_id: str,
    build_id: str,
    paragraphs: List[Dict],
    segments: List[Dict]
) -> List[str]:
    """
    Generate paragraph_spans linking paragraphs to segment ranges.
    
    This creates the mapping that enables O(1) paragraph rendering:
    iOS renders paragraph N as: segments[spans[N].start ... spans[N].end]
    
    Args:
        chapter_id: UUID of chapter
        build_id: UUID of chapter_build
        paragraphs: List of paragraph dicts with 'text' keys
        segments: List of segment dicts with 'text_normalized' keys
        
    Returns: List of created span IDs
    """
    from app.chapters import get_supabase
    supabase = get_supabase()
    
    if not paragraphs or not segments:
        logger.warning(f"No paragraphs or segments to create spans for chapter {chapter_id}")
        return []
    
    span_ids = []
    current_segment = 0
    
    for para_idx, para in enumerate(paragraphs):
        para_text = normalize_text(para.get('text', ''))
        
        # Find which segments belong to this paragraph
        start_segment = current_segment
        matched_text = ''
        
        # Greedily match segments until we've covered this paragraph's text
        while current_segment < len(segments):
            seg_text = segments[current_segment].get('text_normalized', '')
            matched_text = (matched_text + ' ' + seg_text).strip()
            
            current_segment += 1
            
            # Check if we have enough text (allowing for minor differences)
            if len(matched_text) >= len(para_text) * 0.8:
                break
        
        end_segment = current_segment - 1
        
        # Ensure valid range
        if end_segment < start_segment:
            end_segment = start_segment
        if end_segment >= len(segments):
            end_segment = len(segments) - 1
        
        # Create span record
        result = supabase.table("paragraph_spans").insert({
            "chapter_id": chapter_id,
            "build_id": build_id,
            "paragraph_index": para_idx,
            "start_segment_index": start_segment,
            "end_segment_index": end_segment
        }).execute()
        
        if result.data:
            span_ids.append(result.data[0]["id"])
    
    logger.info(f"Created {len(span_ids)} paragraph_spans for chapter {chapter_id}")
    return span_ids

