"""
Honora TTS Dashboard - Multi-Engine Edition
Supports: Piper (free/fast), XTTS-Local (free/slow), XTTS-RunPod (paid/fast)
"""

import os
import json
import time
import uuid
import threading
import queue
import logging
from flask import Flask, render_template, request, jsonify, send_from_directory
from supabase import create_client

# Import our engine manager
from tts_engines import engine_manager, TTSEngine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
PORT = int(os.getenv("PORT", 5001))

# Output folder
OUTPUT_FOLDER = "generated_audio"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Supabase client
_supabase = None

def get_supabase():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return None
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


# =============================================================================
# JOB QUEUE & WORKER POOL
# =============================================================================

# Number of parallel TTS workers (for Replicate/RunPod)
PARALLEL_WORKERS = 3  # Can process 3 sections simultaneously

job_queue = queue.Queue()
job_status = {}
job_history = []  # Keep track of completed/failed jobs for dashboard log
MAX_HISTORY = 100  # Keep last 100 jobs in history


def tts_worker():
    """Background worker to process TTS jobs using selected engine"""
    while True:
        try:
            job = job_queue.get()
            job_id = job["id"]
            
            job_status[job_id]["status"] = "processing"
            engine_name = job.get("engine", "piper")
            logger.info(f"Processing job {job_id} with engine: {engine_name}")
            
            output_path = os.path.join(OUTPUT_FOLDER, f"{job_id}.wav")
            
            try:
                # Get the selected engine
                engine = engine_manager.get_engine(engine_name)
                logger.info(f"Job {job_id}: Using {engine.name} - {engine.description}")
                
                # Generate audio
                text = job["text"]
                voice = job.get("voice", "")
                language = job.get("language", "en")
                
                logger.info(f"Job {job_id}: Generating audio for: {text[:50]}...")
                start_time = time.time()
                
                success = engine.generate(
                    text=text,
                    voice=voice,
                    language=language,
                    output_path=output_path
                )
                
                elapsed = time.time() - start_time
                
                if success and os.path.exists(output_path):
                    # Try to upload to Supabase and update paragraph/section
                    public_url = None
                    try:
                        supabase = get_supabase()
                        if supabase:
                            # Use paragraph_id for filename if available
                            paragraph_id = job.get("paragraph_id")
                            if paragraph_id:
                                file_name = f"tts/{paragraph_id}.wav"
                            else:
                                file_name = f"tts/{job_id}.wav"
                            
                            with open(output_path, 'rb') as f:
                                supabase.storage.from_("audio").upload(
                                    file_name, 
                                    f.read(),
                                    {"content-type": "audio/wav", "x-upsert": "true"}
                                )
                            public_url = f"{SUPABASE_URL}/storage/v1/object/public/audio/{file_name}"
                            logger.info(f"Job {job_id}: Uploaded to {file_name}")
                            
                            # Update paragraph with audio_url so iOS app knows where to find it
                            if paragraph_id:
                                supabase.table("paragraphs").update({
                                    "audio_url": public_url
                                }).eq("id", paragraph_id).execute()
                                logger.info(f"Job {job_id}: Updated paragraph {paragraph_id} with audio_url")
                                
                    except Exception as upload_err:
                        logger.warning(f"Job {job_id}: Upload failed: {upload_err}")
                    
                    job_status[job_id]["status"] = "succeeded"
                    job_status[job_id]["output"] = public_url or f"/local/{job_id}.wav"
                    job_status[job_id]["local_path"] = output_path
                    job_status[job_id]["duration"] = elapsed
                    job_status[job_id]["engine"] = engine.name
                    
                    # Add to history
                    import datetime
                    job_history.insert(0, {
                        "job_id": job_id,
                        "paragraph_id": job.get("paragraph_id"),
                        "status": "succeeded",
                        "engine": engine.name,
                        "duration": round(elapsed, 1),
                        "timestamp": datetime.datetime.now().isoformat(),
                        "text_preview": text[:50] + "..." if len(text) > 50 else text
                    })
                    if len(job_history) > MAX_HISTORY:
                        job_history.pop()
                    
                    logger.info(f"Job {job_id} succeeded in {elapsed:.1f}s!")
                else:
                    job_status[job_id]["status"] = "failed"
                    job_status[job_id]["error"] = "Audio generation failed"
                    
                    # Add to history
                    import datetime
                    job_history.insert(0, {
                        "job_id": job_id,
                        "paragraph_id": job.get("paragraph_id"),
                        "status": "failed",
                        "engine": engine_name,
                        "error": "No output file",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "text_preview": text[:50] + "..." if len(text) > 50 else text
                    })
                    if len(job_history) > MAX_HISTORY:
                        job_history.pop()
                    
                    logger.error(f"Job {job_id} failed: no output file")
                
            except Exception as e:
                job_status[job_id]["status"] = "failed"
                job_status[job_id]["error"] = str(e)
                logger.error(f"Job {job_id} failed: {e}")
                import traceback
                traceback.print_exc()
                
            job_queue.task_done()
            
        except Exception as e:
            logger.error(f"Worker error: {e}")

