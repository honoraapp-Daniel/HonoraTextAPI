"""
Quick TTS Test - Verify XTTS-v2 works locally
"""
import os
import time

print("=" * 50)
print("🎤 Honora TTS Local Test")
print("=" * 50)

# Test text
TEST_TEXT = "Welcome to Honora. This is a test of the text to speech system. The ancient wisdom awaits your discovery."

# Voice reference
VOICE_FILE = "AI Stemmer Honora/AI_Voice_Honora_Brian.wav"
OUTPUT_FILE = "output/test_output.wav"

# Ensure output folder exists
os.makedirs("output", exist_ok=True)

print(f"\n📝 Text: {TEST_TEXT}")
print(f"🎙️ Voice: {VOICE_FILE}")
print(f"💾 Output: {OUTPUT_FILE}")

print("\n⏳ Loading XTTS-v2 model (this may take a minute on first run)...")
start = time.time()

try:
    from TTS.api import TTS
    
    # Load model (CPU mode for local testing)
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")
    
    load_time = time.time() - start
    print(f"✅ Model loaded in {load_time:.1f} seconds")
    
    print("\n🔊 Generating audio...")
    gen_start = time.time()
    
    tts.tts_to_file(
        text=TEST_TEXT,
        speaker_wav=VOICE_FILE,
        language="en",
        file_path=OUTPUT_FILE
    )
    
    gen_time = time.time() - gen_start
    print(f"✅ Audio generated in {gen_time:.1f} seconds")
    
    # Check file size
    size = os.path.getsize(OUTPUT_FILE)
    print(f"📁 Output file size: {size / 1024:.1f} KB")
    
    print("\n" + "=" * 50)
    print("🎉 SUCCESS! Audio saved to:", OUTPUT_FILE)
    print("=" * 50)
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
