"""
Marker API integration for PDF to Markdown conversion.
Uses Datalab.to API for high-quality PDF extraction.

This replaces the previous PyMuPDF-based extraction with a more accurate
Markdown output that preserves document structure.
"""
import os
import requests
import time
import json
import re

MARKER_API_URL = "https://www.datalab.to/api/v1/marker"
MARKER_STATUS_URL = "https://www.datalab.to/api/v1/marker/{request_id}"


def get_datalab_api_key() -> str:
    """Get Datalab API key from environment."""
    api_key = os.getenv("DATALAB_API_KEY")
    if not api_key:
        raise RuntimeError("DATALAB_API_KEY must be set")
    return api_key


def extract_pdf_to_markdown(pdf_path: str, max_wait_seconds: int = 300) -> dict:
    """
    Converts PDF to structured Markdown using Marker API.
    
    The Marker API is async - we submit the PDF and poll for results.
    
    Args:
        pdf_path: Path to the PDF file
        max_wait_seconds: Maximum time to wait for processing (default: 5 min)
        
    Returns:
        {
            "markdown": "# Chapter 1\n\nThe text...",
            "success": True,
            "pages": 119,
            "request_id": "...",
            "images": {...}  # Optional, if images were extracted
        }
    """
    api_key = get_datalab_api_key()
    
    headers = {
        "X-Api-Key": api_key
    }
    
    print(f"[MARKER] Submitting PDF for extraction: {pdf_path}")
    
    # Step 1: Submit PDF for processing
    with open(pdf_path, "rb") as f:
        response = requests.post(
            MARKER_API_URL,
            headers=headers,
            files={"file": (os.path.basename(pdf_path), f, "application/pdf")},
            data={
                "output_format": "markdown",
                "force_ocr": "false",  # Only use OCR if needed
                "paginate_output": "false"  # Get continuous markdown
            }
        )
    
    if response.status_code != 200:
        error_msg = f"Marker API submission error: {response.status_code} - {response.text}"
        print(f"[MARKER] ❌ {error_msg}")
        raise Exception(error_msg)
    
    result = response.json()
    
    # Check if result is immediate (small PDFs) or async
    if result.get("success") and result.get("markdown"):
        # Immediate result
        print(f"[MARKER] ✅ Immediate result received ({result.get('pages', '?')} pages)")
        return result
    
    # Async processing - need to poll
    request_id = result.get("request_id")
    if not request_id:
        raise Exception(f"No request_id in Marker response: {result}")
    
    print(f"[MARKER] Async processing started, request_id: {request_id}")
    
    # Step 2: Poll for results
    status_url = MARKER_STATUS_URL.format(request_id=request_id)
    start_time = time.time()
    poll_interval = 2  # Start with 2 seconds
    
    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            raise Exception(f"Marker API timeout after {max_wait_seconds}s")
        
        time.sleep(poll_interval)
        
        status_response = requests.get(status_url, headers=headers)
        
        if status_response.status_code != 200:
            print(f"[MARKER] ⚠️ Status check failed: {status_response.status_code}")
            continue
        
        status_data = status_response.json()
        status = status_data.get("status", "unknown")
        
        if status == "complete":
            print(f"[MARKER] ✅ Processing complete ({elapsed:.1f}s)")
            return status_data
        
        if status == "failed":
            error = status_data.get("error", "Unknown error")
            raise Exception(f"Marker processing failed: {error}")
        
        # Still processing
        print(f"[MARKER] ⏳ Status: {status} ({elapsed:.1f}s elapsed)")
        
        # Increase poll interval gradually (max 10s)
        poll_interval = min(poll_interval * 1.5, 10)


