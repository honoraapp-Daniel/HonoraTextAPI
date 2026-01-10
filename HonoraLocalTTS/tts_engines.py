"""
Honora TTS Engines - Flexible TTS with multiple backends
Supports:
  - Piper (free, fast, local CPU)
  - XTTS-v2 Local (free, slow on CPU, high quality)
  - XTTS-v2 RunPod (paid, fast GPU, high quality)
"""

import os
import uuid
import time
import logging
import subprocess
import tempfile
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# =============================================================================
# BASE ENGINE
# =============================================================================

class TTSEngine(ABC):
    """Base class for all TTS engines"""
    
    @abstractmethod
    def generate(self, text: str, voice: str, language: str, output_path: str) -> bool:
        """Generate audio from text. Returns True on success."""
        pass
    
    @abstractmethod
    def get_voices(self) -> list:
        """Return list of available voices"""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        pass


# =============================================================================
# PIPER ENGINE (Free, Fast, Local)
# =============================================================================

class PiperEngine(TTSEngine):
    """Piper TTS - Fast local CPU inference"""
    
    # Model folder
    MODEL_DIR = "piper_models"
    
    # Available voices (need to be downloaded first)
    VOICES = {
        "en-us-lessac": {"file": "en_US-lessac-medium.onnx", "name": "Lessac (US English)"},
    }
    
    def __init__(self):
        self._voice_cache = None
        # Ensure model dir exists
        os.makedirs(self.MODEL_DIR, exist_ok=True)
    
    @property
    def name(self) -> str:
        return "Piper"
    
    @property
    def description(self) -> str:
        return "Fast local TTS (free, ~10x faster than XTTS on CPU)"
    
    def get_voices(self) -> list:
        voices = []
        # Check which models are actually downloaded
        if os.path.exists(self.MODEL_DIR):
            for f in os.listdir(self.MODEL_DIR):
                if f.endswith(".onnx"):
                    voice_name = f.replace(".onnx", "")
                    voices.append({
                        "id": voice_name,
                        "name": voice_name.replace("_", " ").replace("-", " ").title(),
                        "path": os.path.join(self.MODEL_DIR, f),
                        "source": "piper"
                    })
        return voices if voices else [{"id": "en_US-lessac-medium", "name": "Lessac (US)", "source": "piper"}]
    
    def generate(self, text: str, voice: str, language: str, output_path: str) -> bool:
        try:
            # Find model file
            model_path = None
            for v in self.get_voices():
                if v.get("path"):
                    model_path = v["path"]
                    break
            
            if not model_path:
                # Try default
                model_path = os.path.join(self.MODEL_DIR, "en_US-lessac-medium.onnx")
            
            if not os.path.exists(model_path):
                logger.error(f"Piper model not found: {model_path}")
                logger.error("Download with: python -c \"from piper import download; download.download_voice('en_US-lessac-medium')\"")
                return False
            
            logger.info(f"Piper: Generating with model {model_path}")
            start = time.time()
            
            # Use piper command line with explicit model path
            cmd = [
                "piper",
                "--model", model_path,
                "--output_file", output_path
            ]
            
            # Pipe text to piper
            result = subprocess.run(
                cmd,
                input=text.encode('utf-8'),
                capture_output=True,
                timeout=60
            )
            
            if result.returncode != 0:
                stderr = result.stderr.decode()
                logger.error(f"Piper error: {stderr}")
                return False
            
            elapsed = time.time() - start
            logger.info(f"Piper: Generated in {elapsed:.1f}s")
            return os.path.exists(output_path)
            
        except FileNotFoundError:
            logger.error("Piper not found. Install with: pip install piper-tts")
            return False
        except Exception as e:
            logger.error(f"Piper error: {e}")
            import traceback
            traceback.print_exc()
            return False


# =============================================================================
# XTTS LOCAL ENGINE (Free, Slow, High Quality)
# =============================================================================

