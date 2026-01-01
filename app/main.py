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
from app.cover_art import generate_cover_image, update_book_cover_url


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

dashboard_path = static_path / "dashboard.html"
dashboard_v2_path = static_path / "dashboard_v2.html"


# Minimal dashboard UI for running the full pipeline
@app.get("/", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    if dashboard_path.exists():
        return FileResponse(dashboard_path)
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


# V2 Dashboard - Chapter by Chapter pipeline
@app.get("/v2", include_in_schema=False)
@app.get("/v2/dashboard", include_in_schema=False)
async def dashboard_v2():
    if dashboard_v2_path.exists():
        return FileResponse(dashboard_v2_path)
    return HTMLResponse("<h1>V2 Dashboard not found</h1>", status_code=404)


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
# Preview-only pipeline (no Supabase writes)
# -----------------------------------------------------------
@app.post("/process_book_preview")
async def process_book_preview(file: UploadFile = File(...)):
    """
    Preview pipeline: run full processing but DO NOT write to Supabase.
    Returns metadata, cover art preview URLs, and samples of sections/paragraphs.
    """
    preview_id = str(uuid.uuid4())
    pdf_path = f"{TEMP_DIR}/{preview_id}.pdf"
    json_path = f"{TEMP_DIR}/{preview_id}.json"
    preview_path = f"{TEMP_DIR}/{preview_id}.preview.json"

    with open(pdf_path, "wb") as f:
        f.write(await file.read())

    pages = extract_raw_pages(pdf_path)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)

    # Metadata from first pages
    first_pages_text = ""
    for page_obj in pages[:3]:
        items = page_obj.get("items", [])
        page_text = " ".join([item.get("text", "") for item in items])
        first_pages_text += page_text + "\n\n"
    metadata = extract_book_metadata(first_pages_text)

    # Cover art preview (no Supabase upload)
    cover_urls = {}
    try:
        cover_urls = generate_cover_image(metadata, upload=False)
    except Exception as cover_error:
        cover_urls["error"] = str(cover_error)

    # Clean pages
    cleaned_pages = []
    for page_obj in pages:
        items = page_obj.get("items", [])
        if items:
            cleaned = clean_page_text(items)
            cleaned_pages.append({
                "page": page_obj.get("page"),
                "cleaned_text": cleaned.get("cleaned_text", "")
            })
    full_text = "\n\n".join([p["cleaned_text"] for p in cleaned_pages if p.get("cleaned_text")])

    # Chapters + stories
    stories, chapters = extract_chapters_smart(full_text)

    # Sections - use same semantic splitting as paragraphs
    # Section 0 = chapter title, Section 1+ = semantic paragraphs
    sections_all = []
    sections_by_chapter = []
    for chap in chapters:
        # Use GPT to create semantic sections (same as paragraphs)
        chapter_sections = split_into_paragraphs_gpt(chap.get("text", ""))
        sections_by_chapter.append(chapter_sections)
        for idx, sec in enumerate(chapter_sections):
            sections_all.append({
                "chapter_index": chap.get("chapter_index"),
                "section_index": idx,  # Start from 0 (title is section 0)
                "text": sec
            })

    # Paragraphs
    paragraphs_all = []
    paragraphs_by_chapter = []
    for chap in chapters:
        chapter_paragraphs = split_into_paragraphs_gpt(chap.get("text", ""))
        paragraphs_by_chapter.append(chapter_paragraphs)
        for idx, par in enumerate(chapter_paragraphs):
            paragraphs_all.append({
                "chapter_index": chap.get("chapter_index"),
                "paragraph_index": idx + 1,
                "text": par
            })

    # Persist preview payload for later approval upload
    preview_payload = {
        "metadata": metadata,
        "cover_urls": cover_urls,
        "stories": stories,
        "chapters": chapters,
        "sections_by_chapter": sections_by_chapter,
        "paragraphs_by_chapter": paragraphs_by_chapter,
    }
    with open(preview_path, "w", encoding="utf-8") as f:
        json.dump(preview_payload, f, ensure_ascii=False, indent=2)

    return {
        "status": "preview",
        "preview_id": preview_id,
        "metadata": metadata,
        "cover_urls": cover_urls,
        "sections_sample": sections_all[:10],
        "paragraphs_sample": paragraphs_all[:10],
    }

