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
    Parse chapter boundaries from Markdown headers.
    
    Marker API preserves headers as:
    - # for main titles
    - ## for chapters
    - ### for sections
    
    Filters out navigation pages like "Start Reading", "Page Index", etc.
    
    Returns:
        [
            {"index": 1, "title": "Introduction", "start_line": 0, "end_line": 45},
            {"index": 2, "title": "The Hermetic Philosophy", "start_line": 46, "end_line": 120},
            ...
        ]
    """
    import re
    
    lines = markdown.split("\n")
    chapters = []
    current_chapter = None
    
    # DEBUG: Log first 50 lines to see markdown structure
    print("[MARKER] DEBUG: First 50 lines of markdown:")
    for i, line in enumerate(lines[:50]):
        if line.strip():
            print(f"[MARKER]   Line {i}: {line[:80]}{'...' if len(line) > 80 else ''}")
    
    # Navigation pages to skip (common on sacred-texts.com scraped PDFs)
    navigation_patterns = [
        r'^start\s*reading$',
        r'^page\s*index$',
        r'^title\s*page$',
        r'^table\s*of\s*contents$',
        r'^contents$',
        r'^index$',
        r'^errata$',
        r'^next$',
        r'^previous$',
        r'^prev$',
        r'^home$',
        r'^\s*$',  # Empty titles
    ]
    navigation_regex = re.compile('|'.join(navigation_patterns), re.IGNORECASE)
    
    # Pattern for chapter headers (## or # followed by Chapter/Roman numerals/English words)
    # English number words for matching
    number_words = r'(?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve|Thirteen|Fourteen|Fifteen|Sixteen|Seventeen|Eighteen|Nineteen|Twenty(?:-One|-Two|-Three|-Four|-Five|-Six|-Seven|-Eight|-Nine)?|Thirty)'
    
    chapter_patterns = [
        # PRIORITY 1: HONORA_CHAPTER_START markers from HonoraWebScraper (most reliable!)
        # Format: <!-- HONORA_CHAPTER_START: 1 | Chapter 1 - Salaam -->
        r'HONORA_CHAPTER_START:\s*(\d+)\s*\|\s*(.*?)\s*(?:-->|$)',
        # PRIORITY 2: "Chapter 1 - Salaam" format (HonoraWebScraper with numbers)
        r'^#{0,2}\s*Chapter\s+(\d+)\s*[-–]\s*(.+)',
        # "Chapter One - Salaam" (HonoraWebScraper format with English words)
        rf'^#{{0,2}}\s*Chapter\s+{number_words}\s*[-–]\s*(.*)',
        # "Chapter One" alone (no subtitle)
        rf'^#{{0,2}}\s*Chapter\s+{number_words}\s*$',
        # "Chapter 1: Title" or "Chapter I. Title"
        r'^#{1,2}\s+Chapter\s+(\d+|[IVXLCDM]+)[:\.\s\-–]*(.*)',
        # "I. The Philosophy" (Roman numeral at start)
        r'^#{1,2}\s+([IVXLCDM]+)[:\.\s]+(.*)',
        # "Introduction", "Preface", etc.
        r'^#{1,2}\s+(Introduction|Preface|Prologue|Epilogue|Conclusion)(.*)',
    ]
    
    for line_num, line in enumerate(lines):
        # Skip Table of Contents section
        # ToC entries look like chapters but have no real content after them
        # Detect ToC header and skip until we see actual chapter content
        if re.match(r'^#{1,2}\s*Table\s+of\s+Contents\s*$', line, re.IGNORECASE):
            print(f"[MARKER] 📚 Found Table of Contents at line {line_num}, will skip ToC entries")
            # Mark that we're in ToC section - entries here should be skipped
            # We detect end of ToC by finding a chapter header followed by substantial content
            continue
        
        # Skip lines that are just ToC entries (short lines with chapter references but no following content)
        # ToC entries typically have very little text on the same line
        # Real chapters have content paragraphs following the header
        
        for pattern in chapter_patterns:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                # Extract title
                groups = match.groups()
                if len(groups) >= 2:
                    title = groups[1].strip() if groups[1].strip() else groups[0]
                else:
                    title = groups[0].strip()
                
                # Clean title
                title = title.strip(".:- ")
                
                # Skip navigation pages
                if navigation_regex.match(title):
                    print(f"[MARKER] ⏭️ Skipping navigation chapter: '{title}'")
                    continue
                
                # Skip chapters with very short content hints (likely navigation)
                if not title:
                    continue
                
                # Close previous chapter
                if current_chapter:
                    current_chapter["end_line"] = line_num - 1
                    chapters.append(current_chapter)
                
                current_chapter = {
                    "index": len(chapters) + 1,
                    "title": title if title else f"Chapter {len(chapters) + 1}",
                    "start_line": line_num,
                    "end_line": None,
                    "header_line": line.strip()
                }
                break
    
    # Close last chapter
    if current_chapter:
        current_chapter["end_line"] = len(lines) - 1
        chapters.append(current_chapter)
    
    # If no chapters found, treat entire text as one chapter
    if not chapters:
        chapters.append({
            "index": 1,
            "title": "Full Text",
            "start_line": 0,
            "end_line": len(lines) - 1,
            "header_line": None
        })
    
    # POST-PROCESSING: Filter out Table of Contents entries
    # ToC entries have very little content between headers (< 100 chars typically)
    # Real chapters have substantial content (> 500 chars typically)
    MIN_CHAPTER_CONTENT = 200  # Minimum characters for a real chapter
    
    filtered_chapters = []
    for ch in chapters:
        start = ch["start_line"]
        end = ch["end_line"] if ch["end_line"] else len(lines) - 1
        
        # Calculate content length (excluding the header line itself)
        content_lines = lines[start + 1:end + 1]
        content_text = "\n".join(content_lines).strip()
        content_length = len(content_text)
        
        if content_length < MIN_CHAPTER_CONTENT:
            print(f"[MARKER] ⏭️ Skipping ToC/short entry: '{ch['title']}' ({content_length} chars)")
            continue
        
        filtered_chapters.append(ch)
        print(f"[MARKER] ✅ Chapter: '{ch['title']}' ({content_length} chars)")
    
    # Use filtered chapters if we found real chapters
    if filtered_chapters:
        chapters = filtered_chapters
    
    # Re-index chapters sequentially
    for i, ch in enumerate(chapters):
        ch["index"] = i + 1
    
    print(f"[MARKER] Found {len(chapters)} chapters in Markdown (after filtering)")
    for ch in chapters[:5]:  # Log first 5
        print(f"[MARKER]   Chapter {ch['index']}: {ch['title']}")
    if len(chapters) > 5:
        print(f"[MARKER]   ... and {len(chapters) - 5} more")
    
    return chapters


def extract_chapter_text(markdown: str, chapter: dict) -> str:
    """
    Extract the text content for a specific chapter.
    
    Args:
        markdown: Full markdown text
        chapter: Chapter dict with start_line and end_line
        
    Returns:
        Chapter text as string
    """
    lines = markdown.split("\n")
    start = chapter.get("start_line", 0)
    end = chapter.get("end_line", len(lines) - 1)
    
    chapter_lines = lines[start:end + 1]
    return "\n".join(chapter_lines)
