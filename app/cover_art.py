"""
Cover art generation module for Honora.
Generates artistic book cover images using Google Gemini (Nano Banana).
Falls back to DALL-E 3 if Gemini fails.
Generates 16:9 image then crops to 1:1 variant.
"""
import os
import requests
import uuid
import base64
from io import BytesIO
from PIL import Image
from openai import OpenAI
from supabase import create_client

# Lazy initialization
_supabase_client = None


def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set")
    return OpenAI(api_key=api_key)


def get_gemini_client():
    """Get Google Gemini client."""
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY must be set")
    return genai.Client(api_key=api_key)


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
    Generates a Gemini/Nano Banana prompt for vintage-style book covers.
    
    Style: Classic vintage book cover with ornate borders, 
    blurred background extension for flexible aspect ratios.
    """
    metadata = metadata or {}
    title = metadata.get("title", "Untitled")
    author = metadata.get("author", "Unknown")
    year = metadata.get("publishing_year", "")
    category = metadata.get("category", "")
    synopsis = metadata.get("synopsis", "")
    
    # Build context for artwork inspiration
    thematic_hints = ""
    if category:
        thematic_hints += f"Genre: {category}. "
    if synopsis:
        thematic_hints += f"Themes: {synopsis[:300]}"
    
    # Format year if available
    year_text = f"\n{year}" if year else ""
    
    prompt = f"""Create a beautiful vintage-style book cover artwork:

BOOK DETAILS:
- Title: "{title}"
- Author: {author}{year_text}
{thematic_hints}

REQUIRED DESIGN ELEMENTS:
1. VINTAGE BOOK FORMAT: Design the cover in a classic, ornate vintage book style with decorative borders and frames (like antique 1900s-1920s book covers)

2. TEXT PLACEMENT:
   - Title "{title}" at the TOP in elegant vintage typography
   - Author "{author}" at the BOTTOM with the year if known
   - Text must be clearly readable and beautifully styled

3. CENTRAL ARTWORK: Create rich, detailed illustration in the center that captures the book's themes and essence. Use artistic elements that reflect the genre and content.

4. BLURRED BACKGROUND EXTENSION: The main cover design should be centered, with the background extending beyond the cover edges as a soft, blurred version of the artwork colors. This creates a seamless look when cropped to different aspect ratios (16:9 or 1:1).

5. COLOR PALETTE: Rich, warm vintage tones - golds, deep reds, aged paper colors, ornate metallic accents. NO plain white backgrounds.

This is for a premium audiobook app. Make it look like a treasured antique book cover."""

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
    Tries Google Gemini (Nano Banana) first.
    Falls back to DALL-E 3 if Gemini fails.
    """
    try:
        return generate_with_gemini(metadata, upload)
    except Exception as e:
        print(f"[COVER ART] ❌ Gemini failed: {e}")
        print("[COVER ART] 🔄 Switching to DALL-E fallback...")
        return generate_with_dalle(metadata, upload)


def generate_with_gemini(metadata: dict, upload: bool = True) -> dict:
    """
    Generate cover art using Google Gemini (Nano Banana).
    Uses gemini-2.5-flash-image model with 16:9 aspect ratio.
    """
    from google.genai import types
    
    metadata = metadata or {}
    prompt = generate_cover_art_prompt(metadata)
    title = metadata.get("title", "Untitled")
    
    print(f"[COVER ART] Generating artwork for: {title}")
    print(f"[COVER ART] Using Google Gemini (Nano Banana)...")
    
    client = get_gemini_client()
    
    # Generate image with 16:9 aspect ratio
    response = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_modalities=['Image'],
            image_config=types.ImageConfig(
                aspect_ratio="16:9"
            )
        )
    )
    
    # Extract image from response
    image_bytes = None
    for part in response.parts:
        if hasattr(part, 'inline_data') and part.inline_data is not None:
            # Get base64 encoded image data
            image_data = part.inline_data.data
            if isinstance(image_data, str):
                image_bytes = base64.b64decode(image_data)
            else:
                image_bytes = image_data
            break
    
    if not image_bytes:
        raise Exception("No image returned from Gemini")
    
    print(f"[COVER ART] ✅ Image generated successfully!")
    
    urls = {}
    if not upload:
        # For preview, save temporarily and return path
        temp_path = f"/tmp/gemini_cover_{uuid.uuid4()}.png"
        with open(temp_path, 'wb') as f:
            f.write(image_bytes)
        urls["cover_art_url"] = temp_path
        urls["cover_art_url_16x9"] = temp_path
        return urls
    
    return process_and_upload_image_bytes(image_bytes, metadata, urls)


def generate_with_dalle(metadata: dict, upload: bool = True) -> dict:
    """Fallback generator using DALL-E 3."""
    client = get_openai_client()
    metadata = metadata or {}
    title = metadata.get("title", "Untitled")
    synopsis = metadata.get("synopsis") or ""  # Handle None explicitly
    category = metadata.get("category") or "General"
    print(f"[COVER ART] ⚠️ Using DALL-E 3 fallback for: {title}")

    prompt = f"""Book cover artwork for "{title}". 
    Genre: {category}. 
    Synopsis: {synopsis[:200] if synopsis else 'A profound literary work'}.
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


def process_and_upload_image_bytes(image_bytes: bytes, metadata: dict, urls: dict) -> dict:
    """Process image from bytes data and upload to Supabase."""
    print("[COVER ART] Processing artwork...")
    
    original = Image.open(BytesIO(image_bytes)).convert("RGB")
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


def process_and_upload_image(image_url: str, metadata: dict, urls: dict) -> dict:
    """Shared helper to download, crop, and upload image from URL."""
    print("[COVER ART] Downloading artwork...")
    image_response = requests.get(image_url)
    if image_response.status_code != 200:
        raise Exception(f"Failed to download image: {image_response.status_code}")
    
    return process_and_upload_image_bytes(image_response.content, metadata, urls)


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
