"""
Minimal TTS Dashboard for debugging
"""
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return "TTS Dashboard is working!"

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/test")
def test():
    return "Test route works!"

if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
