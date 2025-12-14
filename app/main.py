from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
import uuid
import os
import json
from typing import Optional

from app.extractor import extract_raw_pages
from app.cleaner import clean_page_text
from app.chapters import extract_chapters_from_text, write_chapters_to_supabase, create_book_in_supabase
from app.metadata import extract_book_metadata


app = FastAPI()

TEMP_DIR = "/tmp/honora"
os.makedirs(TEMP_DIR, exist_ok=True)

# -----------------------------------------------------------
# 1) PDF → RAW JSON extractor
# -----------------------------------------------------------
@app.post("/extract_pdf")
async def extract_pdf(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    pdf_path = f"{TEMP_DIR}/{file_id}.pdf"
    json_path = f"{TEMP_DIR}/{file_id}.json"

    with open(pdf_path, "wb") as f:
        f.write(await file.read())

    pages = extract_raw_pages(pdf_path)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)

    return {
        "status": "ok",
        "file_id": file_id,
        "download_url": f"/download/{file_id}"
    }

# -----------------------------------------------------------
# 2) Download RAW extracted JSON
# -----------------------------------------------------------
@app.get("/download/{file_id}")
def download_json(file_id: str):
    json_path = f"{TEMP_DIR}/{file_id}.json"

    if not os.path.isfile(json_path):
        return JSONResponse({"error": "Extracted JSON file not found"}, status_code=404)

    return FileResponse(
        path=json_path,
        media_type="application/json",
        filename=f"{file_id}.json"
    )

# -----------------------------------------------------------
# 3) Clean a single page (LLM)
# -----------------------------------------------------------
@app.post("/clean_page")
async def clean_page(payload: dict):
    if "items" not in payload:
        return JSONResponse({"error": "Missing 'items' in request body"}, status_code=400)

    cleaned = clean_page_text(payload["items"])
    return cleaned

