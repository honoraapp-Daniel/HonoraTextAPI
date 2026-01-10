# RunPod TTS Deployment Guide

## Problem Background

We encountered two failure modes:
1. **"No sections provided"** - Workers running old code that only supports batch mode
2. **"EOF when reading a line"** - Worker crashes from large Base64 payloads

## Solution Summary

- Handler now supports BOTH simple mode (`text + voice_url`) and batch mode (`sections`)
- All responses include VERSION info for deployment verification
- Voice files are now fetched via URL (not embedded as Base64)
- Worker caches voice files in `/tmp/honora_voice_cache/`
- Client has retries, timeouts, and request correlation

---

## Step-by-Step Redeployment Procedure

### 1. Verify Code is Pushed

```bash
cd /Users/cuwatyarecords/Desktop/HonoraTextAPI
git log -1 --oneline
# Should show latest commit with handler changes
```

### 2. Build Docker Image with Unique Tag

**IMPORTANT: Do NOT use `latest` tag. Use a unique tag for tracking.**

```bash
# Get git SHA for tagging
GIT_SHA=$(git rev-parse --short HEAD)
BUILD_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "Building with GIT_SHA=$GIT_SHA, BUILD_TIME=$BUILD_TIME"

# Build with build args
docker build \
  -f HonoraLocalTTS/Dockerfile.runpod \
  --build-arg GIT_SHA=$GIT_SHA \
  --build-arg BUILD_TIME=$BUILD_TIME \
  -t your-dockerhub/honora-tts:$GIT_SHA \
  .

# Also tag as latest for convenience
docker tag your-dockerhub/honora-tts:$GIT_SHA your-dockerhub/honora-tts:latest
```

### 3. Push to Docker Hub

```bash
docker push your-dockerhub/honora-tts:$GIT_SHA
docker push your-dockerhub/honora-tts:latest
```

### 4. Update RunPod Template

1. Go to RunPod Console: https://www.runpod.io/console/serverless
2. Click on your **HonoraTextAPI** endpoint
3. Go to **Templates** or **Settings**
4. Update the Docker image to the NEW tag: `your-dockerhub/honora-tts:<GIT_SHA>`
5. Save changes

### 5. Force Worker Restart (Critical!)

Option A: **Scale to Zero and Back**
1. Go to endpoint settings
2. Set "Min Workers" to 0
3. Wait for all workers to terminate
4. Set "Min Workers" back to desired value (e.g., 1-3)

Option B: **Terminate Existing Workers**
1. Go to **Workers** tab
2. Click "Terminate" on each running worker
3. New workers will start automatically with the new image

### 6. Verify New Code is Running

Run the health check from your local machine:

```bash
cd /Users/cuwatyarecords/Desktop/HonoraTextAPI/HonoraLocalTTS
source .venv-tts/bin/activate
export $(cat ../.env | grep -v '^#' | xargs)

python3 -c "
from tts_engines import engine_manager

engine = engine_manager.get_engine('xtts-runpod')
result = engine.health_check()
print('Health Check Result:')
print(f'  Status: {result.get(\"status\")}')
if 'version' in result:
    v = result['version']
    print(f'  Handler Version: {v.get(\"handler_version\")}')
    print(f'  Git SHA: {v.get(\"git_sha\")}')
    print(f'  Build Time: {v.get(\"build_time\")}')
    print(f'  Torch: {v.get(\"torch_version\")}')
else:
    print(f'  Error: {result.get(\"error\")}')
    print('  ⚠️ OLD CODE STILL RUNNING - VERSION info missing!')
"
```

**Expected Output:**
```
Health Check Result:
  Status: healthy
  Handler Version: simple_mode_v3
  Git SHA: abc1234
  Build Time: 2026-01-10T17:30:00Z
  Torch: 2.1.0+cu118
```

If you see VERSION info, the new code is running! ✅

---

## Test Plan

### Test 1: Health Check
```bash
python3 -c "
from tts_engines import engine_manager
engine = engine_manager.get_engine('xtts-runpod')
print(engine.health_check())
"
```

### Test 2: Tiny Text Request
```bash
python3 -c "
from tts_engines import engine_manager
engine = engine_manager.get_engine('xtts-runpod')
success = engine.generate('Hello world.', '', 'en', '/tmp/test_tiny.wav')
print(f'Success: {success}')
import os
if success:
    print(f'File size: {os.path.getsize(\"/tmp/test_tiny.wav\")} bytes')
"
```

### Test 3: Text + Voice URL Request
```bash
python3 -c "
from tts_engines import engine_manager
engine = engine_manager.get_engine('xtts-runpod')
success = engine.generate(
    'Welcome to Honora. This is a test of the text to speech system.',
    'AI_Voice_Honora_Billy.wav',
    'en',
    '/tmp/test_voice.wav'
)
print(f'Success: {success}')
"
```

### Test 4: Play Generated Audio
```bash
afplay /tmp/test_voice.wav
```

### Test 5: Parallel Stress Test (10 Requests)
```bash
python3 -c "
import concurrent.futures
import time
from tts_engines import engine_manager

engine = engine_manager.get_engine('xtts-runpod')

def run_test(i):
    start = time.time()
    success = engine.generate(f'This is test number {i}.', '', 'en', f'/tmp/stress_{i}.wav')
    elapsed = time.time() - start
    return i, success, elapsed

print('Running 10 parallel requests...')
start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    results = list(executor.map(run_test, range(10)))

total = time.time() - start
successes = sum(1 for _, s, _ in results if s)
print(f'Results: {successes}/10 succeeded in {total:.1f}s total')
for i, success, elapsed in results:
    print(f'  Test {i}: {\"✅\" if success else \"❌\"} ({elapsed:.1f}s)')
"
```

---

## Troubleshooting

### Still seeing "No sections provided"
- Workers are still running old code
- Terminate ALL workers and wait for new ones to start
- Verify the image tag in template matches your pushed image

### Still seeing "EOF when reading a line"
- Check if the new handler is actually deployed (health check should return VERSION)
- If VERSION shows old code, redeploy
- If VERSION shows new code but still failing, check RunPod logs for Python exceptions

### Worker version shows "unknown" git_sha
- The Docker image was built without `--build-arg GIT_SHA=...`
- Rebuild with the build args as shown above

---

## Architecture After Fix

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  TTS Dashboard  │────▶│ XTTSRunPodEngine│────▶│  RunPod Worker  │
│   (Flask)       │     │ (tts_engines.py)│     │ (handler.py)    │
└─────────────────┘     └────────┬────────┘     └────────┬────────┘
                                 │                       │
                                 │ 1. Upload voice       │ 2. Download voice
                                 │    to Supabase        │    (with cache)
                                 ▼                       ▼
                        ┌─────────────────┐     ┌─────────────────┐
                        │    Supabase     │     │  Voice Cache    │
                        │  voices bucket  │     │  /tmp/cache/    │
                        └─────────────────┘     └─────────────────┘
```

**Data Flow:**
1. Client uploads voice file to Supabase (once)
2. Client sends `voice_url` to RunPod (small payload)
3. Worker downloads voice from URL (cached across requests)
4. Worker generates audio and returns Base64
5. Client decodes and saves audio file

---

*Last updated: 2026-01-10*
