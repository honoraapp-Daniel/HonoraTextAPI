from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html
import uuid
import os
import json
from typing import Optional

from app.extractor import extract_raw_pages
from app.cleaner import clean_page_text
from app.chapters import (
    extract_chapters_from_text, 
    extract_chapters_smart,
    write_chapters_to_supabase,
    write_stories_to_supabase,
    create_book_in_supabase,
    chunk_chapter_text,
    write_sections_to_supabase,
    get_chapters_for_book,
    split_into_paragraphs_gpt,
    write_paragraphs_to_supabase
)
from app.metadata import extract_book_metadata


# Custom Swagger UI with Honora branding
app = FastAPI(
    title="Honora Book API",
    description="""
## 🔥 Honora Audiobook Processing Pipeline

Transform PDFs into structured audiobook content.

### Pipeline Flow:
1. **Extract PDF** → Upload and extract text
2. **Create Book** → Auto-detect title, author, language
3. **Clean Book** → AI-powered text cleaning for TTS
4. **Extract Chapters** → Split into chapters for Supabase

---
*Powered by Honora*
    """,
    version="1.0.0",
    docs_url=None,  # Disable default docs again
    redoc_url=None,  # Disable redoc
)

from fastapi.staticfiles import StaticFiles
from pathlib import Path

# Mount static files for custom CSS
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


