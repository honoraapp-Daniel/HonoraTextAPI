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
from supabase import create_client

# Lazy initialization
_supabase_client = None

# Kie.ai API configuration
KIE_API_BASE = "https://api.kie.ai/api/v1/jobs"
KIE_MODEL = "google/nano-banana"


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
    Only rule: artwork must be inspired by the book's content.
    """
    title = metadata.get("title", "Untitled")
    author = metadata.get("author", "Unknown")
    category = metadata.get("category", "")
    synopsis = metadata.get("synopsis", "")
    
    # Build context about the book
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


def crop_to_aspect_ratio(image: Image.Image, target_ratio: float) -> Image.Image:
    """
    Crops image to target aspect ratio from center.
    target_ratio = width / height (e.g., 1.0 for 1:1, 0.667 for 2:3)
    """
    width, height = image.size
    current_ratio = width / height
    
    if current_ratio > target_ratio:
        # Image is wider than target - crop width
        new_width = int(height * target_ratio)
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    else:
        # Image is taller than target - crop height
        new_height = int(width / target_ratio)
        top = (height - new_height) // 2
        return image.crop((0, top, width, top + new_height))


def generate_cover_image(metadata: dict) -> dict:
    """
    Generates book cover artwork using Nano Banana (via Kie.ai API).
    Nano Banana renders title and author directly on the image.
    Generates 16:9 then crops to 1:1 and 2:3.
    Returns URLs for all three versions.
    """
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
    task_id = create_data.get("data", {}).get("taskId")
    
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
    
    print(f"[COVER ART] Downloading artwork...")
    
    # Download the image
    image_response = requests.get(image_url)
    if image_response.status_code != 200:
        raise Exception(f"Failed to download image: {image_response.status_code}")
    
    # Open image with PIL
    original = Image.open(BytesIO(image_response.content)).convert("RGB")
    width, height = original.size
    print(f"[COVER ART] Downloaded artwork size: {width}x{height}")
    
    # Create cropped versions
    print(f"[COVER ART] Creating cropped versions...")
    
    # 16:9 - keep original (for banners)
    img_16x9 = original
    
    # 1:1 - square crop from center
    img_1x1 = crop_to_aspect_ratio(original, 1.0)
    
    # 2:3 - portrait crop from center
    img_2x3 = crop_to_aspect_ratio(original, 2/3)
    
    print(f"[COVER ART] Cropped sizes: 16:9={img_16x9.size}, 1:1={img_1x1.size}, 2:3={img_2x3.size}")
    
    # Upload all versions to Supabase Storage
    supabase = get_supabase()
    book_id = metadata.get("book_id", str(uuid.uuid4()))
    
    print(f"[COVER ART] Uploading to Supabase Storage...")
    
    urls = {}
    
    # Upload 16:9 (banner)
    buffer = BytesIO()
    img_16x9.save(buffer, format="PNG")
    buffer.seek(0)
    file_name = f"covers/{book_id}_16x9.png"
    supabase.storage.from_("audio").upload(
        file_name,
        buffer.getvalue(),
        {"content-type": "image/png", "x-upsert": "true"}
    )
    urls["cover_art_url_16x9"] = supabase.storage.from_("audio").get_public_url(file_name)
    
    # Upload 1:1 (square)
    buffer = BytesIO()
    img_1x1.save(buffer, format="PNG")
    buffer.seek(0)
    file_name = f"covers/{book_id}_1x1.png"
    supabase.storage.from_("audio").upload(
        file_name,
        buffer.getvalue(),
        {"content-type": "image/png", "x-upsert": "true"}
    )
    urls["cover_art_url"] = supabase.storage.from_("audio").get_public_url(file_name)
    
    # Upload 2:3 (portrait)
    buffer = BytesIO()
    img_2x3.save(buffer, format="PNG")
    buffer.seek(0)
    file_name = f"covers/{book_id}_2x3.png"
    supabase.storage.from_("audio").upload(
        file_name,
        buffer.getvalue(),
        {"content-type": "image/png", "x-upsert": "true"}
    )
    urls["cover_art_url_2x3"] = supabase.storage.from_("audio").get_public_url(file_name)
    
    print(f"[COVER ART] ✅ Upload complete! 3 cover versions uploaded")
    
    return urls


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
    if "cover_art_url_2x3" in cover_urls:
        update_data["cover_art_url_2x3"] = cover_urls["cover_art_url_2x3"]
    
    if update_data:
        supabase.table("books").update(update_data).eq("id", book_id).execute()
        print(f"[COVER ART] ✅ Updated book {book_id} with {len(update_data)} cover URLs")
