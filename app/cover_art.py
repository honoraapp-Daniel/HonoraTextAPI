"""
Cover art generation module for Honora.
Generates artistic book cover images using Nano Banana (via Kie.ai API).
Nano Banana handles the title and author text directly.
Generates 16:9 image then crops to 1:1 and 2:3 variants.
"""
import os
import requests
import uuid
import time
import json
from io import BytesIO
from PIL import Image
from openai import OpenAI

# ... (rest of imports)

def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set")
    return OpenAI(api_key=api_key)


def generate_with_dalle(metadata: dict, upload: bool = True) -> dict:
    """Fallback generator using DALL-E 3."""
    client = get_openai_client()
    title = metadata.get("title", "Untitled")
    print(f"[COVER ART] ⚠️ Using DALL-E 3 fallback for: {title}")

    # Simplified prompt for DALL-E (asks for NO text, as DALL-E isn't great at it)
    prompt = f"""Book cover artwork for "{title}". 
    Genre: {metadata.get('category', 'General')}. 
    Synopsis: {metadata.get('synopsis', '')[:200]}.
    Style: Professional, artistic, high quality, minimal text.
    Do NOT include the book title or author name text on the image, just the artwork."""

    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        
        image_url = response.data[0].url
        print(f"[COVER ART] ✅ DALL-E image generated!")
        
        urls = {}
        if not upload:
            urls["cover_art_url"] = image_url
            urls["cover_art_url_16x9"] = image_url
            return urls
            
        # Process and upload (Reuse similar logic)
        return process_and_upload_image(image_url, metadata, urls)
        
    except Exception as e:
        raise Exception(f"DALL-E fallback also failed: {e}")


def process_and_upload_image(image_url: str, metadata: dict, urls: dict) -> dict:
    """Shared helper to download, crop, and upload image from URL."""
    print("[COVER ART] Downloading artwork...")
    image_response = requests.get(image_url)
    if image_response.status_code != 200:
        raise Exception(f"Failed to download image: {image_response.status_code}")
    
    # Open image with PIL
    original = Image.open(BytesIO(image_response.content)).convert("RGB")
    width, height = original.size
    
    # Create cropped versions
    # For DALL-E (1:1 source), we crop to 16:9 (center) and keep 1:1
    # For Kie/Nano (16:9 source), we keep 16:9 and crop to 1:1
    
    is_landscape = width > height
    
    if is_landscape:
        img_16x9 = original
        img_1x1 = crop_to_aspect_ratio(original, 1.0)
    else:
        # Source is Square (DALL-E) or Portrait. Create 16:9 by cropping center voltage
        # Actually DALL-E 3 is usually 1024x1024. 
        # Making 16:9 from square means CROPPING top/bottom heavily.
        img_1x1 = original
        
        target_ratio_16_9 = 16/9
        # To get 16:9 from 1:1, we actually lose image data.
        # Alternatively, we can't make 16:9 from 1:1 easily without losing top/bottom.
        # Let's just crop to 16:9 center.
        new_height = int(width / target_ratio_16_9)
        top = (height - new_height) // 2
        img_16x9 = original.crop((0, top, width, top + new_height))

    # Upload to Supabase Storage
    supabase = get_supabase()
    book_id = metadata.get("book_id", str(uuid.uuid4()))
    
    # Upload 16:9
    buffer = BytesIO()
    img_16x9.save(buffer, format="PNG")
    buffer.seek(0)
    file_name_16x9 = f"covers/{book_id}_16x9.png"
    supabase.storage.from_("audio").upload(
        file_name_16x9,
        buffer.getvalue(),
        {"content-type": "image/png", "x-upsert": "true"}
    )
    urls["cover_art_url_16x9"] = supabase.storage.from_("audio").get_public_url(file_name_16x9)
    
    # Upload 1:1
    buffer = BytesIO()
    img_1x1.save(buffer, format="PNG")
    buffer.seek(0)
    file_name_1x1 = f"covers/{book_id}_1x1.png"
    supabase.storage.from_("audio").upload(
        file_name_1x1,
        buffer.getvalue(),
        {"content-type": "image/png", "x-upsert": "true"}
    )
    urls["cover_art_url"] = supabase.storage.from_("audio").get_public_url(file_name_1x1)
    
    print("[COVER ART] ✅ Upload complete! 2 cover versions uploaded")
    return urls