def parse_chapters_from_markdown(markdown: str) -> list:
    """
    Robust chapter detection that handles Table of Contents entries.
    
    Strategy:
    1. Find ALL "Chapter X - Title" patterns in markdown
    2. For each, calculate content length until next chapter
    3. Only keep chapters with substantial content (>200 chars)
    4. Sort by chapter number (extracted from "Chapter X")
    5. Deduplicate: if same chapter appears twice, keep the one with content
    6. Re-index sequentially
    
    This handles the case where:
    - ToC has "Chapter 1 - Salaam" (0 content)
    - Real chapter has "Chapter 1 - Salaam" (10000+ content)
    
    Returns:
        [
            {"index": 1, "title": "Salaam", "start_line": 50, "end_line": 150, ...},
            {"index": 2, "title": "Breath Is Life", "start_line": 151, ...},
            ...
        ]
    """
    lines = markdown.split("\n")
    candidates = []
    
    # Pattern: "Chapter 1 - Salaam" or "## Chapter 1 - Salaam"
    # Captures chapter number (group 1) and title (group 2)
    chapter_pattern = re.compile(
        r'^#{0,2}\s*Chapter\s+(\d+)\s*[-–]\s*(.+)\s*$',
        re.IGNORECASE
    )
    
    # Also match "# Chapter 1 - Salaam" with single #
    for line_num, line in enumerate(lines):
        stripped = line.strip()
        match = chapter_pattern.match(stripped)
        if match:
            chapter_num = int(match.group(1))
            title = match.group(2).strip()
            candidates.append({
                "chapter_num": chapter_num,
                "title": title,
                "start_line": line_num,
                "header_line": stripped
            })
    
    print(f"[MARKER] Found {len(candidates)} chapter candidates in markdown")
    
    # Calculate content for each candidate (until next candidate)
    for i, ch in enumerate(candidates):
        if i + 1 < len(candidates):
            end_line = candidates[i + 1]["start_line"] - 1
        else:
            end_line = len(lines) - 1
        
        ch["end_line"] = end_line
        
        # Content is everything between this header and next chapter
        content_lines = lines[ch["start_line"] + 1:end_line + 1]
        content_text = "\n".join(content_lines).strip()
        ch["content_length"] = len(content_text)
    
    # Filter: keep only chapters with real content (not ToC entries)
    MIN_CONTENT = 200
    real_chapters = []
    for ch in candidates:
        if ch["content_length"] >= MIN_CONTENT:
            print(f"[MARKER] ✅ Real chapter {ch['chapter_num']}: {ch['title']} ({ch['content_length']} chars)")
            real_chapters.append(ch)
        else:
            print(f"[MARKER] ⏭️ ToC entry skipped: Chapter {ch['chapter_num']} - {ch['title']} ({ch['content_length']} chars)")
    
    # Sort by chapter number to ensure correct order
    real_chapters.sort(key=lambda x: x["chapter_num"])
    
    # Deduplicate: if same chapter_num appears multiple times, keep the one with most content
    seen = {}
    for ch in real_chapters:
        num = ch["chapter_num"]
        if num not in seen:
            seen[num] = ch
        elif ch["content_length"] > seen[num]["content_length"]:
            print(f"[MARKER] 🔄 Replacing chapter {num} with better content version")
            seen[num] = ch
    
    # Sort final chapters by chapter number
    final_chapters = sorted(seen.values(), key=lambda x: x["chapter_num"])
    
    # Re-index sequentially (1, 2, 3, ...)
    for i, ch in enumerate(final_chapters):
        ch["index"] = i + 1
    
    print(f"[MARKER] Final result: {len(final_chapters)} chapters")
    for ch in final_chapters[:5]:
        print(f"[MARKER]   {ch['index']}. Chapter {ch['chapter_num']} - {ch['title']}")
    if len(final_chapters) > 5:
        print(f"[MARKER]   ... and {len(final_chapters) - 5} more")
    
    # If no chapters found, treat entire text as one chapter
    if not final_chapters:
        print("[MARKER] ⚠️ No chapters detected, treating as single chapter")
        final_chapters = [{
            "index": 1,
            "chapter_num": 1,
            "title": "Full Text",
            "start_line": 0,
            "end_line": len(lines) - 1,
            "header_line": None,
            "content_length": len(markdown)
        }]
    
    return final_chapters


def extract_chapter_text(markdown: str, chapter: dict) -> str:
    """
    Extract the text content for a specific chapter.
    
    Args:
        markdown: Full markdown text
        chapter: Chapter dict with start_line and end_line
        
    Returns:
        The chapter's text content
    """
    lines = markdown.split("\n")
    start = chapter.get("start_line", 0)
    end = chapter.get("end_line", len(lines) - 1)
    
    # Skip the header line itself
    content_lines = lines[start + 1:end + 1]
    return "\n".join(content_lines)
