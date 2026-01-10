"""
Honora TTS Worker - RunPod Serverless Handler
Version: simple_mode_v3 (2026-01-10)

Supports:
1. Simple mode: text + voice_url -> returns audio_b64
2. Batch mode: sections + voice_url -> uploads to supabase
3. Legacy: text + speaker_wav_b64 (deprecated, for transition only)

All responses include VERSION info for deployment verification.
"""

import os
import sys
import json
import base64
import hashlib
import tempfile
import traceback
import time
from datetime import datetime
from pathlib import Path

# =============================================================================
# VERSION INFO - CRITICAL FOR DEPLOYMENT VERIFICATION
# =============================================================================

VERSION = {
    "handler_version": "simple_mode_v3",
    "build_time": datetime.utcnow().isoformat() + "Z",
    "git_sha": os.getenv("GIT_SHA", "unknown"),
    "python_version": sys.version.split()[0],
    "torch_version": "loading...",
    "transformers_version": "loading...",
    "tts_version": "loading...",
}

def get_version_info():
    """Get current VERSION with dynamic library versions"""
    try:
        import torch
        VERSION["torch_version"] = torch.__version__
    except:
        VERSION["torch_version"] = "import_failed"
    
    try:
        import transformers
        VERSION["transformers_version"] = transformers.__version__
    except:
        VERSION["transformers_version"] = "import_failed"
    
    try:
        import TTS
        VERSION["tts_version"] = TTS.__version__
    except:
        VERSION["tts_version"] = "import_failed"
    
    return VERSION.copy()


# =============================================================================
# VOICE CACHE - Avoid re-downloading same voice files
# =============================================================================

VOICE_CACHE_DIR = Path("/tmp/honora_voice_cache")
VOICE_CACHE_DIR.mkdir(exist_ok=True)

def get_voice_cache_path(voice_url: str) -> Path:
    """Get cache path for a voice URL based on its hash"""
    url_hash = hashlib.md5(voice_url.encode()).hexdigest()[:16]
    return VOICE_CACHE_DIR / f"voice_{url_hash}.wav"

def download_voice_cached(voice_url: str) -> str:
    """Download voice file with caching. Returns path to WAV file."""
    import requests
    
    cache_path = get_voice_cache_path(voice_url)
    
    if cache_path.exists():
        print(f"[CACHE HIT] Voice cached at: {cache_path}")
        return str(cache_path)
    
    print(f"[CACHE MISS] Downloading voice from: {voice_url}")
    start = time.time()
    
    response = requests.get(voice_url, timeout=60)
    response.raise_for_status()
    
    voice_size = len(response.content)
    elapsed = time.time() - start
    print(f"[DOWNLOAD] Voice downloaded: {voice_size} bytes in {elapsed:.2f}s")
    
    with open(cache_path, "wb") as f:
        f.write(response.content)
    
    return str(cache_path)


# =============================================================================
# TTS MODEL - Warm load at startup, reuse for all requests
# =============================================================================

tts_model = None
model_load_error = None

def load_model_at_startup():
    """Load TTS model at startup for warm container"""
    global tts_model, model_load_error
    
    print("[MODEL] Loading XTTS v2 model at startup...")
    start = time.time()
    
    try:
        from TTS.api import TTS
        tts_model = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=True)
        elapsed = time.time() - start
        print(f"[MODEL] ✅ Model loaded successfully in {elapsed:.1f}s")
        return True
    except Exception as e:
        model_load_error = str(e)
        print(f"[MODEL] ❌ Model load FAILED: {e}")
        traceback.print_exc()
        return False

def get_tts_model():
    """Get the pre-loaded TTS model"""
    global tts_model, model_load_error
    
    if tts_model is None:
        if model_load_error:
            raise RuntimeError(f"Model failed to load at startup: {model_load_error}")
        # Try loading now as fallback
        if not load_model_at_startup():
            raise RuntimeError(f"Model load failed: {model_load_error}")
    
    return tts_model


# =============================================================================
# HELPER: Structured error response
# =============================================================================

def error_response(error_msg: str, details: dict = None) -> dict:
    """Create a structured error response with VERSION info"""
    response = {
        "status": "error",
        "error": error_msg,
        "version": get_version_info(),
    }
    if details:
        response["details"] = details
    return response