# -----------------------------------------------------------
# 4) NEW: Clean an entire book by file_id (server-side)
# -----------------------------------------------------------
@app.post("/clean_book")
async def clean_book(payload: dict):
    """
    payload format (Option 1 - file_id mode):
    {
      "file_id": "uuid-from-extract_pdf",
      "start_page": 1,            # optional (1-indexed)
      "end_page": 999,            # optional (inclusive, 1-indexed)
      "save_full_text": true      # optional (default true)
    }

    payload format (Option 2 - direct items mode):
    {
      "book_id": "optional-identifier",
      "language": "optional-language-hint",
      "items": [{"page": 1, "items": [{"text": "...", "bbox": [...]}]}, ...],
      "save_full_text": true      # optional (default true)
    }
    """

    file_id = payload.get("file_id")
    direct_items = payload.get("items")

    # Validate: must provide either file_id OR items, not both, not neither
    if file_id and direct_items:
        return JSONResponse({"error": "Provide either 'file_id' or 'items', not both"}, status_code=400)

    if not file_id and not direct_items:
        return JSONResponse({"error": "Missing 'file_id' or 'items' in request body"}, status_code=400)

    start_page = payload.get("start_page", 1)
    end_page = payload.get("end_page", None)
    save_full_text = payload.get("save_full_text", True)

    # Load pages from either source
    if file_id:
        raw_json_path = f"{TEMP_DIR}/{file_id}.json"
        if not os.path.isfile(raw_json_path):
            return JSONResponse({"error": f"Raw JSON not found for file_id={file_id}"}, status_code=404)
        with open(raw_json_path, "r", encoding="utf-8") as f:
            pages = json.load(f)
    else:
        # Direct items mode
        if not isinstance(direct_items, list):
            return JSONResponse({"error": "'items' must be an array"}, status_code=400)
        pages = direct_items

    # Validate page range
    if not isinstance(start_page, int) or start_page < 1:
        return JSONResponse({"error": "'start_page' must be an integer >= 1"}, status_code=400)

    if end_page is not None:
        if not isinstance(end_page, int) or end_page < start_page:
            return JSONResponse({"error": "'end_page' must be an integer >= start_page"}, status_code=400)

    cleaned_pages = []
    removed_log = []
    uncertain_log = []

    # Iterate pages (each element has: {"page": n, "items": [...]})
    for page_obj in pages:
        page_num = page_obj.get("page")
        items = page_obj.get("items", [])

        # skip outside range
        if page_num is None:
            continue
        if page_num < start_page:
            continue
        if end_page is not None and page_num > end_page:
            continue

        result = clean_page_text(items)

        cleaned_text = result.get("cleaned_text", "")
        removed = result.get("removed", [])
        uncertain = result.get("uncertain", [])

        cleaned_pages.append({
            "page": page_num,
            "cleaned_text": cleaned_text
        })

        if removed:
            removed_log.append({
                "page": page_num,
                "removed": removed
            })

        if uncertain:
            uncertain_log.append({
                "page": page_num,
                "uncertain": uncertain
            })

    # Build full text (optional)
    full_text = None
    if save_full_text:
        # Keep a clean audiobook-ish flow; double newline between pages.
        full_text = "\n\n".join([p["cleaned_text"] for p in cleaned_pages if p["cleaned_text"].strip()])

    # Save cleaned result server-side
    cleaned_id = str(uuid.uuid4())
    cleaned_path = f"{TEMP_DIR}/{cleaned_id}.cleaned.json"

    output = {
        "status": "ok",
        "source_file_id": file_id,
        "cleaned_file_id": cleaned_id,
        "page_range": {"start_page": start_page, "end_page": end_page},
        "pages_cleaned": len(cleaned_pages),
        "pages": cleaned_pages,
        "removed_log": removed_log,
        "uncertain_log": uncertain_log,
        "full_text": full_text
    }

    with open(cleaned_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return {
        "status": "ok",
        "source_file_id": file_id,
        "cleaned_file_id": cleaned_id,
        "download_url": f"/download_cleaned/{cleaned_id}",
        "pages_cleaned": len(cleaned_pages)
    }

# -----------------------------------------------------------
# 5) Download CLEANED result JSON
# -----------------------------------------------------------
@app.get("/download_cleaned/{cleaned_file_id}")
def download_cleaned(cleaned_file_id: str):
    cleaned_path = f"{TEMP_DIR}/{cleaned_file_id}.cleaned.json"

    if not os.path.isfile(cleaned_path):
        return JSONResponse({"error": "Cleaned JSON file not found"}, status_code=404)

    return FileResponse(
        path=cleaned_path,
        media_type="application/json",
        filename=f"{cleaned_file_id}.cleaned.json"
    )

# -----------------------------------------------------------
# 6) Extract chapters from cleaned text
# -----------------------------------------------------------
@app.post("/extract_chapters")
async def extract_chapters(payload: dict):
    book_id = payload.get("book_id")
    cleaned_file_id = payload.get("cleaned_file_id")

    if not book_id or not cleaned_file_id:
        return JSONResponse(
            {"error": "Missing book_id or cleaned_file_id"},
            status_code=400
        )

    cleaned_path = f"{TEMP_DIR}/{cleaned_file_id}.cleaned.json"
    if not os.path.isfile(cleaned_path):
        return JSONResponse(
            {"error": "Cleaned file not found"},
            status_code=404
        )

    with open(cleaned_path, "r", encoding="utf-8") as f:
        cleaned = json.load(f)

    full_text = cleaned.get("full_text")
    if not full_text:
        return JSONResponse(
            {"error": "No full_text in cleaned file"},
            status_code=400
        )

    chapters = extract_chapters_from_text(full_text)
    write_chapters_to_supabase(book_id, chapters)

    return {
        "status": "ok",
        "chapters_created": len(chapters)
    }

# -----------------------------------------------------------
# 7) Create book entry with auto-extracted metadata
# -----------------------------------------------------------
@app.post("/create_book")
async def create_book(payload: dict):
    """
    Extracts title and author from the PDF and creates a book in Supabase.
    
    payload:
    {
      "file_id": "uuid-from-extract_pdf"
    }
    
    Returns:
    {
      "status": "ok",
      "book_id": "supabase-uuid",
      "title": "...",
      "author": "..."
    }
    """
    file_id = payload.get("file_id")
    
    if not file_id:
        return JSONResponse({"error": "Missing 'file_id' in request body"}, status_code=400)
    
    # Load raw extracted JSON
    raw_json_path = f"{TEMP_DIR}/{file_id}.json"
    if not os.path.isfile(raw_json_path):
        return JSONResponse({"error": f"Raw JSON not found for file_id={file_id}"}, status_code=404)
    
    with open(raw_json_path, "r", encoding="utf-8") as f:
        pages = json.load(f)
    
    # Get text from first 3 pages for metadata extraction
    first_pages_text = ""
    for page_obj in pages[:3]:
        items = page_obj.get("items", [])
        page_text = " ".join([item["text"] for item in items])
        first_pages_text += page_text + "\n\n"
    
    # Extract metadata using GPT
    metadata = extract_book_metadata(first_pages_text)
    title = metadata.get("title", "Unknown")
    author = metadata.get("author", "Unknown")
    language = metadata.get("language", "en")
    
    # Create book in Supabase
    book_id = create_book_in_supabase(title, author, language)
    
    return {
        "status": "ok",
        "book_id": book_id,
        "title": title,
        "author": author,
        "language": language
    }
