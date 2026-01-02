"""
Cover art generation module for Honora.
Generates artistic book cover images using Nano Banana (Google AI Studio).
"""
import os
import requests
import uuid
from io import BytesIO
from PIL import Image
from supabase import create_client
from google import genai
from google.genai import types

from app.config import Config
from app.logger import get_logger
from app.utils import retry_on_failure

logger = get_logger(__name__)

# Lazy initialization
_supabase_client = None
_nano_banana_client = None

# Nano Banana API key (via Google AI Studio)
NANO_BANANA_API_KEY = "AIzaSyAytfAtpVeIW__NUUAgosEfoDtroVE6LsU"


def get_nano_banana_client():
    """Get Nano Banana client with proper configuration."""
    global _nano_banana_client
    if _nano_banana_client is None:
        _nano_banana_client = genai.Client(api_key=NANO_BANANA_API_KEY)
    return _nano_banana_client


def get_supabase():
    """Get Supabase client with proper configuration."""
    global _supabase_client
    if _supabase_client is None:
        Config.validate_required("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        url = Config.SUPABASE_URL
        if not url.endswith("/"):
            url = f"{url}/"
        _supabase_client = create_client(url, Config.SUPABASE_SERVICE_ROLE_KEY)
    return _supabase_client


def generate_cover_art_prompt(metadata: dict) -> str:
    """
    Generates a Nano Banana prompt for vintage-style book covers.
    
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

4. COLOR PALETTE: Rich, warm vintage tones - golds, deep reds, aged paper colors, ornate metallic accents. NO plain white backgrounds.

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


@retry_on_failure(max_retries=2, delay=3, exceptions=(Exception,))
def generate_cover_image(metadata: dict, upload: bool = True) -> dict:
    """
    Generates book cover artwork using Nano Banana via Google AI Studio.
    
    Args:
        metadata: Book metadata dictionary
        upload: Whether to upload to Supabase storage
        
    Returns:
        dict with cover_art_url and cover_art_url_16x9
    """
    return generate_with_nano_banana(metadata, upload)


def generate_with_nano_banana(metadata: dict, upload: bool = True) -> dict:
    """
    Generate cover art using Nano Banana (Imagen 3) via Google AI Studio.
    
    Args:
        metadata: Book metadata dictionary
        upload: Whether to upload to Supabase
        
    Returns:
        dict with cover art URLs
    """
    try:
        client = get_nano_banana_client()
        metadata = metadata or {}
        title = metadata.get("title", "Untitled")
        
        logger.info(f"Generating Nano Banana cover art for: {title}")

        # Build detailed prompt
        prompt = generate_cover_art_prompt(metadata)
        
        # Generate image with Nano Banana (Imagen 3)
        response = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="1:1",  # Square for cover art
                output_mime_type="image/png"
            )
        )
        
        if not response.generated_images:
            raise Exception("No images generated by Nano Banana")
        
        # Get image bytes
        image_bytes = response.generated_images[0].image.image_bytes
        
        logger.info(f"Nano Banana cover art generated successfully for: {title}")
        
        urls = {}
        if not upload:
            # For preview, we can't return raw bytes so return a placeholder
            urls["cover_art_url"] = None
            urls["cover_art_url_16x9"] = None
            logger.info("Preview mode: skipping upload")
            return urls
            
        return process_and_upload_image_bytes(image_bytes, metadata, urls)
        
    except Exception as e:
        logger.error(f"Failed to generate cover art with Nano Banana: {e}")
        raise


def process_and_upload_image_bytes(image_bytes: bytes, metadata: dict, urls: dict) -> dict:
    """
    Process image from bytes data and upload to Supabase.
    
    Args:
        image_bytes: Raw image bytes
        metadata: Book metadata
        urls: Dictionary to store URLs
        
    Returns:
        Updated urls dictionary
    """
    try:
        logger.info("Processing cover art image...")
        
        original = Image.open(BytesIO(image_bytes)).convert("RGB")
        width, height = original.size
        
        # Create both aspect ratios
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
        
        logger.info("Uploading cover art to Supabase Storage...")
        
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
        
        logger.info("Cover art upload complete! 2 versions uploaded (1:1 and 16:9)")
        return urls
        
    except Exception as e:
        logger.error(f"Failed to process and upload cover art: {e}")
        raise


def update_book_cover_url(book_id: str, cover_urls: dict) -> None:
    """
    Update the book record with cover art URLs.
    
    Args:
        book_id: Book UUID
        cover_urls: Dictionary with cover art URLs
    """
    try:
        supabase = get_supabase()
        
        update_data = {}
        if "cover_art_url" in cover_urls:
            update_data["cover_art_url"] = cover_urls["cover_art_url"]
        if "cover_art_url_16x9" in cover_urls:
            update_data["cover_art_url_16x9"] = cover_urls["cover_art_url_16x9"]
        
        if update_data:
            supabase.table("books").update(update_data).eq("id", book_id).execute()
            logger.info(f"Updated book {book_id} with {len(update_data)} cover URLs")
        else:
            logger.warning(f"No cover URLs to update for book {book_id}")
            
    except Exception as e:
        logger.error(f"Failed to update book cover URLs: {e}")
        raise
