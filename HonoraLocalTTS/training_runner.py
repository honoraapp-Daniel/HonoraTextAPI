"""
Training Runner
Manages XTTS-v2 training as subprocess with real-time log capture
"""

import os
import re
import json
import time
import signal
import subprocess
import threading
from datetime import datetime
from typing import Optional, Callable
import uuid

import training_db as db

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PATH = os.path.join(BASE_DIR, ".venv-tts")
TRAIN_SCRIPT = os.path.join(BASE_DIR, "train_xtts.py")
LOGS_DIR = os.path.join(BASE_DIR, "train_logs")
REGISTRY_PATH = os.path.join(BASE_DIR, "voice_registry.json")

os.makedirs(LOGS_DIR, exist_ok=True)


class TrainingRunner:
    """Manages a single training run as subprocess"""
    
    # Progress parsing patterns
    STEP_PATTERN = re.compile(r'STEP:\s*(\d+)/(\d+)', re.IGNORECASE)
    EPOCH_PATTERN = re.compile(r'EPOCH:\s*(\d+)/(\d+)', re.IGNORECASE)
    LOSS_PATTERN = re.compile(r'loss[=:]\s*([\d.]+)', re.IGNORECASE)
    
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.current_run_id: Optional[str] = None
        self.log_file = None
        self.log_lines = []
        self._stop_event = threading.Event()
        self._log_thread: Optional[threading.Thread] = None
        self._callbacks = []
    
    def is_running(self) -> bool:
        """Check if training is currently running"""
        return self.process is not None and self.process.poll() is None
    
    def add_log_callback(self, callback: Callable[[str], None]):
        """Add callback for new log lines"""
        self._callbacks.append(callback)
    
    def remove_log_callback(self, callback: Callable[[str], None]):
        """Remove log callback"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def start(
        self,
        run_id: str,
        train_csv: str,
        eval_csv: str,
        output_path: str,
        num_epochs: int = 10,
        batch_size: int = 2,
        language: str = "en"
    ) -> bool:
        """Start training subprocess"""
        if self.is_running():
            return False
        
        self.current_run_id = run_id
        self.log_lines = []
        self._stop_event.clear()
        
        # Open log file
        log_path = os.path.join(LOGS_DIR, f"{run_id}.log")
        self.log_file = open(log_path, "w")
        
        # Build command
        python_path = os.path.join(VENV_PATH, "bin", "python3")
        cmd = [
            python_path,
            TRAIN_SCRIPT,
            "--train_csv", train_csv,
            "--eval_csv", eval_csv,
            "--output_path", output_path,
            "--num_epochs", str(num_epochs),
            "--batch_size", str(batch_size),
            "--language", language,
        ]
        
        self._log(f"Starting training: {' '.join(cmd)}")
        
        # Update DB
        db.update_run(run_id, status="running", started_at=datetime.utcnow().isoformat(), total_epochs=num_epochs)
        
        # Start process
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=BASE_DIR,
                env={**os.environ, "PYTHONUNBUFFERED": "1"}
            )
        except Exception as e:
            self._log(f"Failed to start process: {e}")
            db.update_run(run_id, status="failed", error=str(e), ended_at=datetime.utcnow().isoformat())
            return False
        
        # Start log capture thread
        self._log_thread = threading.Thread(target=self._capture_logs, daemon=True)
        self._log_thread.start()
        
        return True
    
    def _log(self, line: str):
        """Write to log file and notify callbacks"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {line}"
        
        self.log_lines.append(formatted)
        
        if self.log_file:
            self.log_file.write(formatted + "\n")
            self.log_file.flush()
        
        for callback in self._callbacks:
            try:
                callback(formatted)
            except:
                pass
    
    def _capture_logs(self):
        """Capture logs from subprocess stdout"""
        if not self.process:
            return
        
        try:
            for line in iter(self.process.stdout.readline, ''):
                if self._stop_event.is_set():
                    break
                
                line = line.rstrip()
                if line:
                    self._log(line)
                    self._parse_progress(line)
            
            # Process finished
            self.process.wait()
            exit_code = self.process.returncode
            
            self._log(f"Training process exited with code {exit_code}")
            
            if exit_code == 0:
                db.update_run(
                    self.current_run_id,
                    status="completed",
                    exit_code=exit_code,
                    ended_at=datetime.utcnow().isoformat()
                )
                self._register_voice()
            elif exit_code == -signal.SIGTERM or exit_code == -signal.SIGINT:
                db.update_run(
                    self.current_run_id,
                    status="cancelled",
                    exit_code=exit_code,
                    ended_at=datetime.utcnow().isoformat()
                )
            else:
                db.update_run(
                    self.current_run_id,
                    status="failed",
                    exit_code=exit_code,
                    error=f"Process exited with code {exit_code}",
                    ended_at=datetime.utcnow().isoformat()
                )
        
        except Exception as e:
            self._log(f"Error capturing logs: {e}")
            db.update_run(
                self.current_run_id,
                status="failed",
                error=str(e),
                ended_at=datetime.utcnow().isoformat()
            )
        finally:
            if self.log_file:
                self.log_file.close()
                self.log_file = None
            self.process = None
    
    def _parse_progress(self, line: str):
        """Parse progress from log line"""
        run_id = self.current_run_id
        if not run_id:
            return
        
        updates = {}
        
        # Parse step
        step_match = self.STEP_PATTERN.search(line)
        if step_match:
            updates["progress_step"] = int(step_match.group(1))
            updates["progress_total"] = int(step_match.group(2))
        
        # Parse epoch
        epoch_match = self.EPOCH_PATTERN.search(line)
        if epoch_match:
            updates["current_epoch"] = int(epoch_match.group(1))
            updates["total_epochs"] = int(epoch_match.group(2))
        
        # Parse loss
        loss_match = self.LOSS_PATTERN.search(line)
        if loss_match:
            try:
                updates["current_loss"] = float(loss_match.group(1))
            except:
                pass
        
        if updates:
            db.update_run(run_id, **updates)
    
    def _register_voice(self):
        """Register trained voice to shared registry"""
        run = db.get_run(self.current_run_id)
        if not run:
            return
        
        voice_name = run.get("voice_name", "Trained Voice")
        output_path = run.get("output_path", "")
        
        # Find the best model checkpoint
        trainer_output = os.path.join(output_path, "run", "training")
        checkpoint_path = None
        config_path = None
        vocab_path = None
        speaker_ref = None
        
        # Look for best_model.pth in trainer output
        for root, dirs, files in os.walk(trainer_output):
            for f in files:
                if f == "best_model.pth":
                    checkpoint_path = os.path.join(root, f)
                elif f == "config.json" and not config_path:
                    config_path = os.path.join(root, f)
                elif f == "vocab.json" and not vocab_path:
                    vocab_path = os.path.join(root, f)
        
        # Look for speaker reference from dataset
        dataset_path = run.get("dataset_path", "")
        if os.path.exists(dataset_path):
            for f in os.listdir(dataset_path):
                if f.endswith(".wav"):
                    speaker_ref = os.path.join(dataset_path, f)
                    break
        
        if not checkpoint_path:
            self._log("Warning: Could not find trained checkpoint")
            return
        
        # Load existing registry
        registry = {"voices": []}
        if os.path.exists(REGISTRY_PATH):
            try:
                with open(REGISTRY_PATH, "r") as f:
                    registry = json.load(f)
            except:
                pass
        
        # Add new voice
        voice_entry = {
            "id": self.current_run_id,
            "name": voice_name,
            "type": "trained",
            "checkpoint_path": checkpoint_path,
            "config_path": config_path,
            "vocab_path": vocab_path,
            "speaker_wav": speaker_ref,
            "language": run.get("config", {}).get("language", "en") if isinstance(run.get("config"), dict) else "en",
            "created_at": datetime.utcnow().isoformat(),
            "training_run_id": self.current_run_id
        }
        
        # Remove existing voice with same run_id if any
        registry["voices"] = [v for v in registry["voices"] if v.get("id") != self.current_run_id]
        registry["voices"].append(voice_entry)
        
        # Atomic write
        temp_path = REGISTRY_PATH + ".tmp"
        with open(temp_path, "w") as f:
            json.dump(registry, f, indent=2)
        os.replace(temp_path, REGISTRY_PATH)
        
        self._log(f"Voice registered: {voice_name}")
    
    def cancel(self) -> bool:
        """Cancel running training"""
        if not self.is_running():
            return False
        
        self._log("Cancelling training...")
        self._stop_event.set()
        
        try:
            self.process.terminate()
            # Give it a few seconds to cleanup
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        except Exception as e:
            self._log(f"Error cancelling: {e}")
            return False
        
        return True
    
    def get_logs(self, start_index: int = 0) -> list:
        """Get log lines from index"""
        return self.log_lines[start_index:]


# Global runner instance (single training at a time)
runner = TrainingRunner()
