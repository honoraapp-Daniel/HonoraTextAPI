# Change
- Change title: Training Machine V4 (XTTS v2 RunPod training)
- Intent: Replace fake training with real XTTS v2 fine-tuning and RunPod-ready training service.
- Method: Added train_xtts_v2 runner, rewired training_app to start subprocess training with log parsing/stop/results, added RunPod training Dockerfile, and refreshed project status.
- Reason: Enable real GPU training with progress reporting and artifact output on RunPod.
- Files touched: HonoraLocalTTS/train_xtts_v2.py, HonoraLocalTTS/training_app.py, HonoraLocalTTS/Dockerfile.runpod.train, docs/project-status-2026-01-29.md
- Tests: python3 -m py_compile HonoraLocalTTS/training_app.py HonoraLocalTTS/train_xtts_v2.py
- Agent signature: Codex
