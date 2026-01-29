from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import json
import os
import re
import signal
import subprocess
import sys
import threading
from datetime import datetime
from typing import Dict, Optional

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "train_uploads")
DATASET_DIR = os.path.join(BASE_DIR, "train_dataset")
OUTPUT_DIR = os.path.join(BASE_DIR, "train_output")

app.config["TRAIN_UPLOAD_FOLDER"] = UPLOAD_DIR
app.config["TRAIN_DATASET_FOLDER"] = DATASET_DIR
app.config["TRAIN_OUTPUT_FOLDER"] = OUTPUT_DIR
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DATASET_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

training_state: Dict[str, Optional[str]] = {
    "status": "idle",
    "current_step": 0,
    "total_steps": 0,
    "current_epoch": 0,
    "total_epochs": 0,
    "loss": None,
    "message": "",
    "started_at": None,
    "finished_at": None,
    "run_name": None,
    "output_dir": None,
    "log_file": None,
    "last_checkpoint": None,
    "error": None,
}

training_process: Optional[subprocess.Popen] = None
state_lock = threading.Lock()
current_dataset_path: Optional[str] = None


STEP_RE = re.compile(r"step\s*[:=]\s*(\d+)", re.IGNORECASE)
EPOCH_RE = re.compile(r"epoch\s*[:=]\s*(\d+)(?:\s*/\s*(\d+))?", re.IGNORECASE)
LOSS_RE = re.compile(r"loss\s*[:=]\s*([0-9.+-eE]+)", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _update_state(**kwargs):
    with state_lock:
        training_state.update(kwargs)


def _clear_directory(path: str):
    if not os.path.exists(path):
        return
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            os.remove(os.path.join(root, name))
        for name in dirs:
            os.rmdir(os.path.join(root, name))


def _validate_dataset(path: str) -> Optional[str]:
    wavs_dir = os.path.join(path, "wavs")
    metadata_path = os.path.join(path, "metadata.csv")
    if not os.path.isdir(wavs_dir):
        return "Missing train_dataset/wavs directory."
    if not os.path.isfile(metadata_path):
        return "Missing train_dataset/metadata.csv."
    return None


def _read_log_tail(path: str, max_chars: int = 2000) -> str:
    if not path or not os.path.isfile(path):
        return ""
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        offset = max(0, size - max_chars)
        handle.seek(offset)
        data = handle.read().decode("utf-8", errors="ignore")
    return data


def _parse_progress(log_text: str) -> Dict[str, Optional[str]]:
    current_step = None
    current_epoch = None
    total_epoch = None
    loss = None

    for line in reversed(log_text.splitlines()):
        if loss is None:
            loss_match = LOSS_RE.search(line)
            if loss_match:
                loss = loss_match.group(1)
        if current_step is None:
            step_match = STEP_RE.search(line)
            if step_match:
                current_step = int(step_match.group(1))
        if current_epoch is None:
            epoch_match = EPOCH_RE.search(line)
            if epoch_match:
                current_epoch = int(epoch_match.group(1))
                if epoch_match.group(2):
                    total_epoch = int(epoch_match.group(2))
        if current_step or current_epoch or loss:
            if current_step is not None and current_epoch is not None and loss is not None:
                break

    updates: Dict[str, Optional[str]] = {}
    if current_step is not None:
        updates["current_step"] = current_step
    if current_epoch is not None:
        updates["current_epoch"] = current_epoch
    if total_epoch is not None:
        updates["total_epochs"] = total_epoch
    if loss is not None:
        try:
            updates["loss"] = float(loss)
        except ValueError:
            updates["loss"] = loss
    return updates


def _find_latest_checkpoint(output_dir: str) -> Optional[str]:
    if not output_dir or not os.path.isdir(output_dir):
        return None
    candidates = []
    for root, _, files in os.walk(output_dir):
        for name in files:
            if name.endswith((".pth", ".pt", ".ckpt")):
                full_path = os.path.join(root, name)
                candidates.append(full_path)
    if not candidates:
        return None
    latest = max(candidates, key=os.path.getmtime)
    return os.path.relpath(latest, output_dir)


def _write_result(
    status: str,
    message: str,
    output_dir: str,
    params: Dict[str, Optional[str]],
    last_checkpoint: Optional[str],
):
    if not output_dir:
        return
    result_path = os.path.join(output_dir, "result.json")
    payload = {
        "status": status,
        "message": message,
        "started_at": training_state.get("started_at"),
        "finished_at": training_state.get("finished_at"),
        "run_name": training_state.get("run_name"),
        "output_dir": output_dir,
        "last_checkpoint": last_checkpoint,
        "params": params,
    }
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _monitor_process(
    proc: subprocess.Popen,
    output_dir: str,
    params: Dict[str, Optional[str]],
    log_handle,
):
    global training_process
    return_code = proc.wait()

    with state_lock:
        current_status = training_state.get("status")

    finished_at = _now_iso()
    if current_status in ("stopping", "stopped"):
        status = "stopped"
        message = "Training stopped by user."
    elif return_code == 0:
        status = "done"
        message = "Training finished successfully."
    else:
        status = "error"
        message = f"Training exited with code {return_code}."

    last_checkpoint = _find_latest_checkpoint(output_dir)
    _update_state(
        status=status,
        finished_at=finished_at,
        message=message,
        last_checkpoint=last_checkpoint,
        error=None if status != "error" else message,
    )
    _write_result(status, message, output_dir, params, last_checkpoint)

    try:
        log_handle.close()
    except Exception:
        pass

    with state_lock:
        training_process = None


def _stop_process(proc: subprocess.Popen):
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


@app.route("/")
def index():
    return render_template("train.html")


@app.route("/upload_dataset", methods=["POST"])
def upload_dataset():
    global current_dataset_path

    if training_state.get("status") == "running":
        return jsonify({"ok": False, "error": "Training is running. Stop it before uploading."}), 400

    if "dataset_zip" not in request.files:
        return jsonify({"ok": False, "error": "No file part 'dataset_zip'."}), 400

    file = request.files["dataset_zip"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "No selected file."}), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    zip_name = secure_filename(file.filename)
    zip_path = os.path.join(UPLOAD_DIR, zip_name)
    file.save(zip_path)

    _clear_directory(DATASET_DIR)
    os.makedirs(DATASET_DIR, exist_ok=True)

    try:
        import zipfile

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(DATASET_DIR)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Failed to extract zip: {exc}"}), 400
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

    error = _validate_dataset(DATASET_DIR)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    current_dataset_path = DATASET_DIR
    return jsonify({"ok": True, "message": "Dataset uploaded and extracted."})


