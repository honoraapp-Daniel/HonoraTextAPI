"""
Honora TTS Dashboard - Railway Edition
Connects to RunPod Serverless for GPU TTS processing
"""

import os
import json
import time
import requests
from flask import Flask, render_template, request, jsonify, Response
from functools import wraps

app = Flask(__name__)

# Environment variables - normalize URL (remove trailing slash for consistency)
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "")
RUNPOD_ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID", "")

# Supabase client - lazy initialization
_supabase = None

def get_supabase():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return None  # Return None instead of raising to avoid crashes
        try:
            from supabase import create_client
            _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception as e:
            print(f"Supabase init error: {e}")
            return None
    return _supabase


# =============================================================================
# ROUTES - Dashboard
# =============================================================================

@app.route("/")
def dashboard():
    """TTS Dashboard home"""
    return render_template("tts_dashboard.html")


@app.route("/health")
def health():
    """Health check for Railway"""
    return jsonify({"status": "ok"})


@app.route("/api/status")
def get_status():
    """Get configuration status - useful for debugging"""
    return jsonify({
        "supabase_configured": bool(SUPABASE_URL and SUPABASE_KEY),
        "runpod_configured": bool(RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID),
        "runpod_endpoint_id": RUNPOD_ENDPOINT_ID[:8] + "..." if RUNPOD_ENDPOINT_ID else None,
        "supabase_url": SUPABASE_URL[:30] + "..." if SUPABASE_URL else None
    })


# =============================================================================
# API - Books & Chapters from Supabase
# =============================================================================

@app.route("/api/books")
def get_books():
    """Get all books from Supabase"""
    try:
        supabase = get_supabase()
        result = supabase.table("books").select("id, title, author, cover_art_url").order("created_at", desc=True).limit(50).execute()
        return jsonify(result.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/books/<book_id>/chapters")
def get_chapters(book_id):
    """Get chapters for a book"""
    try:
        supabase = get_supabase()
        result = supabase.table("chapters").select("id, title, chapter_index").eq("book_id", book_id).order("chapter_index").execute()
        
        # Get section counts for each chapter
        chapters = []
        for ch in result.data:
            section_count = supabase.table("sections").select("id", count="exact").eq("chapter_id", ch["id"]).execute()
            audio_count = supabase.table("sections").select("id", count="exact").eq("chapter_id", ch["id"]).neq("audio_url", None).execute()
            
            chapters.append({
                **ch,
                "section_count": section_count.count or 0,
                "audio_count": audio_count.count or 0
            })
        
        return jsonify(chapters)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chapters/<chapter_id>/sections")
def get_sections(chapter_id):
    """Get sections for a chapter"""
    try:
        supabase = get_supabase()
        result = supabase.table("sections").select("id, section_index, text_ref, audio_url").eq("chapter_id", chapter_id).order("section_index").execute()
        return jsonify(result.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# API - Voice Management
# =============================================================================

@app.route("/api/voices")
def get_voices():
    """Get available voice references from Supabase storage"""
    try:
        supabase = get_supabase()
        result = supabase.storage.from_("voices").list()
        voices = [{"name": f["name"], "url": f"{SUPABASE_URL}/storage/v1/object/public/voices/{f['name']}"} 
                  for f in result if f["name"].endswith(".wav")]
        return jsonify(voices)
    except Exception as e:
        return jsonify({"error": str(e), "voices": []}), 200


@app.route("/api/voices/upload", methods=["POST"])
def upload_voice():
    """Upload a voice reference file"""
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files["file"]
        if not file.filename.endswith(".wav"):
            return jsonify({"error": "Only .wav files accepted"}), 400
        
        supabase = get_supabase()
        file_bytes = file.read()
        
        # Upload to Supabase Storage
        supabase.storage.from_("voices").upload(
            file.filename,
            file_bytes,
            {"content-type": "audio/wav", "x-upsert": "true"}
        )
        
        url = f"{SUPABASE_URL}/storage/v1/object/public/voices/{file.filename}"
        return jsonify({"success": True, "url": url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# API - RunPod TTS Jobs
# =============================================================================

def call_runpod(endpoint, payload):
    """Call RunPod Serverless API"""
    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        raise RuntimeError("RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID must be set")
    
    url = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/{endpoint}"
    headers = {"Authorization": f"Bearer {RUNPOD_API_KEY}", "Content-Type": "application/json"}
    
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def get_runpod_status(job_id):
    """Check RunPod job status"""
    url = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/status/{job_id}"
    headers = {"Authorization": f"Bearer {RUNPOD_API_KEY}"}
    
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


@app.route("/api/tts/start", methods=["POST"])
def start_tts_job():
    """Start a TTS generation job on RunPod"""
    try:
        data = request.json
        section_ids = data.get("section_ids", [])
        voice_url = data.get("voice_url")
        
        if not section_ids:
            return jsonify({"error": "No sections specified"}), 400
        if not voice_url:
            return jsonify({"error": "No voice URL specified"}), 400
        
        # Fetch section texts from Supabase
        supabase = get_supabase()
        sections = []
        for sid in section_ids:
            result = supabase.table("sections").select("id, text_ref").eq("id", sid).single().execute()
            if result.data:
                sections.append({"id": result.data["id"], "text": result.data["text_ref"]})
        
        if not sections:
            return jsonify({"error": "No valid sections found"}), 400
        
        # Start RunPod job
        payload = {
            "input": {
                "sections": sections,
                "voice_url": voice_url,
                "supabase_url": SUPABASE_URL,
                "supabase_key": SUPABASE_KEY
            }
        }
        
        result = call_runpod("run", payload)
        return jsonify({"job_id": result.get("id"), "status": result.get("status")})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tts/status/<job_id>")
def check_tts_status(job_id):
    """Check status of a TTS job"""
    try:
        result = get_runpod_status(job_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tts/chapter", methods=["POST"])
def start_chapter_job():
    """Start TTS for an entire chapter"""
    try:
        data = request.json
        chapter_id = data.get("chapter_id")
        voice_url = data.get("voice_url")
        limit = data.get("limit")  # Optional: limit number of sections (for testing)
        
        if not chapter_id or not voice_url:
            return jsonify({"error": "chapter_id and voice_url required"}), 400
        
        # Get all sections for chapter
        supabase = get_supabase()
        query = supabase.table("sections").select("id").eq("chapter_id", chapter_id).order("section_index")
        
        if limit:
            query = query.limit(limit)
        
        result = query.execute()
        section_ids = [s["id"] for s in result.data]
        
        if not section_ids:
            return jsonify({"error": "No sections found for chapter"}), 400
        
        # Reuse start_tts_job logic
        return start_tts_job_internal(section_ids, voice_url)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def start_tts_job_internal(section_ids, voice_url):
    """Internal helper to start TTS job"""
    supabase = get_supabase()
    sections = []
    
    for sid in section_ids:
        result = supabase.table("sections").select("id, text_ref").eq("id", sid).single().execute()
        if result.data:
            sections.append({"id": result.data["id"], "text": result.data["text_ref"]})
    
    payload = {
        "input": {
            "sections": sections,
            "voice_url": voice_url,
            "supabase_url": SUPABASE_URL,
            "supabase_key": SUPABASE_KEY
        }
    }
    
    result = call_runpod("run", payload)
    return jsonify({
        "job_id": result.get("id"),
        "status": result.get("status"),
        "section_count": len(sections)
    })


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
