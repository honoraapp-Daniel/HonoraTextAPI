"""
Cover art generation module for Honora.
Generates artistic book cover images using Nano Banana (via Kie.ai API).
Falls back to DALL-E 3 if Kie.ai fails.
Generates 16:9 image then crops to 1:1 variant.
"""
import os
import requests
import uuid
import time
import json
from io import BytesIO
from PIL import Image
from openai import OpenAI
from supabase import create_client

# Lazy initialization
_supabase_client = None

# Kie.ai API configuration
KIE_API_BASE = "https://api.kie.ai/api/v1/jobs"
KIE_MODEL = "google/nano-banana"


def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set")
    return OpenAI(api_key=api_key)


def get_kie_api_key():
    """Get Kie.ai API key from environment."""
    api_key = os.getenv("KIE_API_KEY")
    if not api_key:
        raise RuntimeError("KIE_API_KEY must be set")
    return api_key


def get_supabase():
    global _supabase_client
    if _supabase_client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        _supabase_client = create_client(url, key)
    return _supabase_client


def generate_cover_art_prompt(metadata: dict) -> str:
    """
    Generates a Nano Banana prompt with creative freedom.
    Includes title and author for the AI to render on the cover.
    """
    metadata = metadata or {}
    title = metadata.get("title", "Untitled")
    author = metadata.get("author", "Unknown")
    category = metadata.get("category", "")
    synopsis = metadata.get("synopsis", "")
    
    book_context = f'"{title}" by {author}'
    if category:
        book_context += f'. Genre: {category}'
    if synopsis:
        book_context += f'. Synopsis: {synopsis[:400]}'
    
    prompt = f"""Create a beautiful, professional book cover for:

{book_context}

The cover MUST include:
- The title "{title}" prominently displayed
- The author name "{author}" 

You have complete creative freedom for the artwork! Choose any artistic style, colors, composition, mood, or visual approach that best captures the essence and themes of this book.

The only rule: The artwork must be inspired by and reflect the book's content, themes, or mood.

Make it stunning and professional - this is for an audiobook app."""

    return prompt


def crop_to_aspect_ratio(image: Image.Image, target_ratio: float, anchor: str = "center") -> Image.Image:
    """
    Crops image to target aspect ratio.
    target_ratio = width / height (e.g., 1.0 for 1:1)
    """
    width, height = image.size
    current_ratio = width / height
    
    if current_ratio > target_ratio:
        new_width = int(height * target_ratio)
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    else:
        new_height = int(width / target_ratio)
        if anchor == "top":
            return image.crop((0, 0, width, new_height))
        else:
            top = (height - new_height) // 2
            return image.crop((0, top, width, top + new_height))


def generate_cover_image(metadata: dict, upload: bool = True) -> dict:
    """
    Generates book cover artwork.
    Tries Kie.ai (Nano Banana) first.
    Falls back to DALL-E 3 if Kie.ai fails (e.g. no credits).
    """
    try:
        return generate_with_kie(metadata, upload)
    except Exception as e:
        print(f"[COVER ART] ❌ Kie.ai failed: {e}")
        print("[COVER ART] 🔄 Switching to DALL-E fallback...")
        return generate_with_dalle(metadata, upload)


def generate_with_dalle(metadata: dict, upload: bool = True) -> dict:
    """Fallback generator using DALL-E 3."""
    client = get_openai_client()
    metadata = metadata or {}
    title = metadata.get("title", "Untitled")
    print(f"[COVER ART] ⚠️ Using DALL-E 3 fallback for: {title}")

    prompt = f"""Book cover artwork for "{title}". 
    Genre: {metadata.get('category', 'General')}. 
    Synopsis: {metadata.get('synopsis', '')[:200]}.
    Style: Professional, artistic, high quality.
    Do NOT include any text on the image, just the artwork."""

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
        
    return process_and_upload_image(image_url, metadata, urls)


def generate_with_kie(metadata: dict, upload: bool = True) -> dict:
    """Kie.ai (Nano Banana) generation logic."""
    metadata = metadata or {}
    prompt = generate_cover_art_prompt(metadata)
    title = metadata.get("title", "Untitled")
    
    print(f"[COVER ART] Generating artwork for: {title}")
    print(f"[COVER ART] Using Nano Banana via Kie.ai API...")
    
    api_key = get_kie_api_key()
    
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
    
    create_response = requests.post(
        f"{KIE_API_BASE}/createTask",
        headers=headers,
        json=payload
    )
    
    if create_response.status_code != 200:
        raise Exception(f"Kie.ai API error: {create_response.status_code} - {create_response.text}")
    
    create_data = create_response.json()
    
    data_obj = create_data.get("data")
    if data_obj is None:
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
        time.sleep(2)
        
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
        urls["cover_art_url"] = image_url
        urls["cover_art_url_16x9"] = image_url
        print("[COVER ART] Preview mode: returning generated URL without upload")
        return urls
        
    return process_and_upload_image(image_url, metadata, urls)


def process_and_upload_image(image_url: str, metadata: dict, urls: dict) -> dict:
    """Shared helper to download, crop, and upload image from URL."""
    print("[COVER ART] Downloading artwork...")
    image_response = requests.get(image_url)
    if image_response.status_code != 200:
        raise Exception(f"Failed to download image: {image_response.status_code}")
    
    original = Image.open(BytesIO(image_response.content)).convert("RGB")
    width, height = original.size
    
    is_landscape = width > height
    
    if is_landscape:
        img_16x9 = original
        img_1x1 = crop_to_aspect_ratio(original, 1.0)
    else:
        img_1x1 = original
        target_ratio_16_9 = 16/9
        new_height = int(width / target_ratio_16_9)
        top = (height - new_height) // 2
        img_16x9 = original.crop((0, top, width, top + new_height))

    supabase = get_supabase()
    book_id = metadata.get("book_id", str(uuid.uuid4()))
    
    print("[COVER ART] Uploading to Supabase Storage...")
    
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


def update_book_cover_url(book_id: str, cover_urls: dict):
    """Updates the book record with the cover art URLs."""
    supabase = get_supabase()
    
    update_data = {}
    if "cover_art_url" in cover_urls:
        update_data["cover_art_url"] = cover_urls["cover_art_url"]
    if "cover_art_url_16x9" in cover_urls:
        update_data["cover_art_url_16x9"] = cover_urls["cover_art_url_16x9"]
    
    if update_data:
        supabase.table("books").update(update_data).eq("id", book_id).execute()
        print(f"[COVER ART] ✅ Updated book {book_id} with {len(update_data)} cover URLs")