# -----------------------------------------------------------
# Commit preview to Supabase after approval
# -----------------------------------------------------------
@app.post("/process_book_upload")
async def process_book_upload(payload: dict):
    """
    Commit a previously generated preview to Supabase.
    Expects: {"preview_id": "..."}
    """
    preview_id = payload.get("preview_id")
    if not preview_id:
        return JSONResponse({"error": "preview_id is required"}, status_code=400)

    preview_path = f"{TEMP_DIR}/{preview_id}.preview.json"
    if not os.path.isfile(preview_path):
        return JSONResponse({"error": "Preview not found"}, status_code=404)

    with open(preview_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    metadata = data.get("metadata", {})
    cover_urls_preview = data.get("cover_urls", {})
    stories = data.get("stories", [])
    chapters = data.get("chapters", [])
    sections_by_chapter = data.get("sections_by_chapter", [])
    paragraphs_by_chapter = data.get("paragraphs_by_chapter", [])

    # Create book
    book_id = create_book_in_supabase(metadata)

    # Generate & upload cover art
    try:
        metadata_with_id = dict(metadata)
        metadata_with_id["book_id"] = book_id
        cover_urls = generate_cover_image(metadata_with_id, upload=True)
        update_book_cover_url(book_id, cover_urls)
    except Exception as cover_error:
        cover_urls = {"error": str(cover_error), **cover_urls_preview}

    # Stories
    story_id_map = {}
    if stories:
        story_id_map = write_stories_to_supabase(book_id, stories)

    # Chapters
    db_chapters = write_chapters_to_supabase(book_id, chapters, story_id_map)
    total_sections = 0
    total_paragraphs = 0

    # Sections
    for i, chapter in enumerate(db_chapters):
        chapter_sections = sections_by_chapter[i] if i < len(sections_by_chapter) else []
        write_sections_to_supabase(chapter["id"], chapter_sections)
        total_sections += len(chapter_sections)

    # Paragraphs
    for i, chapter in enumerate(db_chapters):
        chapter_paragraphs = paragraphs_by_chapter[i] if i < len(paragraphs_by_chapter) else []
        write_paragraphs_to_supabase(chapter["id"], chapter_paragraphs)
        total_paragraphs += len(chapter_paragraphs)

    return {
        "status": "uploaded",
        "book_id": book_id,
        "cover_urls": cover_urls,
        "sections": total_sections,
        "paragraphs": total_paragraphs,
        "chapters": len(db_chapters),
        "stories": len(stories),
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
        
        # ===== STEP 5: Create Semantic Sections =====
        logger.info("Step 5: Creating semantic sections...")
        print(f"[PIPELINE] Step 5: Creating semantic sections (GPT paragraphs) for {len(db_chapters)} chapters...")
        from app.chapters import split_into_paragraphs_gpt, write_sections_to_supabase
        
        total_sections = 0
        
        for chapter in db_chapters:
            chapter_text = chapter.get("text", "")
            if chapter_text:
                # Use GPT semantic splitting - Section 0 = title, Section 1+ = paragraphs
                sections = split_into_paragraphs_gpt(chapter_text)
                write_sections_to_supabase(chapter["id"], sections)
                total_sections += len(sections)
            else:
                print(f"[PIPELINE] ⚠️ Warning: Chapter {chapter.get('chapter_index')} has no text!")
        
        print(f"[PIPELINE] Step 5 complete: {total_sections} semantic sections created")
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


# ============================================
# PIPELINE V2: CHAPTER-BY-CHAPTER ENDPOINTS
# ============================================

from app.pipeline_v2 import (
    create_job,
    get_job_state,
    phase_extract_pdf,
    phase_metadata,
    phase_detect_chapters,
    phase_process_chapter,
    phase_commit_to_supabase,
    process_all_chapters
)

TEMP_DIR_V2 = "/tmp/honora_v2"
os.makedirs(TEMP_DIR_V2, exist_ok=True)


@app.post("/v2/upload", tags=["Pipeline V2"])
async def v2_upload_file(file: UploadFile = File(...)):
    """
    Start a new V2 processing job.
    
    Uploads the file (PDF or JSON) and creates a job for chapter-by-chapter processing.
    Returns job_id for tracking progress.
    """
    # Determine file extension from uploaded filename
    original_filename = file.filename or "upload.pdf"
    extension = os.path.splitext(original_filename)[1].lower()
    
    # Default to .pdf if unknown
    if extension not in [".pdf", ".json"]:
        extension = ".pdf"
    
    # Save uploaded file with correct extension
    temp_id = str(uuid.uuid4())
    file_path = f"{TEMP_DIR_V2}/{temp_id}{extension}"
    
    with open(file_path, "wb") as f:
        f.write(await file.read())
    
    # Create job (will detect file type from extension)
    job_id = create_job(file_path)
    
    return {
        "status": "created",
        "job_id": job_id,
        "file_type": "json" if extension == ".json" else "pdf",
        "message": f"Job created from {extension.upper()[1:]} file. Call appropriate endpoints to process."
    }


@app.get("/v2/job/{job_id}", tags=["Pipeline V2"])
async def v2_get_job_status(job_id: str):
    """
    Get full job status including:
    - Current phase
    - Metadata preview  
    - Chapter list with status
    """
    state = get_job_state(job_id)
    if not state:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    
    return state


@app.post("/v2/job/{job_id}/extract", tags=["Pipeline V2"])
async def v2_extract_pdf(job_id: str):
    """
    Extract PDF to Markdown using Marker API.
    This is the first processing step after upload.
    """
    try:
        result = await phase_extract_pdf(job_id)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/v2/job/{job_id}/metadata", tags=["Pipeline V2"])
async def v2_extract_metadata(job_id: str):
    """
    Extract metadata (title, author, etc.) and generate cover art preview.
    Call after extraction is complete.
    """
    try:
        result = await phase_metadata(job_id)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/v2/job/{job_id}/detect-chapters", tags=["Pipeline V2"])
async def v2_detect_chapters(job_id: str):
    """
    Detect chapter boundaries from the Markdown.
    Returns list of chapters with titles and previews.
    """
    try:
        result = await phase_detect_chapters(job_id)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/v2/job/{job_id}/process-chapter/{chapter_index}", tags=["Pipeline V2"])
async def v2_process_single_chapter(job_id: str, chapter_index: int):
    """
    Process a single chapter: clean text, create sections and paragraphs.
    """
    try:
        result = await phase_process_chapter(job_id, chapter_index)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/v2/job/{job_id}/process-all", tags=["Pipeline V2"])
async def v2_process_all_chapters(job_id: str):
    """
    Process all chapters in sequence.
    Convenience endpoint for batch processing.
    """
    try:
        result = await process_all_chapters(job_id)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/v2/job/{job_id}/chapter/{chapter_index}", tags=["Pipeline V2"])
async def v2_edit_chapter(job_id: str, chapter_index: int, payload: dict):
    """
    Edit chapter content manually.
    
    payload: {
        "sections": ["Section 0 text", "Section 1 text", ...],
        "paragraphs": ["Paragraph 0 text", ...]
    }
    """
    state = get_job_state(job_id)
    if not state:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    
    chapters = state.get("chapters", [])
    chapter = next((c for c in chapters if c["index"] == chapter_index), None)
    
    if not chapter:
        return JSONResponse({"error": f"Chapter {chapter_index} not found"}, status_code=404)
    
    # Update chapter with new content
    if "sections" in payload:
        chapter["sections"] = payload["sections"]
        chapter["section_count"] = len(payload["sections"])
    
    if "paragraphs" in payload:
        chapter["paragraphs"] = payload["paragraphs"]
        chapter["paragraph_count"] = len(payload["paragraphs"])
    
    chapter["status"] = "ready"
    
    from app.pipeline_v2 import save_job_state
    save_job_state(job_id, state)
    
    return {
        "status": "updated",
        "chapter_index": chapter_index,
        "sections": len(chapter.get("sections", [])),
        "paragraphs": len(chapter.get("paragraphs", []))
    }


@app.post("/v2/job/{job_id}/rewrite-text", tags=["Pipeline V2"])
async def v2_rewrite_text(job_id: str, payload: dict):
    """
    Rewrite text using Gemini to remove special characters (TTS-friendly).
    
    payload: {
        "text": "Text with special characters ♄ ✶ △",
        "type": "paragraph" or "section" (optional)
    }
    
    Returns: {
        "original": "...",
        "rewritten": "...",
        "changes_detected": true/false
    }
    """
    try:
        from app.text_rewriter import rewrite_text_gemini
        
        text = payload.get("text")
        if not text:
            return JSONResponse({"error": "'text' is required"}, status_code=400)
        
        rewritten = rewrite_text_gemini(text)
        
        return {
            "original": text,
            "rewritten": rewritten,
            "changes_detected": text != rewritten
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/v2/job/{job_id}/optimize-paragraphs", tags=["Pipeline V2"])
async def v2_optimize_paragraphs(job_id: str, payload: dict):
    """
    Optimize paragraphs using Gemini: merge short, split long, improve TTS quality.
    
    payload: {
        "paragraphs": ["paragraph 1", "paragraph 2", ...],
        "chapter_title": "Chapter name" (optional)
    }
    
    Returns: {
        "optimized_paragraphs": [...],
        "changes": [...],
        "suggestions": [...]
    }
    """
    try:
        from app.text_rewriter import optimize_paragraphs_gemini
        
        paragraphs = payload.get("paragraphs")
        if not paragraphs or not isinstance(paragraphs, list):
            return JSONResponse({"error": "'paragraphs' must be a list"}, status_code=400)
        
        chapter_title = payload.get("chapter_title", "")
        
        result = optimize_paragraphs_gemini(paragraphs, chapter_title)
        
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/v2/job/{job_id}/chapter/{chapter_index}/sections", tags=["Pipeline V2"])
async def v2_update_sections(job_id: str, chapter_index: int, payload: dict):
    """
    Add, update, or delete sections for a chapter.
    
    payload: {
        "sections": ["Section 0 (title)", "Section 1", ...],
        "operation": "replace" (default), "append", or "insert",
        "insert_at": 2 (if operation=insert)
    }
    """
    state = get_job_state(job_id)
    if not state:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    
    chapters = state.get("chapters", [])
    chapter = next((c for c in chapters if c["index"] == chapter_index), None)
    
    if not chapter:
        return JSONResponse({"error": f"Chapter {chapter_index} not found"}, status_code=404)
    
    sections = payload.get("sections")
    if not sections or not isinstance(sections, list):
        return JSONResponse({"error": "'sections' must be a list"}, status_code=400)
    
    operation = payload.get("operation", "replace")
    
    if operation == "replace":
        chapter["sections"] = sections
    elif operation == "append":
        current_sections = chapter.get("sections", [])
        chapter["sections"] = current_sections + sections
    elif operation == "insert":
        insert_at = payload.get("insert_at", 0)
        current_sections = chapter.get("sections", [])
        chapter["sections"] = current_sections[:insert_at] + sections + current_sections[insert_at:]
    else:
        return JSONResponse({"error": f"Unknown operation: {operation}"}, status_code=400)
    
    chapter["section_count"] = len(chapter["sections"])
    
    from app.pipeline_v2 import save_job_state
    save_job_state(job_id, state)
    
    return {
        "status": "updated",
        "chapter_index": chapter_index,
        "sections": len(chapter.get("sections", [])),
        "operation": operation
    }


@app.delete("/v2/job/{job_id}/chapter/{chapter_index}/section/{section_index}", tags=["Pipeline V2"])
async def v2_delete_section(job_id: str, chapter_index: int, section_index: int):
    """
    Delete a specific section from a chapter.
    Section 0 (title) cannot be deleted.
    """
    state = get_job_state(job_id)
    if not state:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    
    chapters = state.get("chapters", [])
    chapter = next((c for c in chapters if c["index"] == chapter_index), None)
    
    if not chapter:
        return JSONResponse({"error": f"Chapter {chapter_index} not found"}, status_code=404)
    
    sections = chapter.get("sections", [])
    
    if section_index == 0:
        return JSONResponse({"error": "Cannot delete section 0 (chapter title)"}, status_code=400)
    
    if section_index < 0 or section_index >= len(sections):
        return JSONResponse({"error": f"Section {section_index} not found"}, status_code=404)
    
    sections.pop(section_index)
    chapter["sections"] = sections
    chapter["section_count"] = len(sections)
    
    from app.pipeline_v2 import save_job_state
    save_job_state(job_id, state)
    
    return {
        "status": "deleted",
        "chapter_index": chapter_index,
        "section_index": section_index,
        "remaining_sections": len(sections)
    }


@app.post("/v2/job/{job_id}/commit", tags=["Pipeline V2"])
async def v2_commit_to_supabase(job_id: str):
    """
    Final commit: Upload all processed data to Supabase.
    Creates book, chapters, sections, and paragraphs.
    """
    try:
        result = await phase_commit_to_supabase(job_id)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/v2/job/{job_id}/full-pipeline", tags=["Pipeline V2"])
async def v2_full_pipeline(job_id: str):
    """
    Run the complete V2 pipeline in one call:
    1. Extract PDF
    2. Extract metadata + cover art
    3. Detect chapters
    4. Process all chapters
    5. Commit to Supabase
    
    For automated processing without manual approval.
    """
    try:
        # Step 1: Extract
        await phase_extract_pdf(job_id)
        
        # Step 2: Metadata
        await phase_metadata(job_id)
        
        # Step 3: Detect chapters
        await phase_detect_chapters(job_id)
        
        # Step 4: Process all chapters
        await process_all_chapters(job_id)
        
        # Step 5: Commit
        result = await phase_commit_to_supabase(job_id)
        
        return {
            "status": "complete",
            **result
        }
        
    except Exception as e:
        import traceback
        return JSONResponse({
            "error": str(e),
            "traceback": traceback.format_exc()
        }, status_code=500)

