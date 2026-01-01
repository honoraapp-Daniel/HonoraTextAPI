"""
Honora TTS Worker - RunPod Serverless Handler
Processes sections using XTTS v2 and uploads audio to Supabase Storage
"""

import os
import io
import tempfile
import runpod
import requests
from TTS.api import TTS
from supabase import create_client

# Initialize model (loaded once when container starts)
print("Loading XTTS v2 model...")
tts_model = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=True)
print("✅ Model loaded!")


def download_voice(voice_url: str) -> str:
    """Download voice reference file to temp path"""
    response = requests.get(voice_url, timeout=30)
    response.raise_for_status()
    
    temp_path = tempfile.mktemp(suffix=".wav")
    with open(temp_path, "wb") as f:
        f.write(response.content)
    
    return temp_path


def upload_to_supabase(supabase_url: str, supabase_key: str, section_id: str, audio_data: bytes) -> str:
    """Upload audio to Supabase Storage and update section record"""
    supabase = create_client(supabase_url, supabase_key)
    
    # Upload to storage
    file_path = f"audio/{section_id}.wav"
    
    supabase.storage.from_("audio").upload(
        file_path,
        audio_data,
        {"content-type": "audio/wav", "x-upsert": "true"}
    )
    
    # Get public URL
    audio_url = f"{supabase_url}/storage/v1/object/public/audio/{file_path}"
    
    # Update section record
    supabase.table("sections").update({
        "audio_url": audio_url
    }).eq("id", section_id).execute()
    
    return audio_url


def handler(job):
    """
    RunPod Serverless handler
    
    Input:
        sections: [{id, text}, ...]
        voice_url: URL to voice reference WAV
        supabase_url: Supabase project URL
        supabase_key: Supabase service role key
    
    Output:
        processed: number of sections processed
        status: "complete" or "error"
    """
    job_input = job["input"]
    sections = job_input.get("sections", [])
    voice_url = job_input.get("voice_url")
    supabase_url = job_input.get("supabase_url")
    supabase_key = job_input.get("supabase_key")
    
    if not sections:
        return {"status": "error", "error": "No sections provided"}
    
    if not voice_url:
        return {"status": "error", "error": "No voice URL provided"}
    
    if not supabase_url or not supabase_key:
        return {"status": "error", "error": "Supabase credentials missing"}
    
    try:
        # Download voice reference
        print(f"Downloading voice from: {voice_url}")
        voice_path = download_voice(voice_url)
        print("✅ Voice downloaded")
        
        processed = 0
        errors = []
        
        for section in sections:
            section_id = section.get("id")
            text = section.get("text", "").strip()
            
            if not text:
                print(f"Skipping empty section: {section_id}")
                continue
            
            try:
                print(f"Processing section {section_id}: {text[:50]}...")
                
                # Generate audio
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tts_model.tts_to_file(
                        text=text,
                        speaker_wav=voice_path,
                        language="en",
                        file_path=tmp.name
                    )
                    
                    # Read audio data
                    with open(tmp.name, "rb") as f:
                        audio_data = f.read()
                    
                    # Clean up temp file
                    os.unlink(tmp.name)
                
                # Upload to Supabase
                audio_url = upload_to_supabase(supabase_url, supabase_key, section_id, audio_data)
                print(f"✅ Section {section_id} complete: {audio_url}")
                
                processed += 1
                
                # Yield progress for streaming
                runpod.serverless.progress_update(job, {
                    "processed": processed,
                    "total": len(sections),
                    "current_section": section_id
                })
                
            except Exception as e:
                error_msg = f"Section {section_id}: {str(e)}"
                print(f"❌ Error: {error_msg}")
                errors.append(error_msg)
        
        # Clean up voice file
        if os.path.exists(voice_path):
            os.unlink(voice_path)
        
        return {
            "status": "complete",
            "processed": processed,
            "total": len(sections),
            "errors": errors if errors else None
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e)}


# Start RunPod Serverless
runpod.serverless.start({"handler": handler})
