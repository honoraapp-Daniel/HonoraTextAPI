from flask import Flask, render_template, request, jsonify
import os
import zipfile
import threading
import time
from datetime import datetime

app = Flask(__name__)
app.config["TRAIN_UPLOAD_FOLDER"] = "train_uploads"
app.config["TRAIN_DATASET_FOLDER"] = "train_dataset"
app.config["TRAIN_OUTPUT_FOLDER"] = "train_output"

os.makedirs(app.config["TRAIN_UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["TRAIN_DATASET_FOLDER"], exist_ok=True)
os.makedirs(app.config["TRAIN_OUTPUT_FOLDER"], exist_ok=True)

training_state = {
    "status": "idle",
    "current_step": 0,
    "total_steps": 0,
    "loss": None,
    "message": "",
    "started_at": None,
    "finished_at": None,
    "run_name": None,
}

current_dataset_path = None


def fake_xtts_training_loop(dataset_path: str, output_path: str, steps: int = 100):
    global training_state

    training_state["status"] = "running"
    training_state["current_step"] = 0
    training_state["total_steps"] = steps
    training_state["message"] = f"Training on dataset: {dataset_path}"
    training_state["started_at"] = datetime.utcnow().isoformat()

    try:
        for step in range(1, steps + 1):
            time.sleep(0.5)  # simulates work

            training_state["current_step"] = step
            training_state["loss"] = round(2.0 / step, 4)
            training_state["message"] = f"Step {step}/{steps}"

        training_state["status"] = "done"
        training_state["finished_at"] = datetime.utcnow().isoformat()
        training_state["message"] = f"Training finished. Model saved to {output_path}"
    except Exception as e:
        training_state["status"] = "error"
        training_state["message"] = f"Error: {e}"


@app.route("/")
def index():
    return render_template("train.html")


@app.route("/upload_dataset", methods=["POST"])
def upload_dataset():
    global current_dataset_path

    if "dataset_zip" not in request.files:
        return jsonify({"ok": False, "error": "No file part 'dataset_zip'."}), 400

    file = request.files["dataset_zip"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "No selected file."}), 400

    zip_path = os.path.join(app.config["TRAIN_UPLOAD_FOLDER"], file.filename)
    file.save(zip_path)

    if os.path.exists(app.config["TRAIN_DATASET_FOLDER"]):
        for root, dirs, files in os.walk(app.config["TRAIN_DATASET_FOLDER"], topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

    os.makedirs(app.config["TRAIN_DATASET_FOLDER"], exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(app.config["TRAIN_DATASET_FOLDER"])

    current_dataset_path = app.config["TRAIN_DATASET_FOLDER"]

    return jsonify({"ok": True, "message": "Dataset uploaded and extracted."})


@app.route("/start_training", methods=["POST"])
def start_training():
    global current_dataset_path, training_state

    if current_dataset_path is None:
        return jsonify({"ok": False, "error": "No dataset uploaded yet."}), 400

    if training_state["status"] == "running":
        return jsonify({"ok": False, "error": "Training already running."}), 400

    data = request.get_json() or {}
    run_name = data.get("run_name", f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}")
    total_steps = int(data.get("total_steps", 100))

    output_dir = os.path.join(app.config["TRAIN_OUTPUT_FOLDER"], run_name)
    os.makedirs(output_dir, exist_ok=True)

    training_state.update({
        "status": "running",
        "current_step": 0,
        "total_steps": total_steps,
        "loss": None,
        "message": "Starting training...",
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "run_name": run_name,
    })

    t = threading.Thread(
        target=fake_xtts_training_loop,
        args=(current_dataset_path, output_dir, total_steps),
        daemon=True,
    )
    t.start()

    return jsonify({"ok": True, "message": f"Training started with run_name={run_name}"})


@app.route("/training_progress", methods=["GET"])
def training_progress():
    return jsonify(training_state)


if __name__ == "__main__":
    app.run(debug=True, port=5001)

