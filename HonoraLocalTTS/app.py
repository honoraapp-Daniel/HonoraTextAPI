from flask import Flask, render_template, request, send_file, Response, stream_with_context
import os
import zipfile
import shutil
import json
import time
from TTS.api import TTS

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["OUTPUT_FOLDER"] = "output"

# Ensure folders exist
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)

voice_path = None
book_path = None
is_zip_upload = False

# Progress tracking
progress_data = {"current": 0, "total": 0, "filename": "", "status": "idle"}

# Load XTTS models (only once at startup)
MODELS = {}

# Default clone model (XTTS v2 off-the-shelf)
MODELS["clone"] = TTS(
    model_name="tts_models/multilingual/multi-dataset/xtts_v2",
    gpu=False
)

# Fine-tuned Frederick model (if available)
frederick_model_path = "runs/frederick"
if os.path.exists(frederick_model_path) and os.path.exists(os.path.join(frederick_model_path, "config.json")):
    try:
        MODELS["own"] = TTS(
            model_path=frederick_model_path,
            config_path=os.path.join(frederick_model_path, "config.json"),
            gpu=False
        )
        print("✓ Frederick model loaded successfully")
    except Exception as e:
        print(f"Warning: Could not load Frederick model: {e}")
else:
    print("Note: Frederick model not found at runs/frederick/ - only clone voice available")

DEFAULT_MODEL = "clone"


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/upload_voice", methods=["POST"])
def upload_voice():
    global voice_path

    file = request.files.get("voice_file")
    if not file:
        return "No file received."

    voice_path = os.path.join(app.config["UPLOAD_FOLDER"], "voice.wav")
    file.save(voice_path)

    return "Voice uploaded successfully!"


@app.route("/upload_book", methods=["POST"])
def upload_book():
    global book_path, is_zip_upload

    file = request.files.get("book_file")
    if not file:
        return "No file received."

    filename = file.filename
    if filename.endswith(".zip"):
        book_path = os.path.join(app.config["UPLOAD_FOLDER"], "book.zip")
        is_zip_upload = True
    else:
        book_path = os.path.join(app.config["UPLOAD_FOLDER"], "book.txt")
        is_zip_upload = False
    
    file.save(book_path)

    return "Book uploaded successfully!"


@app.route("/progress")
def progress():
    def generate():
        global progress_data
        while True:
            # Send current progress as SSE event
            yield f"data: {json.dumps(progress_data)}\n\n"
            time.sleep(0.5)  # Update every 500ms
            
            # Stop streaming when complete
            if progress_data["status"] == "complete":
                break
    
    return Response(stream_with_context(generate()), mimetype="text/event-stream")



@app.route("/generate", methods=["POST"])
def generate_audio():
    global voice_path, book_path, is_zip_upload, progress_data

    # Get selected model (default to "clone" if not specified)
    model_key = request.form.get("model", DEFAULT_MODEL)
    
    # Validate model exists
    if model_key not in MODELS:
        return f"Invalid model selected: {model_key}", 400

    if not voice_path or not os.path.exists(voice_path):
        return "No voice file uploaded."

    if not book_path or not os.path.exists(book_path):
        return "No book uploaded."

    # Clean output folder
    if os.path.exists(app.config["OUTPUT_FOLDER"]):
        shutil.rmtree(app.config["OUTPUT_FOLDER"])
    os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)

    if is_zip_upload:
        # Handle ZIP batch processing
        progress_data = {"current": 0, "total": 0, "filename": "", "status": "processing", "model": model_key}
        
        extract_folder = os.path.join(app.config["UPLOAD_FOLDER"], "extracted_book")
        if os.path.exists(extract_folder):
            shutil.rmtree(extract_folder)
        os.makedirs(extract_folder, exist_ok=True)

        with zipfile.ZipFile(book_path, 'r') as zip_ref:
            zip_ref.extractall(extract_folder)

        # Count total text files first
        txt_files = []
        for root, dirs, files in os.walk(extract_folder):
            for file in files:
                if file.endswith(".txt"):
                    txt_files.append(os.path.join(root, file))
        
        progress_data["total"] = len(txt_files)
        
        # Process each text file
        generated_files = []
        for idx, txt_path in enumerate(txt_files, 1):
            file = os.path.basename(txt_path)
            
            # Try multiple encodings
            text = None
            for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
                try:
                        with open(txt_path, "r", encoding=encoding) as f:
                            text = f.read()
                        break
                except (UnicodeDecodeError, LookupError):
                    continue
            
            if text is None:
                print(f"Skipping {file} - unable to decode")
                continue
            
            if not text.strip():
                continue

            # Output filename same as input but .wav
            wav_filename = os.path.splitext(file)[0] + ".wav"
            output_path = os.path.join(app.config["OUTPUT_FOLDER"], wav_filename)
            
            # Update progress
            progress_data["current"] = idx
            progress_data["filename"] = wav_filename
            
            print(f"Generating {wav_filename}...")
            MODELS[model_key].tts_to_file(
                text=text,
                speaker_wav=voice_path,
                language="en",
                file_path=output_path
            )
            generated_files.append(output_path)

        # Create result ZIP
        print(f"Total files generated: {len(generated_files)}")
        result_zip_path = os.path.join(app.config["UPLOAD_FOLDER"], "audiobooks.zip")
        with zipfile.ZipFile(result_zip_path, 'w') as zipf:
            for file in generated_files:
                print(f"Adding to ZIP: {file}")
                zipf.write(file, os.path.basename(file))
        
        print(f"ZIP created at: {result_zip_path}")
        progress_data["status"] = "complete"
        return send_file(result_zip_path, as_attachment=True, download_name="audiobooks.zip")

    else:
        # Handle single file processing
        progress_data = {"current": 1, "total": 1, "filename": "audiobook.wav", "status": "processing", "model": model_key}
        
        with open(book_path, "r", encoding="utf-8") as f:
            text = f.read()

        output_path = os.path.join(app.config["OUTPUT_FOLDER"], "audiobook.wav")

        print(f"Generating audiobook.wav...")
        MODELS[model_key].tts_to_file(
            text=text,
            speaker_wav=voice_path,
            language="en",
            file_path=output_path
        )
        
        # Create ZIP even for single file (for consistency)
        result_zip_path = os.path.join(app.config["UPLOAD_FOLDER"], "audiobooks.zip")
        with zipfile.ZipFile(result_zip_path, 'w') as zipf:
            zipf.write(output_path, os.path.basename(output_path))
        
        print(f"ZIP created at: {result_zip_path}")
        progress_data["status"] = "complete"
        return send_file(result_zip_path, as_attachment=True, download_name="audiobooks.zip")


if __name__ == "__main__":
    app.run(debug=True)

