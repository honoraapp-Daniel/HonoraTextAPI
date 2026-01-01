# Honora TTS Service - Setup Guide

## Quick Start

### 1. Railway Dashboard Setup

1. In Railway, create new project from GitHub repo
2. Set root directory to `HonoraLocalTTS`
3. Add environment variables:
   - `SUPABASE_URL` - Your Supabase project URL
   - `SUPABASE_SERVICE_ROLE_KEY` - Service role key (not anon!)
   - `RUNPOD_API_KEY` - From RunPod console
   - `RUNPOD_ENDPOINT_ID` - Your serverless endpoint ID

4. Deploy will auto-start from `Dockerfile.dashboard`

### 2. RunPod Serverless Setup

1. Go to [RunPod Console](https://www.runpod.io/console/serverless)
2. Create new Serverless Endpoint
3. Build Docker image:
   ```bash
   cd HonoraLocalTTS
   docker build -f Dockerfile.runpod -t your-username/honora-tts:latest .
   docker push your-username/honora-tts:latest
   ```
4. Use image `your-username/honora-tts:latest`
5. Select GPU: RTX A4000 (16GB VRAM, $0.19/hr)
6. Copy Endpoint ID to Railway env vars

### 3. Supabase Setup

Create `voices` and `audio` storage buckets:

```sql
-- Create storage buckets if not exists
INSERT INTO storage.buckets (id, name, public) 
VALUES ('voices', 'voices', true), ('audio', 'audio', true)
ON CONFLICT (id) DO NOTHING;

-- Add audio_url column to sections if needed
ALTER TABLE sections ADD COLUMN IF NOT EXISTS audio_url TEXT;
```

### 4. Usage

1. Open Railway dashboard URL
2. Upload voice reference (.wav, 10-30 seconds of clear speech)
3. Select book → chapter
4. Test with 1-3 sections first
5. Process full chapter/book when satisfied

## File Structure

```
HonoraLocalTTS/
├── tts_dashboard.py       # Railway Flask app
├── templates/
│   └── tts_dashboard.html # Dashboard UI
├── runpod_handler.py      # RunPod GPU worker
├── Dockerfile.dashboard   # Railway container
├── Dockerfile.runpod      # RunPod GPU container
├── railway.json           # Railway config
├── requirements_dashboard.txt
└── requirements_runpod.txt
```