@app.route("/start_training", methods=["POST"])
def start_training():
    global training_process, current_dataset_path

    if current_dataset_path is None:
        return jsonify({"ok": False, "error": "No dataset uploaded yet."}), 400

    if training_state.get("status") == "running":
        return jsonify({"ok": False, "error": "Training already running."}), 400

    error = _validate_dataset(current_dataset_path)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    data = request.get_json() or {}
    run_name = data.get("run_name") or f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    total_steps = data.get("total_steps")
    epochs = data.get("epochs")

    output_dir = os.path.join(OUTPUT_DIR, run_name)
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, "train.log")

    cmd = [
        sys.executable,
        "-u",
        os.path.join(BASE_DIR, "train_xtts_v2.py"),
        "--dataset_dir",
        current_dataset_path,
        "--output_dir",
        output_dir,
        "--run_name",
        run_name,
    ]

    if epochs is not None:
        cmd += ["--epochs", str(int(epochs))]
    if total_steps is not None:
        cmd += ["--max_steps", str(int(total_steps))]

    batch_size = int(data.get("batch_size", 2))
    grad_accum = int(data.get("grad_accum", 1))
    lr = float(data.get("lr", 5e-6))
    mixed_precision = data.get("mixed_precision", "fp16")
    gpu = int(data.get("gpu", 0))

    cmd += [
        "--batch_size",
        str(batch_size),
        "--grad_accum",
        str(grad_accum),
        "--lr",
        str(lr),
        "--mixed_precision",
        str(mixed_precision),
        "--gpu",
        str(gpu),
    ]

    params = {
        "run_name": run_name,
        "total_steps": int(total_steps) if total_steps is not None else None,
        "epochs": int(epochs) if epochs is not None else None,
        "batch_size": batch_size,
        "grad_accum": grad_accum,
        "lr": lr,
        "mixed_precision": mixed_precision,
        "gpu": gpu,
    }

    try:
        log_handle = open(log_path, "a", encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        training_process = subprocess.Popen(
            cmd,
            cwd=BASE_DIR,
            stdout=log_handle,
            stderr=log_handle,
            env=env,
        )
    except Exception as exc:
        try:
            log_handle.close()
        except Exception:
            pass
        _update_state(status="error", message=str(exc), error=str(exc))
        return jsonify({"ok": False, "error": f"Failed to start training: {exc}"}), 500

    _update_state(
        status="running",
        current_step=0,
        total_steps=int(total_steps) if total_steps is not None else 0,
        current_epoch=0,
        total_epochs=int(epochs) if epochs is not None else 0,
        loss=None,
        message="Training started.",
        started_at=_now_iso(),
        finished_at=None,
        run_name=run_name,
        output_dir=output_dir,
        log_file=log_path,
        last_checkpoint=None,
        error=None,
    )

    monitor_thread = threading.Thread(
        target=_monitor_process,
        args=(training_process, output_dir, params, log_handle),
        daemon=True,
    )
    monitor_thread.start()

    return jsonify({"ok": True, "message": f"Training started with run_name={run_name}"})


@app.route("/training_progress", methods=["GET"])
def training_progress():
    with state_lock:
        status = training_state.get("status")
        log_file = training_state.get("log_file")
        response = dict(training_state)

    log_tail = _read_log_tail(log_file)
    if status == "running" and log_tail:
        updates = _parse_progress(log_tail)
        if updates:
            _update_state(**updates)
            response.update(updates)

    response["log_tail"] = log_tail[-2000:] if log_tail else ""
    return jsonify(response)


@app.route("/stop_training", methods=["POST"])
def stop_training():
    global training_process

    with state_lock:
        proc = training_process
        status = training_state.get("status")

    if proc is None or status != "running":
        return jsonify({"ok": False, "error": "No running training process."}), 400

    _update_state(status="stopping", message="Stopping training...")

    stopper = threading.Thread(target=_stop_process, args=(proc,), daemon=True)
    stopper.start()

    return jsonify({"ok": True, "message": "Stop signal sent."})


@app.route("/runs", methods=["GET"])
def list_runs():
    runs = []
    if not os.path.isdir(OUTPUT_DIR):
        return jsonify({"runs": runs})

    for name in sorted(os.listdir(OUTPUT_DIR)):
        run_dir = os.path.join(OUTPUT_DIR, name)
        if not os.path.isdir(run_dir):
            continue
        result_path = os.path.join(run_dir, "result.json")
        result = None
        if os.path.isfile(result_path):
            try:
                with open(result_path, "r", encoding="utf-8") as handle:
                    result = json.load(handle)
            except Exception:
                result = None
        runs.append({
            "run_name": name,
            "output_dir": run_dir,
            "result": result,
        })

    return jsonify({"runs": runs})


@app.route("/download/<run_name>/<path:filename>", methods=["GET"])
def download_file(run_name: str, filename: str):
    run_dir = os.path.join(OUTPUT_DIR, run_name)
    if not os.path.isdir(run_dir):
        return jsonify({"ok": False, "error": "Run not found."}), 404

    requested = os.path.abspath(os.path.join(run_dir, filename))
    if not requested.startswith(os.path.abspath(run_dir)):
        return jsonify({"ok": False, "error": "Invalid path."}), 400

    if not os.path.isfile(requested):
        return jsonify({"ok": False, "error": "File not found."}), 404

    rel_dir = os.path.dirname(os.path.relpath(requested, run_dir))
    return send_from_directory(os.path.join(run_dir, rel_dir), os.path.basename(requested), as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5002)))