def generate_cover_image(metadata: dict, upload: bool = True) -> dict:
    """
    Generates book cover artwork.
    Tries Kie.ai (Nano Banana) first.
    Fallbacks to DALL-E 3 if Kie.ai fails (e.g. no credits).
    """
    try:
        return generate_with_kie(metadata, upload)
    except Exception as e:
        print(f"[COVER ART] ❌ Kie.ai extraction failed: {e}")
        print("[COVER ART] 🔄 Switching to DALL-E fallback...")
        return generate_with_dalle(metadata, upload)


def generate_with_kie(metadata: dict, upload: bool = True) -> dict:
    """Original Kie.ai generation logic."""
    prompt = generate_cover_art_prompt(metadata)
    title = metadata.get("title", "Untitled")
    
    print(f"[COVER ART] Generating artwork for: {title}")
    print(f"[COVER ART] Using Nano Banana via Kie.ai API...")
    
    api_key = get_kie_api_key()
    
    # Create image generation task
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": KIE_MODEL,
        "input": {
            "prompt": prompt,
            "output_format": "png",
            "image_size": "16:9"
        }
    }
    
    # Submit task to Kie.ai
    create_response = requests.post(
        f"{KIE_API_BASE}/createTask",
        headers=headers,
        json=payload
    )
    
    if create_response.status_code != 200:
        raise Exception(f"Kie.ai API error: {create_response.status_code} - {create_response.text}")
    
    create_data = create_response.json()
    
    # Safe extraction of taskId
    data_obj = create_data.get("data")
    if data_obj is None:
        # Check for error msg
        error_msg = create_data.get("message") or create_data.get("msg") or "Unknown error"
        raise Exception(f"Kie.ai response missing 'data': {error_msg}")
        
    task_id = data_obj.get("taskId")
    
    if not task_id:
        raise Exception(f"No taskId in response: {create_data}")
    
    print(f"[COVER ART] Task created: {task_id}, polling for result...")
    
    # Poll for result (max 60 seconds)
    image_url = None
    max_attempts = 30
    for attempt in range(max_attempts):
        time.sleep(2)  # Wait 2 seconds between polls
        
        poll_response = requests.get(
            f"{KIE_API_BASE}/recordInfo?taskId={task_id}",
            headers=headers
        )
        
        if poll_response.status_code != 200:
            print(f"[COVER ART] Poll error: {poll_response.status_code}")
            continue
        
        poll_data = poll_response.json()
        state = poll_data.get("data", {}).get("state", "")
        
        if state == "success":
            result_json_str = poll_data.get("data", {}).get("resultJson", "{}")
            result_json = json.loads(result_json_str)
            result_urls = result_json.get("resultUrls", [])
            if result_urls:
                image_url = result_urls[0]
                print(f"[COVER ART] ✅ Image generated successfully!")
                break
        elif state == "failed":
            error_msg = poll_data.get("data", {}).get("errorMessage", "Unknown error")
            raise Exception(f"Image generation failed: {error_msg}")
        else:
            print(f"[COVER ART] Status: {state} (attempt {attempt + 1}/{max_attempts})")
    
    if not image_url:
        raise Exception("Timeout waiting for image generation")
    
    urls = {}
    if not upload:
        # Preview-only: return the generated URL without uploading to Supabase
        urls["cover_art_url"] = image_url
        urls["cover_art_url_16x9"] = image_url
        print("[COVER ART] Preview mode: returning generated URL without upload")
        return urls
        
    # Use shared helper
    return process_and_upload_image(image_url, metadata, urls)


def update_book_cover_url(book_id: str, cover_urls: dict):
    """
    Updates the book record with the cover art URLs.
    """
    supabase = get_supabase()
    
    update_data = {}
    if "cover_art_url" in cover_urls:
        update_data["cover_art_url"] = cover_urls["cover_art_url"]
    if "cover_art_url_16x9" in cover_urls:
        update_data["cover_art_url_16x9"] = cover_urls["cover_art_url_16x9"]
    
    if update_data:
        supabase.table("books").update(update_data).eq("id", book_id).execute()
        print(f"[COVER ART] ✅ Updated book {book_id} with {len(update_data)} cover URLs")
