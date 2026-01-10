"""
Honora TTS Worker - RunPod Serverless Handler
Processes text using XTTS v2 and returns audio

Supports two modes:
1. Simple mode: text + speaker_wav_b64 -> returns audio_b64
2. Batch mode: sections + voice_url + supabase credentials -> uploads to supabase
"""

import os
import base64
import tempfile
import traceback

# Global model - lazy loaded
tts_model = None

def get_tts_model():
    """Lazy load TTS model"""
    global tts_model
    if tts_model is None:
        print("Loading XTTS v2 model...")
        try:
            from TTS.api import TTS
            tts_model = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=True)
            print("✅ Model loaded successfully!")
        except Exception as e:
            print(f"❌ Model load error: {e}")
            traceback.print_exc()
            raise
    return tts_model


def download_voice(voice_url: str) -> str:
    """Download voice reference file to temp path"""
    import requests
    response = requests.get(voice_url, timeout=60)
    response.raise_for_status()
    
    temp_path = tempfile.mktemp(suffix=".wav")
    with open(temp_path, "wb") as f:
        f.write(response.content)
    
    return temp_path


def handler(job):
    """
    RunPod Serverless handler
    
    Simple Mode Input:
        text: Text to synthesize
        speaker_wav_b64: Base64 encoded voice reference WAV
        language: Language code (default: "en")
    
    Simple Mode Output:
        audio_b64: Base64 encoded audio WAV
        status: "complete" or "error"
    
    Batch Mode Input:
        sections: [{id, text}, ...]
        voice_url: URL to voice reference WAV
        supabase_url: Supabase project URL
        supabase_key: Supabase service role key
        language: Language code (default: "en")
    """
    import runpod
    
    try:
        job_input = job.get("input", {})
        
        # Check which mode we're in
        text = job_input.get("text")
        speaker_wav_b64 = job_input.get("speaker_wav_b64")
        sections = job_input.get("sections", [])
        
        # ========== SIMPLE MODE ==========
        if text and speaker_wav_b64:
            language = job_input.get("language", "en")
            
            print(f"Simple mode: Generating audio for: {text[:50]}...")
            
            # Load model
            model = get_tts_model()
            
            # Decode voice reference
            voice_data = base64.b64decode(speaker_wav_b64)
            voice_path = tempfile.mktemp(suffix=".wav")
            with open(voice_path, "wb") as f:
                f.write(voice_data)
            print("✅ Voice decoded")
            
            # Generate audio
            output_path = tempfile.mktemp(suffix=".wav")
            model.tts_to_file(
                text=text,
                speaker_wav=voice_path,
                language=language,
                file_path=output_path
            )
            print("✅ Audio generated")
            
            # Read and encode audio
            with open(output_path, "rb") as f:
                audio_data = f.read()
            audio_b64 = base64.b64encode(audio_data).decode()
            
            # Cleanup
            os.unlink(voice_path)
            os.unlink(output_path)
            
            return {
                "status": "complete",
                "audio_b64": audio_b64
            }
        
        # ========== BATCH MODE ==========
        elif sections:
            voice_url = job_input.get("voice_url")
            supabase_url = job_input.get("supabase_url")
            supabase_key = job_input.get("supabase_key")
            language = job_input.get("language", "en")
            
            if not voice_url:
                return {"status": "error", "error": "No voice URL provided"}
            
            if not supabase_url or not supabase_key:
                return {"status": "error", "error": "Supabase credentials missing"}
            
            # Load model
            model = get_tts_model()
            
            # Download voice reference
            print(f"Downloading voice from: {voice_url}")
            voice_path = download_voice(voice_url)
            print("✅ Voice downloaded")
            
            processed = 0
            errors = []
            
            from supabase import create_client
            supabase_url = supabase_url.rstrip("/")
            supabase = create_client(supabase_url, supabase_key)
            
            for i, section in enumerate(sections):
                section_id = section.get("id")
                text = section.get("text", "").strip()
                
                if not text:
                    print(f"Skipping empty section: {section_id}")
                    continue
                
                try:
                    print(f"[{i+1}/{len(sections)}] Processing: {text[:50]}...")
                    
                    # Generate audio
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        model.tts_to_file(
                            text=text,
                            speaker_wav=voice_path,
                            language=language,
                            file_path=tmp.name
                        )
                        
                        # Read audio data
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
                    
                    print(f"✅ Section complete: {audio_url}")
                    processed += 1
                    
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
        
        else:
            return {"status": "error", "error": "No text or sections provided"}
        
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "error": str(e)}


# Start RunPod Serverless
if __name__ == "__main__":
    import runpod
    print("Starting RunPod Serverless handler...")
    runpod.serverless.start({"handler": handler})
