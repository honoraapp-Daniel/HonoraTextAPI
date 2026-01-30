"""
Honora Training Dashboard
Flask app for XTTS-v2 voice training on port 5005
"""

import os
import json
import uuid
import zipfile
import shutil
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, send_file

# Load environment variables
from dotenv import load_dotenv
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import training_db as db
from training_runner import runner

app = Flask(__name__)

# Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "train_uploads")
DATASET_DIR = os.path.join(BASE_DIR, "train_dataset")
OUTPUT_DIR = os.path.join(BASE_DIR, "train_output")
LOGS_DIR = os.path.join(BASE_DIR, "train_logs")
REGISTRY_PATH = os.path.join(BASE_DIR, "voice_registry.json")

for d in [UPLOAD_DIR, DATASET_DIR, OUTPUT_DIR, LOGS_DIR]:
    os.makedirs(d, exist_ok=True)


# =============================================================================
# PAGES
# =============================================================================

@app.route("/")
def index():
    """Redirect to voices page"""
    return redirect(url_for("voices_page"))


@app.route("/voices")
def voices_page():
    """List all trained voices and runs"""
    return render_template("training_dashboard.html", page="voices")


@app.route("/new-training")
def new_training_page():
    """Upload and configure new training"""
    return render_template("training_dashboard.html", page="new-training")


@app.route("/guide")
def guide_page():
    """Training guide and documentation"""
    return render_template("training_dashboard.html", page="guide")


@app.route("/runs/<run_id>")
def run_detail_page(run_id):
    """Training run detail with logs"""
    return render_template("training_dashboard.html", page="run-detail", run_id=run_id)


# =============================================================================
# API - Voices & Runs
# =============================================================================

@app.route("/api/voices")
def get_voices():
    """Get all registered voices"""
    registry = {"voices": []}
    if os.path.exists(REGISTRY_PATH):
        try:
            with open(REGISTRY_PATH, "r") as f:
                registry = json.load(f)
        except:
            pass
    return jsonify(registry.get("voices", []))


@app.route("/api/runs")
def get_runs():
    """Get all training runs"""
    runs = db.get_all_runs()
    # Parse config JSON
    for run in runs:
        if run.get("config") and isinstance(run["config"], str):
            try:
                run["config"] = json.loads(run["config"])
            except:
                pass
    return jsonify(runs)