class XTTSLocalEngine(TTSEngine):
    """XTTS-v2 running locally on CPU"""
    
    def __init__(self):
        self._model = None
        self._voice_folder = "AI Stemmer Honora"
    
    @property
    def name(self) -> str:
        return "XTTS-Local"
    
    @property
    def description(self) -> str:
        return "High-quality voice cloning (free, slow on CPU ~20s per sentence)"
    
    def _load_model(self):
        if self._model is None:
            logger.info("Loading XTTS-v2 model (this takes ~45s first time)...")
            from TTS.api import TTS
            self._model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")
            logger.info("XTTS-v2 model loaded!")
        return self._model
    
    def get_voices(self) -> list:
        voices = []
        if os.path.exists(self._voice_folder):
            for f in os.listdir(self._voice_folder):
                if f.endswith(".wav"):
                    voices.append({
                        "id": f,
                        "name": f.replace("AI_Voice_Honora_", "").replace(".wav", ""),
                        "path": os.path.join(self._voice_folder, f),
                        "source": "xtts-local"
                    })
        return voices
    
    def generate(self, text: str, voice: str, language: str, output_path: str) -> bool:
        try:
            tts = self._load_model()
            
            # Find voice file
            voice_path = None
            for v in self.get_voices():
                if v["id"] == voice or v["name"].lower() == voice.lower():
                    voice_path = v["path"]
                    break
            
            if not voice_path:
                # Default to first available voice
                voices = self.get_voices()
                if voices:
                    voice_path = voices[0]["path"]
                else:
                    logger.error("No voice files found")
                    return False
            
            logger.info(f"XTTS-Local: Generating with voice {voice_path}")
            start = time.time()
            
            tts.tts_to_file(
                text=text,
                speaker_wav=voice_path,
                language=language or "en",
                file_path=output_path
            )
            
            elapsed = time.time() - start
            logger.info(f"XTTS-Local: Generated in {elapsed:.1f}s")
            return os.path.exists(output_path)
            
        except Exception as e:
            logger.error(f"XTTS-Local error: {e}")
            import traceback
            traceback.print_exc()
            return False


# =============================================================================
# XTTS RUNPOD ENGINE (Paid, Fast, High Quality)
# =============================================================================