# Start worker pool (multiple parallel workers)
for i in range(PARALLEL_WORKERS):
    threading.Thread(target=tts_worker, daemon=True, name=f"TTS-Worker-{i+1}").start()
logger.info(f"Started {PARALLEL_WORKERS} parallel TTS worker threads")


# =============================================================================
# ROUTES - Dashboard
# =============================================================================

@app.route("/")
def dashboard():
    return render_template("tts_dashboard.html")

@app.route("/api/status")
def get_status():
    return jsonify({
        "supabase_configured": bool(SUPABASE_URL and SUPABASE_KEY),
        "engines": engine_manager.list_engines(),
        "queue_size": job_queue.qsize(),
        "workers": PARALLEL_WORKERS
    })

@app.route("/api/history")
def get_job_history():
    """Get recent job history (succeeded and failed)"""
    return jsonify({
        "jobs": job_history,
        "total": len(job_history),
        "succeeded": len([j for j in job_history if j["status"] == "succeeded"]),
        "failed": len([j for j in job_history if j["status"] == "failed"])
    })

@app.route("/api/retry/<paragraph_id>", methods=["POST"])
def retry_paragraph(paragraph_id):
    """Retry a specific paragraph that failed"""
    try:
        data = request.json or {}
        engine = data.get("engine", "xtts-replicate")
        voice = data.get("voice", "")
        language = data.get("language", "en")
        
        supabase = get_supabase()
        res = supabase.table("paragraphs").select("id, text").eq("id", paragraph_id).single().execute()
        
        if not res.data:
            return jsonify({"error": "Paragraph not found"}), 404
        
        text = res.data["text"]
        job_id = str(uuid.uuid4())
        
        job_status[job_id] = {
            "id": job_id,
            "paragraph_id": paragraph_id,
            "status": "queued",
            "engine": engine
        }
        
        job_queue.put({
            "id": job_id,
            "paragraph_id": paragraph_id,
            "text": text,
            "voice": voice,
            "language": language,
            "engine": engine
        })
        
        return jsonify({
            "job_id": job_id,
            "paragraph_id": paragraph_id,
            "status": "queued"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ROUTES - Engines
# =============================================================================

@app.route("/api/engines")
def list_engines():
    """List all available TTS engines"""
    return jsonify(engine_manager.list_engines())

@app.route("/api/engines/<engine_id>/voices")
def get_engine_voices(engine_id):
    """Get voices for a specific engine"""
    engine = engine_manager.get_engine(engine_id)
    return jsonify(engine.get_voices())


# =============================================================================
# ROUTES - Books/Chapters from Supabase
# =============================================================================

@app.route("/api/books")
def get_books():
    try:
        sb = get_supabase()
        res = sb.table("books").select("id, title, author, cover_art_url").order("created_at", desc=True).limit(50).execute()
        return jsonify(res.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/books/<book_id>/chapters")
def get_chapters(book_id):
    try:
        sb = get_supabase()
        res = sb.table("chapters").select("id, title, chapter_index").eq("book_id", book_id).order("chapter_index").execute()
        chapters = []
        for ch in res.data:
            count = sb.table("paragraphs").select("id", count="exact").eq("chapter_id", ch["id"]).execute()
            chapters.append({
                "id": ch["id"],
                "title": ch["title"],
                "chapter_index": ch["chapter_index"],
                "section_count": count.count or 0,
            })
        return jsonify(chapters)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/chapters/<chapter_id>/sections")
def get_sections(chapter_id):
    try:
        sb = get_supabase()
        res = sb.table("paragraphs").select("id, paragraph_index, text").eq("chapter_id", chapter_id).order("paragraph_index").execute()
        return jsonify([{
            "id": p["id"], 
            "section_index": p["paragraph_index"], 
            "text": p["text"][:100] + "..." if len(p["text"]) > 100 else p["text"],
            "full_text": p["text"]
        } for p in res.data])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ROUTES - TTS-First v3.1 Segments & Spans
# =============================================================================

@app.route("/api/chapters/<chapter_id>/segments")
def get_segments(chapter_id):
    """Get TTS segments for a chapter (by current build)"""
    try:
        sb = get_supabase()
        # Get current build
        ch = sb.table("chapters").select("current_build_id, audio_version").eq("id", chapter_id).single().execute()
        build_id = ch.data.get("current_build_id") if ch.data else None
        audio_version = ch.data.get("audio_version", "v1") if ch.data else "v1"
        
        if build_id:
            res = sb.table("tts_segments").select("id, segment_index, text, text_normalized, duration_ms, group_id, offset_in_group_ms").eq("build_id", build_id).order("segment_index").execute()
        else:
            res = sb.table("tts_segments").select("id, segment_index, text, text_normalized, duration_ms, group_id, offset_in_group_ms").eq("chapter_id", chapter_id).order("segment_index").execute()
        
        return jsonify({
            "build_id": build_id,
            "audio_version": audio_version,
            "segments": res.data,
            "count": len(res.data)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/chapters/<chapter_id>/spans")
def get_spans(chapter_id):
    """Get paragraph spans for a chapter"""
    try:
        sb = get_supabase()
        ch = sb.table("chapters").select("current_build_id").eq("id", chapter_id).single().execute()
        build_id = ch.data.get("current_build_id") if ch.data else None
        
        if build_id:
            res = sb.table("paragraph_spans").select("id, paragraph_index, start_segment_index, end_segment_index").eq("build_id", build_id).order("paragraph_index").execute()
            return jsonify({
                "build_id": build_id,
                "spans": res.data,
                "count": len(res.data)
            })
        return jsonify({"build_id": None, "spans": [], "count": 0})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/chapters/<chapter_id>/builds")
def get_builds(chapter_id):
    """Get all builds for a chapter"""
    try:
        sb = get_supabase()
        res = sb.table("chapter_builds").select("id, canonical_version, canonical_hash, created_at").eq("chapter_id", chapter_id).order("canonical_version", desc=True).execute()
        
        # Get current build id
        ch = sb.table("chapters").select("current_build_id").eq("id", chapter_id).single().execute()
        current_build_id = ch.data.get("current_build_id") if ch.data else None
        
        return jsonify({
            "current_build_id": current_build_id,
            "builds": res.data,
            "count": len(res.data)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/chapters/<chapter_id>/audio_groups")
def get_audio_groups(chapter_id):
    """Get audio groups for a chapter"""
    try:
        sb = get_supabase()
        ch = sb.table("chapters").select("current_build_id").eq("id", chapter_id).single().execute()
        build_id = ch.data.get("current_build_id") if ch.data else None
        
        if build_id:
            res = sb.table("audio_groups").select("id, group_index, audio_url, duration_ms, start_time_ms, start_segment_index, end_segment_index").eq("build_id", build_id).order("group_index").execute()
        else:
            res = sb.table("audio_groups").select("id, group_index, audio_url, duration_ms, start_time_ms, start_segment_index, end_segment_index").eq("chapter_id", chapter_id).order("group_index").execute()
        
        return jsonify({
            "build_id": build_id,
            "groups": res.data,
            "count": len(res.data),
            "total_duration_ms": sum(g.get("duration_ms", 0) for g in res.data)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ROUTES - TTS Jobs
# =============================================================================

@app.route("/api/tts/start", methods=["POST"])
def start_tts_job():
    """Start TTS generation with selected engine"""
    try:
        data = request.json
        section_ids = data.get("section_ids", [])
        engine = data.get("engine", "piper")
        voice = data.get("voice", "")
        language = data.get("language", "en")
        
        if not section_ids:
            return jsonify({"error": "No sections selected"}), 400
        
        supabase = get_supabase()
        job_ids = []
        
        for sid in section_ids:
            # Fetch text
            res = supabase.table("paragraphs").select("id, text").eq("id", sid).single().execute()
            if not res.data:
                continue
            
            text = res.data["text"]
            job_id = str(uuid.uuid4())
            
            job_status[job_id] = {
                "id": job_id,
                "paragraph_id": sid,
                "status": "queued",
                "engine": engine
            }
            
            job_queue.put({
                "id": job_id,
                "paragraph_id": sid,  # Include for Supabase update
                "text": text,
                "voice": voice,
                "language": language,
                "engine": engine
            })
            job_ids.append(job_id)
        
        return jsonify({
            "job_ids": job_ids,
            "count": len(job_ids),
            "engine": engine,
            "status": "queued"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/tts/test", methods=["POST"])
def test_tts():
    """Quick test TTS with custom text"""
    try:
        data = request.json
        text = data.get("text", "Hello, this is a test of the text to speech system.")
        engine_name = data.get("engine", "piper")
        voice = data.get("voice", "")
        language = data.get("language", "en")
        
        job_id = str(uuid.uuid4())
        
        job_status[job_id] = {
            "id": job_id,
            "status": "queued",
            "engine": engine_name,
            "text": text[:50] + "..."
        }
        
        job_queue.put({
            "id": job_id,
            "text": text,
            "voice": voice,
            "language": language,
            "engine": engine_name
        })
        
        return jsonify({
            "job_id": job_id,
            "engine": engine_name,
            "status": "queued"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/tts/status/<job_id>")
def check_job_status(job_id):
    status = job_status.get(job_id)
    if not status:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(status)


# =============================================================================
# ROUTES - Voices
# =============================================================================

@app.route("/api/voices")
def get_voices():
    """Get all voices from all engines + Supabase"""
    voices = []
    
    # Get voices from each engine
    for engine_id, engine in engine_manager.engines.items():
        for v in engine.get_voices():
            v["engine"] = engine_id
            voices.append(v)
    
    # Also try Supabase
    try:
        sb = get_supabase()
        if sb:
            files = sb.storage.from_("voices").list()
            base_url = f"{SUPABASE_URL}/storage/v1/object/public/voices"
            for f in files:
                if f["name"].endswith(".wav"):
                    voices.append({
                        "id": f["name"],
                        "name": f["name"].replace(".wav", ""),
                        "url": f"{base_url}/{f['name']}",
                        "source": "supabase",
                        "engine": "xtts-local"  # Supabase voices work with XTTS
                    })
    except:
        pass
    
    return jsonify(voices)


# =============================================================================
# ROUTES - Local Files
# =============================================================================

@app.route("/local/<filename>")
def serve_local_audio(filename):
    """Serve locally generated audio files"""
    return send_from_directory(OUTPUT_FOLDER, filename)

@app.route("/local/voice/<filename>")
def serve_local_voice(filename):
    """Serve local voice reference files"""
    return send_from_directory("AI Stemmer Honora", filename)


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🎤 Honora TTS Dashboard - Multi-Engine Edition")
    print("="*60)
    print("\nAvailable engines:")
    for e in engine_manager.list_engines():
        status = "✅" if e["available"] else "❌"
        print(f"  {status} {e['name']}: {e['description']}")
    print(f"\nDashboard: http://127.0.0.1:{PORT}")
    print("="*60 + "\n")
    
    app.run(host="0.0.0.0", port=PORT, debug=True)
