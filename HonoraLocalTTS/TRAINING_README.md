# Honora Training Dashboard

Train custom XTTS-v2 voices for audiobook narration.

## Quick Start

```bash
cd HonoraLocalTTS

# Terminal 1: TTS Dashboard (port 5001)
source .venv-tts/bin/activate
python tts_dashboard.py

# Terminal 2: Training Dashboard (port 5002)
source .venv-tts/bin/activate
python training_dashboard.py
```

## Usage

1. **Upload Dataset**: Go to http://localhost:5002/new-training
   - Upload a ZIP with WAV+TXT pairs (e.g., `sample_001.wav` + `sample_001.txt`)
   
2. **Start Training**: Configure epochs/batch size, click "Start Training"

3. **Monitor**: View live logs on the run detail page, cancel if needed

4. **Use Voice**: After training, the voice auto-registers.
   - Open http://localhost:5001 and select the new voice from dropdown

## Dataset Format

ZIP file containing:
```
my_voice/
├── sample_001.wav  # 1-11 seconds, 22050 Hz
├── sample_001.txt  # Transcript
├── sample_002.wav
├── sample_002.txt
└── ...
```

## Files

```
HonoraLocalTTS/
├── training_dashboard.py   # Flask app (port 5002)
├── training_runner.py      # Subprocess manager
├── training_db.py          # SQLite layer
├── train_xtts.py           # Training script
├── voice_registry.json     # Shared voice list
├── tts_engines.py          # Modified to read registry
├── train_uploads/          # Uploaded ZIPs
├── train_dataset/          # Extracted datasets
├── train_output/           # Training outputs
└── train_logs/             # Log files
```
