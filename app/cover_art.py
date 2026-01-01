"""
Cover art generation module for Honora.
Generates artistic book cover images using DALL-E 3.
Generates 1:1 base image then creates 16:9 variant.
"""
import os
import requests
import uuid
import base64
from io import BytesIO
from PIL import Image
from openai import OpenAI
from supabase import create_client

from app.config import Config
from app.logger import get_logger
from app.utils import retry_on_failure

logger = get_logger(__name__)

# Lazy initialization
_supabase_client = None
_openai_client = None


def get_openai_client():
    """Get OpenAI client with proper configuration."""
    global _openai_client
    if _openai_client is None:
        Config.validate_required("OPENAI_API_KEY")
        _openai_client = OpenAI(
            api_key=Config.OPENAI_API_KEY,
            timeout=Config.OPENAI_TIMEOUT
        )
    return _openai_client


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


@retry_on_failure(max_retries=2, delay=3, exceptions=(Exception,))
def generate_cover_image(metadata: dict, upload: bool = True) -> dict:
    """
    Generates book cover artwork using DALL-E 3.
    
    Args:
        metadata: Book metadata dictionary
        upload: Whether to upload to Supabase storage
        
    Returns:
        dict with cover_art_url and cover_art_url_16x9
    """
    return generate_with_dalle(metadata, upload)





def generate_with_dalle(metadata: dict, upload: bool = True) -> dict:
    """
    Generate cover art using DALL-E 3.
    
    Args:
        metadata: Book metadata dictionary
        upload: Whether to upload to Supabase
        
    Returns:
        dict with cover art URLs
    """
    try:
        client = get_openai_client()
        metadata = metadata or {}
        title = metadata.get("title", "Untitled")
        synopsis = metadata.get("synopsis") or ""
        category = metadata.get("category") or "General"
        
        logger.info(f"Generating DALL-E 3 cover art for: {title}")

        # Build detailed prompt using existing function
        prompt = generate_cover_art_prompt(metadata)
        
        # Generate image with DALL-E 3
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        
        image_url = response.data[0].url
        logger.info(f"DALL-E 3 cover art generated successfully for: {title}")
        
        urls = {}
        if not upload:
            # Return URL directly for preview
            urls["cover_art_url"] = image_url
            urls["cover_art_url_16x9"] = image_url
            logger.info("Preview mode: returning image URL")
            return urls
            
        return process_and_upload_image(image_url, metadata, urls)
        
    except Exception as e:
        logger.error(f"Failed to generate cover art: {e}")
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


def process_and_upload_image(image_url: str, metadata: dict, urls: dict) -> dict:
    """
    Download image from URL and upload to Supabase.
    
    Args:
        image_url: URL to download image from
        metadata: Book metadata
        urls: Dictionary to store URLs
        
    Returns:
        Updated urls dictionary
    """
    try:
        logger.info(f"Downloading cover art from URL...")
        image_response = requests.get(image_url, timeout=Config.API_TIMEOUT)
        
        if image_response.status_code != 200:
            raise Exception(f"Failed to download image: HTTP {image_response.status_code}")
        
        return process_and_upload_image_bytes(image_response.content, metadata, urls)
        
    except requests.RequestException as e:
        logger.error(f"Failed to download cover art: {e}")
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
