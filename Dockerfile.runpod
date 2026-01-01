# RunPod GPU Worker Dockerfile
# Using official Coqui TTS approach with PyTorch base

FROM pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime

WORKDIR /app

# System dependencies for audio
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    espeak-ng \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install TTS with all dependencies step by step
RUN pip install --upgrade pip setuptools wheel

# Install TTS dependencies first
RUN pip install --no-cache-dir numpy scipy torch torchaudio

# Install TTS (without version constraint to get latest working version)
RUN pip install --no-cache-dir TTS

# Install our additional dependencies
RUN pip install --no-cache-dir supabase requests runpod

# Pre-download XTTS model (faster cold starts)
RUN python -c "from TTS.api import TTS; TTS('tts_models/multilingual/multi-dataset/xtts_v2')" || echo "Model will download on first use"

# Copy handler
COPY HonoraLocalTTS/runpod_handler.py /handler.py

# Run handler
CMD ["python", "-u", "/handler.py"]