def success_response(data: dict) -> dict:
    """Create a structured success response with VERSION info"""
    data["status"] = "complete"
    data["version"] = get_version_info()
    return data


# =============================================================================
# MAIN HANDLER
# =============================================================================

def handler(job):
    """
    RunPod Serverless handler - supports multiple payload formats.
    
    Simple Mode (preferred):
        Input: { "text": "...", "voice_url": "https://...", "language": "en", "request_id": "..." }
        Output: { "status": "complete", "audio_b64": "...", "version": {...} }
    
    Legacy Simple Mode (deprecated):
        Input: { "text": "...", "speaker_wav_b64": "...", "language": "en" }
        Output: { "status": "complete", "audio_b64": "...", "version": {...} }
    
    Batch Mode:
        Input: { "sections": [{id, text}], "voice_url": "...", "supabase_url": "...", "supabase_key": "..." }
        Output: { "status": "complete", "processed": N, "version": {...} }
    
    Health Check:
        Input: { "health": true }
        Output: { "status": "healthy", "version": {...} }
    """
    request_start = time.time()
    request_id = "unknown"
    mode = "unknown"
    
    try:
        # Get input
        job_input = job.get("input", {})
        request_id = job_input.get("request_id", f"auto_{int(time.time()*1000)}")
        
        # Log request info
        payload_size = len(json.dumps(job_input))
        print(f"[REQUEST] id={request_id} payload_size={payload_size} bytes")
        
        # ========== HEALTH CHECK ==========
        if job_input.get("health"):
            mode = "health"
            print(f"[{request_id}] Health check requested")
            return {
                "status": "healthy",
                "version": get_version_info(),
                "cache_dir": str(VOICE_CACHE_DIR),
                "cached_voices": len(list(VOICE_CACHE_DIR.glob("*.wav"))),
                "model_loaded": tts_model is not None,
            }
        
        # Extract common fields
        text = job_input.get("text")
        sections = job_input.get("sections", [])
        voice_url = job_input.get("voice_url")
        speaker_wav_b64 = job_input.get("speaker_wav_b64")  # Legacy
        language = job_input.get("language", "en")
        
        # ========== SIMPLE MODE (text present) ==========
        if text:
            mode = "simple"
            print(f"[{request_id}] Simple mode: text={len(text)} chars")
            
            # Get voice path
            voice_path = None
            
            if voice_url:
                # Preferred: Download from URL (with caching)
                voice_path = download_voice_cached(voice_url)
            elif speaker_wav_b64:
                # Legacy: Decode base64 (deprecated)
                print(f"[{request_id}] WARNING: Using deprecated speaker_wav_b64 field")
                voice_data = base64.b64decode(speaker_wav_b64)
                print(f"[{request_id}] Voice decoded: {len(voice_data)} bytes")
                voice_path = tempfile.mktemp(suffix=".wav")
                with open(voice_path, "wb") as f:
                    f.write(voice_data)
            else:
                return error_response(
                    "Missing voice data: provide 'voice_url' (preferred) or 'speaker_wav_b64'",
                    {"request_id": request_id, "mode": mode}
                )
            
            # Load model and generate
            model = get_tts_model()
            
            output_path = tempfile.mktemp(suffix=".wav")
            print(f"[{request_id}] Generating audio...")
            inference_start = time.time()
            
            model.tts_to_file(
                text=text,
                speaker_wav=voice_path,
                language=language,
                file_path=output_path
            )
            
            inference_time = time.time() - inference_start
            print(f"[{request_id}] ✅ Inference complete in {inference_time:.2f}s")
            
            # Read and encode result
            with open(output_path, "rb") as f:
                audio_data = f.read()
            audio_b64 = base64.b64encode(audio_data).decode()
            
            # Cleanup temp files (but NOT cached voice files)
            os.unlink(output_path)
            if speaker_wav_b64 and voice_path and os.path.exists(voice_path):
                os.unlink(voice_path)
            
            total_time = time.time() - request_start
            print(f"[{request_id}] Request complete in {total_time:.2f}s")
            
            return success_response({
                "audio_b64": audio_b64,
                "audio_size": len(audio_data),
                "inference_time": inference_time,
                "total_time": total_time,
                "request_id": request_id,
            })
        
        # ========== BATCH MODE (sections present) ==========
        elif sections:
            mode = "batch"
            print(f"[{request_id}] Batch mode: {len(sections)} sections")
            
            supabase_url = job_input.get("supabase_url")
            supabase_key = job_input.get("supabase_key")
            
            if not voice_url:
                return error_response("Batch mode requires 'voice_url'", {"request_id": request_id})
            if not supabase_url or not supabase_key:
                return error_response("Batch mode requires 'supabase_url' and 'supabase_key'", {"request_id": request_id})
            
            # Download voice
            voice_path = download_voice_cached(voice_url)
            
            # Load model
            model = get_tts_model()
            
            # Process sections
            from supabase import create_client
            supabase_url = supabase_url.rstrip("/")
            supabase = create_client(supabase_url, supabase_key)
            
            processed = 0
            errors = []
            
            for i, section in enumerate(sections):
                section_id = section.get("id")
                section_text = section.get("text", "").strip()
                
                if not section_text:
                    print(f"[{request_id}] Skipping empty section: {section_id}")
                    continue
                
                try:
                    print(f"[{request_id}] [{i+1}/{len(sections)}] Processing: {section_text[:50]}...")
                    
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        model.tts_to_file(
                            text=section_text,
                            speaker_wav=voice_path,
                            language=language,
                            file_path=tmp.name
                        )
                        
                        with open(tmp.name, "rb") as f:
                            audio_data = f.read()
                        os.unlink(tmp.name)
                    
                    # Upload to Supabase
                    file_path = f"{section_id}.wav"
                    supabase.storage.from_("audio").upload(
                        file_path,
                        audio_data,
                        {"content-type": "audio/wav", "x-upsert": "true"}
                    )
                    
                    audio_url = f"{supabase_url}/storage/v1/object/public/audio/{file_path}"
                    supabase.table("sections").update({
                        "audio_url": audio_url
                    }).eq("id", section_id).execute()
                    
                    print(f"[{request_id}] ✅ Section {section_id} complete")
                    processed += 1
                    
                except Exception as e:
                    error_msg = f"Section {section_id}: {str(e)}"
                    print(f"[{request_id}] ❌ Error: {error_msg}")
                    errors.append(error_msg)
            
            total_time = time.time() - request_start
            print(f"[{request_id}] Batch complete: {processed}/{len(sections)} in {total_time:.2f}s")
            
            return success_response({
                "processed": processed,
                "total": len(sections),
                "errors": errors if errors else None,
                "total_time": total_time,
                "request_id": request_id,
            })
        
        # ========== NO VALID INPUT ==========
        else:
            return error_response(
                "Invalid input: provide 'text' (simple mode), 'sections' (batch mode), or 'health' (health check)",
                {
                    "request_id": request_id,
                    "received_keys": list(job_input.keys()),
                }
            )
    
    except Exception as e:
        total_time = time.time() - request_start
        print(f"[{request_id}] ❌ UNHANDLED EXCEPTION after {total_time:.2f}s: {e}")
        traceback.print_exc()
        
        return error_response(
            str(e),
            {
                "request_id": request_id,
                "mode": mode,
                "total_time": total_time,
                "traceback": traceback.format_exc(),
            }
        )


# =============================================================================
# STARTUP - Load model when container starts (warm start)
# =============================================================================

if __name__ == "__main__":
    import runpod
    
    print("=" * 60)
    print("HONORA TTS WORKER - STARTING")
    print("=" * 60)
    print(f"Version: {VERSION['handler_version']}")
    print(f"Build time: {VERSION['build_time']}")
    print(f"Git SHA: {VERSION['git_sha']}")
    print(f"Python: {VERSION['python_version']}")
    print("=" * 60)
    
    # Warm load model at startup
    load_model_at_startup()
    
    # Update version info with loaded library versions
    get_version_info()
    print(f"Torch: {VERSION['torch_version']}")
    print(f"Transformers: {VERSION['transformers_version']}")
    print(f"TTS: {VERSION['tts_version']}")
    print("=" * 60)
    print("Starting RunPod Serverless handler...")
    
    runpod.serverless.start({"handler": handler})
