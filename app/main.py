from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
import uuid
import os
import json
from app.extractor import extract_raw_pages

app = FastAPI()

TEMP_DIR = "/tmp/honora"
os.makedirs(TEMP_DIR, exist_ok=True)

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
        "json_url": f"/download/{file_id}"
    }

@app.get("/download/{file_id}")
def download_json(file_id: str):
    json_path = f"{TEMP_DIR}/{file_id}.json"
    if not os.path.exists(json_path):
        return JSONResponse({"error": "file not found"}, status_code=404)
    return FileResponse(json_path, media_type="application/json", filename=f"{file_id}.json")

