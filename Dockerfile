# RunPod GPU Worker Dockerfile
# XTTS v2 with CUDA support
# NOTE: This Dockerfile is in the repo root for RunPod GitHub integration

FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

WORKDIR /app

# System dependencies for audio
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip first
RUN pip install --upgrade pip

# Install TTS and dependencies
RUN pip install --no-cache-dir TTS==0.22.0 supabase requests runpod

# Pre-download XTTS model (faster cold starts)
RUN python -c "from TTS.api import TTS; TTS('tts_models/multilingual/multi-dataset/xtts_v2')" || echo "Model will download on first use"

# Copy handler
COPY HonoraLocalTTS/runpod_handler.py /handler.py

# Run handler
CMD ["python", "-u", "/handler.py"]