@app.route("/api/runs/<run_id>")
def get_run(run_id):
    """Get a single training run"""
    run = db.get_run(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
    if run.get("config") and isinstance(run["config"], str):
        try:
            run["config"] = json.loads(run["config"])
        except:
            pass
    return jsonify(run)


@app.route("/api/runs/<run_id>/status")
def get_run_status(run_id):
    """Get run status with progress"""
    run = db.get_run(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
    
    return jsonify({
        "id": run["id"],
        "status": run["status"],
        "progress_step": run.get("progress_step", 0),
        "progress_total": run.get("progress_total", 0),
        "current_epoch": run.get("current_epoch", 0),
        "total_epochs": run.get("total_epochs", 0),
        "current_loss": run.get("current_loss"),
        "is_running": runner.is_running() and runner.current_run_id == run_id
    })


# =============================================================================
# API - Upload
# =============================================================================

@app.route("/api/upload", methods=["POST"])
def upload_dataset():
    """Upload and extract dataset ZIP"""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    
    voice_name = request.form.get("voice_name", "Custom Voice")
    
    # Create unique ID for this dataset
    dataset_id = str(uuid.uuid4())[:8]
    dataset_path = os.path.join(DATASET_DIR, dataset_id)
    os.makedirs(dataset_path, exist_ok=True)
    
    # Save ZIP
    zip_path = os.path.join(UPLOAD_DIR, f"{dataset_id}.zip")
    file.save(zip_path)
    
    # Extract
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dataset_path)
    except Exception as e:
        return jsonify({"error": f"Failed to extract ZIP: {e}"}), 400
    
    # Find WAV and TXT pairs (skip macOS metadata)
    wav_files = []
    txt_files = []
    
    for root, dirs, files in os.walk(dataset_path):
        # Skip __MACOSX directories
        if '__MACOSX' in root:
            continue
        for f in files:
            # Skip macOS metadata files
            if f.startswith('._') or f == '.DS_Store':
                continue
            path = os.path.join(root, f)
            if f.lower().endswith(".wav"):
                wav_files.append(path)
            elif f.lower().endswith(".txt"):
                txt_files.append(path)
    
    # Match pairs by filename (skip long text - XTTS limit is 250 chars)
    MAX_TEXT_LENGTH = 240
    pairs = []
    skipped_long = []
    
    for wav in wav_files:
        base = os.path.splitext(os.path.basename(wav))[0]
        # Look for matching txt
        for txt in txt_files:
            txt_base = os.path.splitext(os.path.basename(txt))[0]
            if txt_base == base:
                # Try multiple encodings
                text = None
                for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
                    try:
                        with open(txt, "r", encoding=encoding) as f:
                            text = f.read().strip()
                        break
                    except UnicodeDecodeError:
                        continue
                if text:
                    # Check text length - XTTS requires < 250 chars
                    if len(text) > MAX_TEXT_LENGTH:
                        skipped_long.append({"file": base, "length": len(text)})
                    else:
                        pairs.append({"audio_file": wav, "text": text})
                break
    
    if not pairs:
        error_msg = "No valid WAV+TXT pairs found"
        if skipped_long:
            error_msg += f". {len(skipped_long)} samples were skipped because text exceeds {MAX_TEXT_LENGTH} chars limit"
        return jsonify({"error": error_msg}), 400
    
    # Create CSV files
    train_csv = os.path.join(dataset_path, "train.csv")
    eval_csv = os.path.join(dataset_path, "eval.csv")
    
    # Split 90/10
    split_idx = max(1, int(len(pairs) * 0.9))
    train_pairs = pairs[:split_idx]
    eval_pairs = pairs[split_idx:] if split_idx < len(pairs) else pairs[:1]
    
    def write_csv(path, items):
        with open(path, "w", encoding="utf-8") as f:
            f.write("audio_file|text|speaker_name\n")
            for item in items:
                text = item["text"].replace("|", " ").replace("\n", " ")
                f.write(f"{item['audio_file']}|{text}|{voice_name}\n")
    
    write_csv(train_csv, train_pairs)
    write_csv(eval_csv, eval_pairs)
    
    return jsonify({
        "dataset_id": dataset_id,
        "dataset_path": dataset_path,
        "train_csv": train_csv,
        "eval_csv": eval_csv,
        "total_pairs": len(pairs),
        "train_count": len(train_pairs),
        "eval_count": len(eval_pairs),
        "voice_name": voice_name,
        "skipped_long_text": len(skipped_long),
        "skipped_files": [s["file"] for s in skipped_long] if skipped_long else []
    })


# =============================================================================
# API - Training Control
# =============================================================================

@app.route("/api/start", methods=["POST"])
def start_training():
    """Start a new training run"""
    if runner.is_running():
        return jsonify({"error": "Training already in progress"}), 400
    
    data = request.json or {}
    
    voice_name = data.get("voice_name", "Custom Voice")
    dataset_path = data.get("dataset_path")
    train_csv = data.get("train_csv")
    eval_csv = data.get("eval_csv")
    num_epochs = int(data.get("num_epochs", 10))
    batch_size = int(data.get("batch_size", 2))
    language = data.get("language", "en")
    
    if not train_csv or not eval_csv:
        return jsonify({"error": "Missing train_csv or eval_csv"}), 400
    
    # Create run
    run_id = str(uuid.uuid4())
    output_path = os.path.join(OUTPUT_DIR, run_id)
    os.makedirs(output_path, exist_ok=True)
    
    config = {
        "num_epochs": num_epochs,
        "batch_size": batch_size,
        "language": language
    }
    
    db.create_run(run_id, voice_name, config, dataset_path, output_path)
    
    # Start training
    success = runner.start(
        run_id=run_id,
        train_csv=train_csv,
        eval_csv=eval_csv,
        output_path=output_path,
        num_epochs=num_epochs,
        batch_size=batch_size,
        language=language
    )
    
    if not success:
        return jsonify({"error": "Failed to start training"}), 500
    
    return jsonify({
        "run_id": run_id,
        "status": "running"
    })


@app.route("/api/runs/<run_id>/cancel", methods=["POST"])
def cancel_training(run_id):
    """Cancel a running training"""
    if not runner.is_running() or runner.current_run_id != run_id:
        return jsonify({"error": "This run is not active"}), 400
    
    success = runner.cancel()
    return jsonify({"success": success})


# =============================================================================
# API - Logs (SSE)
# =============================================================================

@app.route("/api/runs/<run_id>/logs")
def stream_logs(run_id):
    """Stream logs via Server-Sent Events"""
    
    def generate():
        last_index = 0
        while True:
            # Check if this run is active
            is_active = runner.is_running() and runner.current_run_id == run_id
            
            # Get new log lines
            if is_active:
                new_lines = runner.get_logs(last_index)
                for line in new_lines:
                    yield f"data: {json.dumps({'line': line})}\n\n"
                    last_index += 1
            else:
                # Load from file if run is complete
                log_path = os.path.join(LOGS_DIR, f"{run_id}.log")
                if os.path.exists(log_path) and last_index == 0:
                    with open(log_path, "r") as f:
                        for line in f:
                            yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"
                            last_index += 1
                
                # Send status update
                run = db.get_run(run_id)
                if run:
                    yield f"data: {json.dumps({'status': run['status']})}\n\n"
                
                # If not running and we've sent all logs, end stream
                if not is_active:
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    break
            
            import time
            time.sleep(0.5)
    
    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/runs/<run_id>/logs/download")
def download_logs(run_id):
    """Download log file"""
    log_path = os.path.join(LOGS_DIR, f"{run_id}.log")
    if not os.path.exists(log_path):
        return jsonify({"error": "Log file not found"}), 404
    return send_file(log_path, as_attachment=True, download_name=f"training_{run_id}.log")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("Honora Training Dashboard")
    print("http://localhost:5005")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5005, debug=True, threaded=True)