class XTTSRunPodEngine(TTSEngine):
    """
    XTTS-v2 on RunPod Serverless GPU
    
    Features:
    - Voice URL architecture (no multi-MB Base64 per request)
    - Automatic voice upload to Supabase if needed
    - Retries with exponential backoff
    - Request correlation via request_id
    - Proper timeouts (connect + read)
    - VERSION verification from worker responses
    """
    
    # Retry configuration
    MAX_RETRIES = 3
    INITIAL_BACKOFF = 1.0  # seconds
    MAX_BACKOFF = 10.0  # seconds
    
    # Timeout configuration (seconds)
    CONNECT_TIMEOUT = 10
    READ_TIMEOUT = 120  # TTS can take a while
    
    def __init__(self):
        self.api_key = os.getenv("RUNPOD_API_KEY", "")
        self.endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID", "")
        self._voice_folder = "AI Stemmer Honora"
        
        # Supabase config for voice uploads
        self._supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self._supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self._supabase = None
        
        # Track last worker version for debugging
        self.last_worker_version = None
    
    @property
    def name(self) -> str:
        return "XTTS-RunPod"
    
    @property
    def description(self) -> str:
        return "High-quality voice cloning on GPU (~$0.20/hr, 10-20x faster)"
    
    def is_configured(self) -> bool:
        return bool(self.api_key and self.endpoint_id)
    
    def _get_supabase(self):
        """Lazy-load Supabase client"""
        if self._supabase is None and self._supabase_url and self._supabase_key:
            from supabase import create_client
            self._supabase = create_client(self._supabase_url, self._supabase_key)
        return self._supabase
    
    def get_voices(self) -> list:
        """Get available voices from local folder"""
        voices = []
        if os.path.exists(self._voice_folder):
            for f in os.listdir(self._voice_folder):
                if f.endswith(".wav"):
                    voices.append({
                        "id": f,
                        "name": f.replace("AI_Voice_Honora_", "").replace(".wav", ""),
                        "path": os.path.join(self._voice_folder, f),
                        "source": "xtts-runpod"
                    })
        return voices
    
    def _get_voice_url(self, voice: str) -> tuple:
        """
        Get or create a Supabase URL for the voice file.
        Returns (voice_url, voice_path) tuple.
        """
        # Find local voice file
        voice_path = None
        for v in self.get_voices():
            if v["id"] == voice or v["name"].lower() == voice.lower():
                voice_path = v["path"]
                break
        
        if not voice_path:
            voices = self.get_voices()
            if voices:
                voice_path = voices[0]["path"]
            else:
                return None, None
        
        voice_filename = os.path.basename(voice_path)
        
        # Check if we have Supabase configured
        supabase = self._get_supabase()
        if not supabase:
            logger.warning("Supabase not configured - cannot use voice_url mode")
            return None, voice_path
        
        # Build the public URL (assume voice is already in bucket or upload it)
        voice_url = f"{self._supabase_url}/storage/v1/object/public/voices/{voice_filename}"
        
        # Try to upload if not exists (upsert)
        try:
            with open(voice_path, "rb") as f:
                voice_data = f.read()
            
            # Use upsert to upload/update
            supabase.storage.from_("voices").upload(
                voice_filename,
                voice_data,
                {"content-type": "audio/wav", "x-upsert": "true"}
            )
            logger.info(f"Voice uploaded to Supabase: {voice_filename}")
        except Exception as e:
            # May already exist, that's OK
            logger.debug(f"Voice upload note: {e}")
        
        return voice_url, voice_path
    
    def _call_runpod_with_retry(self, payload: dict) -> dict:
        """
        Call RunPod API with retries and exponential backoff.
        Returns the parsed JSON response or raises an exception.
        """
        import requests
        
        request_id = payload.get("input", {}).get("request_id", "unknown")
        payload_size = len(str(payload))
        
        logger.info(f"[{request_id}] Calling RunPod (payload: {payload_size} bytes)")
        
        last_error = None
        backoff = self.INITIAL_BACKOFF
        
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                logger.info(f"[{request_id}] Attempt {attempt}/{self.MAX_RETRIES}")
                
                response = requests.post(
                    f"https://api.runpod.ai/v2/{self.endpoint_id}/runsync",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=payload,
                    timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT)
                )
                
                # Check for HTTP errors
                if response.status_code >= 500:
                    raise requests.exceptions.RequestException(f"Server error: {response.status_code}")
                
                if response.status_code != 200:
                    logger.error(f"[{request_id}] HTTP {response.status_code}: {response.text}")
                    return {"status": "FAILED", "error": f"HTTP {response.status_code}"}
                
                result = response.json()
                
                # Log worker version if present
                worker_version = result.get("output", {}).get("version") or result.get("version")
                if worker_version:
                    self.last_worker_version = worker_version
                    logger.info(f"[{request_id}] Worker version: {worker_version.get('handler_version', 'unknown')}")
                
                return result
                
            except requests.exceptions.Timeout as e:
                last_error = f"Timeout: {e}"
                logger.warning(f"[{request_id}] Attempt {attempt} timeout: {e}")
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                logger.warning(f"[{request_id}] Attempt {attempt} connection error: {e}")
            except requests.exceptions.RequestException as e:
                last_error = f"Request error: {e}"
                logger.warning(f"[{request_id}] Attempt {attempt} error: {e}")
            except Exception as e:
                last_error = f"Unexpected error: {e}"
                logger.error(f"[{request_id}] Attempt {attempt} unexpected error: {e}")
            
            # Backoff before retry (except on last attempt)
            if attempt < self.MAX_RETRIES:
                logger.info(f"[{request_id}] Retrying in {backoff:.1f}s...")
                time.sleep(backoff)
                backoff = min(backoff * 2, self.MAX_BACKOFF)
        
        # All retries exhausted
        logger.error(f"[{request_id}] All {self.MAX_RETRIES} attempts failed. Last error: {last_error}")
        return {"status": "FAILED", "error": last_error}
    
    def health_check(self) -> dict:
        """Check RunPod worker health and get version info"""
        if not self.is_configured():
            return {"status": "error", "error": "RunPod not configured"}
        
        request_id = str(uuid.uuid4())[:8]
        
        result = self._call_runpod_with_retry({
            "input": {
                "health": True,
                "request_id": request_id
            }
        })
        
        return result
    
    def generate(self, text: str, voice: str, language: str, output_path: str) -> bool:
        """Generate audio using RunPod XTTS worker"""
        if not self.is_configured():
            logger.error("RunPod not configured. Set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID")
            return False
        
        request_id = str(uuid.uuid4())
        
        try:
            import base64
            
            # Get voice URL (preferred) or fall back to local path
            voice_url, voice_path = self._get_voice_url(voice)
            
            if not voice_url and not voice_path:
                logger.error("No voice files found")
                return False
            
            # Build payload - prefer voice_url over base64
            payload = {
                "input": {
                    "text": text,
                    "language": language or "en",
                    "request_id": request_id,
                }
            }
            
            if voice_url:
                # Preferred: Use URL (worker downloads and caches)
                payload["input"]["voice_url"] = voice_url
                logger.info(f"[{request_id}] Using voice_url: {voice_url}")
            else:
                # Fallback: Base64 encode (deprecated path)
                logger.warning(f"[{request_id}] Falling back to base64 voice (no Supabase configured)")
                with open(voice_path, "rb") as f:
                    voice_b64 = base64.b64encode(f.read()).decode()
                payload["input"]["speaker_wav_b64"] = voice_b64
            
            logger.info(f"[{request_id}] XTTS-RunPod: Sending to GPU...")
            start = time.time()
            
            # Call with retry
            result = self._call_runpod_with_retry(payload)
            
            # Check result
            if result.get("status") == "COMPLETED":
                output = result.get("output", {})
                audio_b64 = output.get("audio_b64")
                
                if audio_b64:
                    with open(output_path, "wb") as f:
                        f.write(base64.b64decode(audio_b64))
                    
                    elapsed = time.time() - start
                    inference_time = output.get("inference_time", "?")
                    logger.info(f"[{request_id}] ✅ XTTS-RunPod: Generated in {elapsed:.1f}s (inference: {inference_time}s)")
                    return os.path.exists(output_path)
                else:
                    logger.error(f"[{request_id}] No audio_b64 in response: {output}")
                    return False
            else:
                error = result.get("error") or result.get("output", {}).get("error") or "Unknown error"
                worker_version = result.get("output", {}).get("version", {}).get("handler_version", "unknown")
                logger.error(f"[{request_id}] RunPod job failed (worker: {worker_version}): {error}")
                return False
                
        except Exception as e:
            logger.error(f"[{request_id}] XTTS-RunPod error: {e}")
            import traceback
            traceback.print_exc()
            return False


# =============================================================================
# ENGINE MANAGER
# =============================================================================

class TTSEngineManager:
    """Manages all available TTS engines"""
    
    def __init__(self):
        self.engines = {
            "piper": PiperEngine(),
            "xtts-local": XTTSLocalEngine(),
            "xtts-runpod": XTTSRunPodEngine(),
        }
        self._default = "piper"  # Default to fastest free option
    
    def get_engine(self, name: str = None) -> TTSEngine:
        """Get engine by name, or default"""
        if name and name in self.engines:
            return self.engines[name]
        return self.engines[self._default]
    
    def list_engines(self) -> list:
        """List all available engines with status"""
        result = []
        for key, engine in self.engines.items():
            status = {
                "id": key,
                "name": engine.name,
                "description": engine.description,
                "available": True
            }
            
            # Check if RunPod is configured
            if key == "xtts-runpod":
                status["available"] = engine.is_configured()
                if not status["available"]:
                    status["description"] += " (not configured)"
            
            result.append(status)
        return result
    
    def set_default(self, engine_name: str):
        if engine_name in self.engines:
            self._default = engine_name


# Global instance
engine_manager = TTSEngineManager()
