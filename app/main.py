from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
import uuid
import os
import json

from app.extractor import extract_raw_pages
from app.cleaner import clean_page_text   # <-- NEW IMPORT

app = FastAPI()

# Temporary folder in Railway container
TEMP_DIR = "/tmp/honora"
os.makedirs(TEMP_DIR, exist_ok=True)

# -----------------------------------------------------------
# 1) PDF → RAW JSON extractor endpoint
# -----------------------------------------------------------
@app.post("/extract_pdf")
async def extract_pdf(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    pdf_path = f"{TEMP_DIR}/{file_id}.pdf"
    json_path = f"{TEMP_DIR}/{file_id}.json"

    # Save uploaded PDF
    with open(pdf_path, "wb") as f:
        f.write(await file.read())

    # Run PDF extractor
    pages = extract_raw_pages(pdf_path)

    # Save extracted content
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)

    return {
        "status": "ok",
        "file_id": file_id,
        "download_url": f"/download/{file_id}"
    }

# -----------------------------------------------------------
# 2) Download extracted JSON
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
# 3) NEW: Clean a single page using LLM
# -----------------------------------------------------------
@app.post("/clean_page")
async def clean_page(payload: dict):
    """
    payload format:
    {
        "items": [
            {"text": "...", "bbox": [...]},
            ...
        ]
    }
    """
    if "items" not in payload:
        return JSONResponse(
            {"error": "Missing 'items' in request body"},
            status_code=400
        )

    cleaned = clean_page_text(payload["items"])
    return cleaned