# Custom Swagger UI - Clean dark theme
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    custom_css = """
    <style>
        /* Clean dark theme with good readability */
        :root {
            --bg-primary: #1a1a1a;
            --bg-secondary: #2d2d2d;
            --bg-tertiary: #3d3d3d;
            --text-primary: #ffffff;
            --text-secondary: #b0b0b0;
            --accent-green: #10b981;
            --accent-blue: #3b82f6;
            --accent-orange: #f59e0b;
            --border-color: #404040;
        }
        
        body { 
            background-color: var(--bg-primary) !important; 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
        }
        
        .swagger-ui { background-color: var(--bg-primary) !important; }
        
        /* Header */
        .swagger-ui .topbar { 
            background-color: var(--bg-secondary) !important; 
            border-bottom: 1px solid var(--border-color) !important;
            padding: 10px 0 !important;
        }
        
        /* Info section */
        .swagger-ui .info .title { 
            color: var(--text-primary) !important; 
            font-size: 2rem !important;
            font-weight: 600 !important;
        }
        .swagger-ui .info .description, 
        .swagger-ui .info .description p { 
            color: var(--text-secondary) !important; 
            font-size: 1rem !important;
            line-height: 1.6 !important;
        }
        .swagger-ui .info .description h2, 
        .swagger-ui .info .description h3 { 
            color: var(--text-primary) !important; 
            margin-top: 1.5rem !important;
        }
        
        /* Operation blocks */
        .swagger-ui .opblock { 
            background: var(--bg-secondary) !important; 
            border: 1px solid var(--border-color) !important; 
            border-radius: 8px !important;
            margin-bottom: 12px !important;
        }
        .swagger-ui .opblock.opblock-post .opblock-summary-method { 
            background: var(--accent-green) !important; 
            color: white !important;
            font-weight: 600 !important;
        }
        .swagger-ui .opblock.opblock-get .opblock-summary-method { 
            background: var(--accent-blue) !important; 
            color: white !important;
            font-weight: 600 !important;
        }
        .swagger-ui .opblock.opblock-delete .opblock-summary-method { 
            background: #ef4444 !important; 
        }
        .swagger-ui .opblock .opblock-summary-path { 
            color: var(--text-primary) !important; 
            font-size: 1rem !important;
            font-weight: 500 !important;
        }
        .swagger-ui .opblock .opblock-summary-description { 
            color: var(--text-secondary) !important; 
        }
        
        /* Expanded block content */
        .swagger-ui .opblock-body { background: var(--bg-primary) !important; }
        .swagger-ui .opblock-description-wrapper { 
            background: var(--bg-secondary) !important; 
            color: var(--text-secondary) !important;
            padding: 15px !important;
        }
        .swagger-ui .opblock-section-header { 
            background: var(--bg-tertiary) !important; 
            border-bottom: 1px solid var(--border-color) !important;
        }
        .swagger-ui .opblock-section-header h4 { 
            color: var(--text-primary) !important; 
            font-size: 0.9rem !important;
        }
        
        /* Parameters and responses */
        .swagger-ui .parameters-col_description,
        .swagger-ui .parameter__name { 
            color: var(--text-primary) !important; 
        }
        .swagger-ui .parameter__type { 
            color: var(--accent-blue) !important; 
        }
        .swagger-ui table tbody tr td { 
            color: var(--text-secondary) !important; 
            border-color: var(--border-color) !important;
        }
        .swagger-ui .response-col_status { 
            color: var(--accent-green) !important; 
            font-weight: 600 !important;
        }
        .swagger-ui .responses-inner { background: var(--bg-primary) !important; }
        
        /* Execute button */
        .swagger-ui .btn.execute { 
            background-color: var(--accent-blue) !important; 
            border-color: var(--accent-blue) !important; 
            border-radius: 6px !important;
            font-weight: 600 !important;
        }
        .swagger-ui .btn.execute:hover { 
            background-color: #2563eb !important; 
        }
        
        /* Models section */
        .swagger-ui section.models { 
            border: 1px solid var(--border-color) !important; 
            background: var(--bg-secondary) !important; 
            border-radius: 8px !important;
        }
        .swagger-ui section.models h4 { color: var(--text-primary) !important; }
        .swagger-ui .model-box { background: var(--bg-primary) !important; }
        .swagger-ui .model { color: var(--text-secondary) !important; }
        
        /* Filter input */
        .swagger-ui .filter-container input { 
            background: var(--bg-secondary) !important; 
            border: 1px solid var(--border-color) !important; 
            color: var(--text-primary) !important;
            border-radius: 6px !important;
            padding: 8px 12px !important;
        }
        
        /* Code blocks */
        .swagger-ui .highlight-code { background: var(--bg-tertiary) !important; }
        .swagger-ui pre { 
            background: var(--bg-tertiary) !important; 
            color: var(--text-primary) !important;
            border-radius: 6px !important;
        }
        
        /* Links */
        .swagger-ui a { color: var(--accent-blue) !important; }
    </style>
    """
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Honora Book API</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
        REPLACE_CSS
    </head>
    <body>
        <div id="swagger-ui"></div>
        <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
        <script>
            SwaggerUIBundle({
                url: '/openapi.json',
                dom_id: '#swagger-ui',
                presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
                layout: "BaseLayout",
                docExpansion: "list",
                filter: true,
                tryItOutEnabled: true,
                syntaxHighlight: { theme: "agate" }
            });
        </script>
    </body>
    </html>
    """.replace("REPLACE_CSS", custom_css)
    
    return HTMLResponse(content=html)




# OpenAPI JSON endpoint
@app.get("/openapi.json", include_in_schema=False)
async def get_openapi():
    return app.openapi()

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
    
    # Create book in Supabase with full metadata
    book_id = create_book_in_supabase(metadata)
    
    return {
        "status": "ok",
        "book_id": book_id,
        "title": metadata.get("title"),
        "author": metadata.get("author"),
        "language": metadata.get("language"),
        "synopsis": metadata.get("synopsis"),
        "category": metadata.get("category")
    }

# -----------------------------------------------------------
# 8) Chunk chapters into sections for TTS
# -----------------------------------------------------------
@app.post("/chunk_chapters")
async def chunk_chapters(payload: dict):
    """
    Chunks all chapters for a book into max 250-character sections.
    
    payload:
    {
      "book_id": "uuid-of-book",
      "max_chars": 250  # optional, default 250
    }
    
    Returns:
    {
      "status": "ok",
      "book_id": "...",
      "chapters_processed": 5,
      "total_sections_created": 127,
      "details": [
        {"chapter_id": "...", "chapter_index": 1, "sections": 25},
        ...
      ]
    }
    """
    book_id = payload.get("book_id")
    max_chars = payload.get("max_chars", 250)
    
    if not book_id:
        return JSONResponse({"error": "Missing 'book_id' in request body"}, status_code=400)
    
    if not isinstance(max_chars, int) or max_chars < 50 or max_chars > 500:
        return JSONResponse({"error": "'max_chars' must be an integer between 50 and 500"}, status_code=400)
    
    # Fetch all chapters for this book
    chapters = get_chapters_for_book(book_id)
    
    if not chapters:
        return JSONResponse({"error": f"No chapters found for book_id={book_id}"}, status_code=404)
    
    details = []
    total_sections = 0
    
    for chapter in chapters:
        chapter_id = chapter["id"]
        chapter_text = chapter.get("text", "")
        chapter_index = chapter.get("chapter_index", 0)
        
        if not chapter_text:
            details.append({
                "chapter_id": chapter_id,
                "chapter_index": chapter_index,
                "sections": 0,
                "note": "No text content"
            })
            continue
        
        # Chunk the chapter text
        sections = chunk_chapter_text(chapter_text, max_chars)
        
        # Write sections to Supabase
        write_sections_to_supabase(chapter_id, sections)
        
        details.append({
            "chapter_id": chapter_id,
            "chapter_index": chapter_index,
            "sections": len(sections)
        })
        total_sections += len(sections)
    
    return {
        "status": "ok",
        "book_id": book_id,
        "chapters_processed": len(chapters),
        "total_sections_created": total_sections,
        "details": details
    }

# -----------------------------------------------------------
# 9) Create display paragraphs for app UI
# -----------------------------------------------------------
@app.post("/create_paragraphs")
async def create_paragraphs(payload: dict):
    """
    Creates natural paragraphs for app display (time-synchronized transcripts).
    Uses GPT to identify semantic breaks in text.
    
    payload:
    {
      "book_id": "uuid-of-book"
    }
    
    Returns:
    {
      "status": "ok",
      "book_id": "...",
      "chapters_processed": 5,
      "total_paragraphs_created": 89,
      "details": [
        {"chapter_id": "...", "chapter_index": 1, "paragraphs": 18},
        ...
      ]
    }
    """
    book_id = payload.get("book_id")
    
    if not book_id:
        return JSONResponse({"error": "Missing 'book_id' in request body"}, status_code=400)
    
    # Fetch all chapters for this book
    chapters = get_chapters_for_book(book_id)
    
    if not chapters:
        return JSONResponse({"error": f"No chapters found for book_id={book_id}"}, status_code=404)
    
    details = []
    total_paragraphs = 0
    
    for chapter in chapters:
        chapter_id = chapter["id"]
        chapter_text = chapter.get("text", "")
        chapter_index = chapter.get("chapter_index", 0)
        
        if not chapter_text:
            details.append({
                "chapter_id": chapter_id,
                "chapter_index": chapter_index,
                "paragraphs": 0,
                "note": "No text content"
            })
            continue
        
        # Use GPT to split into natural paragraphs
        paragraphs = split_into_paragraphs_gpt(chapter_text)
        
        # Write paragraphs to Supabase
        write_paragraphs_to_supabase(chapter_id, paragraphs)
        
        details.append({
            "chapter_id": chapter_id,
            "chapter_index": chapter_index,
            "paragraphs": len(paragraphs)
        })
        total_paragraphs += len(paragraphs)
    
    return {
        "status": "ok",
        "book_id": book_id,
        "chapters_processed": len(chapters),
        "total_paragraphs_created": total_paragraphs,
        "details": details
    }

# -----------------------------------------------------------
# 10) Full Pipeline: PDF → Supabase (ready for TTS)
# -----------------------------------------------------------
@app.post("/process_book")
async def process_book(file: UploadFile = File(...)):
    """
    Full automated pipeline: Upload PDF → Get TTS-ready data in Supabase.
    
    Steps:
    1. Extract PDF text
    2. Create book entry with auto-detected metadata
    3. Clean text for TTS (GPT)
    4. Extract chapters → Supabase
    5. Chunk chapters into sections (250 chars for TTS)
    6. Create paragraphs (natural breaks for app display)
    
    Returns book_id and summary when ready for TTS processing.
    """
    import logging
    logger = logging.getLogger("honora.pipeline")
    
    result = {
        "status": "processing",
        "steps_completed": [],
        "errors": []
    }
    
    try:
        # ===== STEP 1: Extract PDF =====
        logger.info("Step 1: Extracting PDF...")
        file_id = str(uuid.uuid4())
        pdf_path = f"{TEMP_DIR}/{file_id}.pdf"
        json_path = f"{TEMP_DIR}/{file_id}.json"
        
        with open(pdf_path, "wb") as f:
            f.write(await file.read())
        
        pages = extract_raw_pages(pdf_path)
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False, indent=2)
        
        result["steps_completed"].append("extract_pdf")
        result["file_id"] = file_id
        
        # ===== STEP 2: Create Book =====
        logger.info("Step 2: Creating book entry...")
        first_pages_text = ""
        for page_obj in pages[:3]:
            items = page_obj.get("items", [])
            page_text = " ".join([item["text"] for item in items])
            first_pages_text += page_text + "\n\n"
        
        metadata = extract_book_metadata(first_pages_text)
        
        from app.chapters import create_book_in_supabase
        book_id = create_book_in_supabase(metadata)
        
        result["steps_completed"].append("create_book")
        result["book_id"] = book_id
        result["title"] = metadata.get("title")
        result["author"] = metadata.get("author")
        result["language"] = metadata.get("language")
        result["synopsis"] = metadata.get("synopsis")
        result["category"] = metadata.get("category")
        
        # ===== STEP 2.5: Generate Cover Art =====
        logger.info("Step 2.5: Generating cover art...")
        print(f"[PIPELINE] Step 2.5: Generating cover art with DALL-E...")
        try:
            from app.cover_art import generate_cover_image, update_book_cover_url
            metadata["book_id"] = book_id
            cover_urls = generate_cover_image(metadata)
            update_book_cover_url(book_id, cover_urls)
            result["cover_art_url"] = cover_urls.get("cover_art_url")
            result["cover_art_url_2x3"] = cover_urls.get("cover_art_url_2x3")
            result["steps_completed"].append("generate_cover")
            print(f"[PIPELINE] Step 2.5 complete: Cover art generated (1:1 and 2:3)")
        except Exception as cover_error:
            print(f"[PIPELINE] ⚠️ Cover art failed (continuing): {str(cover_error)}")
            result["cover_art_error"] = str(cover_error)
        
        # ===== STEP 3: Clean Book =====
        logger.info("Step 3: Cleaning text for TTS...")
        print(f"[PIPELINE] Step 3: Cleaning {len(pages)} pages with GPT...")
        cleaned_pages = []
        
        total_pages = len(pages)
        result["total_pages"] = total_pages
        
        for i, page_obj in enumerate(pages):
            items = page_obj.get("items", [])
            if items:
                print(f"[PIPELINE] Cleaning page {i+1}/{total_pages}...")
                try:
                    cleaned = clean_page_text(items)
                    cleaned_pages.append({
                        "page": page_obj.get("page"),
                        "cleaned_text": cleaned.get("cleaned_text", "")
                    })
                except Exception as e:
                    print(f"[PIPELINE] ⚠️ Warning: Failed to clean page {i+1}: {str(e)}")
                    print(f"[PIPELINE] Falling back to raw text for page {i+1}")
                    raw_text = " ".join([item.get("text", "") for item in items])
                    cleaned_pages.append({
                        "page": page_obj.get("page"),
                        "cleaned_text": raw_text
                    })
        
        print(f"[PIPELINE] Step 3 complete: {len(cleaned_pages)} pages cleaned (with some fallbacks if errors occurred)")
        full_text = "\n\n".join([p["cleaned_text"] for p in cleaned_pages if p["cleaned_text"] and p["cleaned_text"].strip()])
        
        # Save cleaned result
        cleaned_id = str(uuid.uuid4())
        cleaned_path = f"{TEMP_DIR}/{cleaned_id}.cleaned.json"
        
        with open(cleaned_path, "w", encoding="utf-8") as f:
            json.dump({"full_text": full_text, "pages": cleaned_pages}, f, ensure_ascii=False, indent=2)
        
        result["steps_completed"].append("clean_book")
        result["cleaned_file_id"] = cleaned_id
        
        # ===== STEP 4: Extract Chapters (Smart GPT-powered) =====
        logger.info("Step 4: Extracting chapters with GPT...")
        print(f"[PIPELINE] Step 4: Detecting book structure and chapters with GPT...")
        from app.chapters import extract_chapters_smart, write_stories_to_supabase, write_chapters_to_supabase
        
        stories, chapters = extract_chapters_smart(full_text)
        
        # Write stories first (for anthologies)
        story_id_map = {}
        if stories:
            print(f"[PIPELINE] Book is an anthology with {len(stories)} stories")
            story_id_map = write_stories_to_supabase(book_id, stories)
            result["stories"] = len(stories)
        
        # Write chapters (linked to stories if applicable)
        db_chapters = write_chapters_to_supabase(book_id, chapters, story_id_map)
        print(f"[PIPELINE] Step 4 complete: {len(stories)} stories, {len(db_chapters)} chapters created")
        
        result["steps_completed"].append("extract_chapters")
        result["chapters"] = len(db_chapters)
        
        # ===== STEP 5: Chunk Chapters (TTS sections) =====
        logger.info("Step 5: Creating TTS sections...")
        print(f"[PIPELINE] Step 5: Creating TTS sections (250 char chunks) for {len(db_chapters)} chapters...")
        from app.chapters import chunk_chapter_text, write_sections_to_supabase
        
        total_sections = 0
        
        for chapter in db_chapters:
            chapter_text = chapter.get("text", "")
            if chapter_text:
                sections = chunk_chapter_text(chapter_text, max_chars=250)
                write_sections_to_supabase(chapter["id"], sections)
                total_sections += len(sections)
            else:
                print(f"[PIPELINE] ⚠️ Warning: Chapter {chapter.get('chapter_index')} has no text!")
        
        print(f"[PIPELINE] Step 5 complete: {total_sections} sections created")
        result["steps_completed"].append("chunk_chapters")
        result["sections"] = total_sections
        
        # ===== STEP 6: Create Paragraphs (app display) =====
        logger.info("Step 6: Creating display paragraphs...")
        print(f"[PIPELINE] Step 6: Creating display paragraphs with GPT for {len(db_chapters)} chapters...")
        from app.chapters import split_into_paragraphs_gpt, write_paragraphs_to_supabase
        
        total_paragraphs = 0
        
        for i, chapter in enumerate(db_chapters):
            chapter_text = chapter.get("text", "")
            if chapter_text:
                print(f"[PIPELINE] Creating paragraphs for chapter {i+1}/{len(db_chapters)} (ID: {chapter['id']})...")
                paragraphs = split_into_paragraphs_gpt(chapter_text)
                write_paragraphs_to_supabase(chapter["id"], paragraphs)
                total_paragraphs += len(paragraphs)
            else:
                print(f"[PIPELINE] ⚠️ Warning: Chapter {i+1} has no text, skipping paragraphs!")
        
        print(f"[PIPELINE] Step 6 complete: {total_paragraphs} paragraphs created")
        result["steps_completed"].append("create_paragraphs")
        result["paragraphs"] = total_paragraphs
        
        # ===== DONE =====
        result["status"] = "ok"
        result["ready_for_tts"] = True
        
        print(f"[PIPELINE] ✅ COMPLETE! Book ID: {book_id}")
        logger.info(f"Pipeline complete! Book ID: {book_id}")
        
        return result
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[PIPELINE] ❌ ERROR: {str(e)}")
        print(f"[PIPELINE] Traceback: {error_details}")
        logger.error(f"Pipeline error: {str(e)}")
        result["status"] = "error"
        result["errors"].append(str(e))
        result["traceback"] = error_details
        return JSONResponse(result, status_code=500)

