"""
Cover art generation module for Honora.
Generates artistic book cover images using Nano Banana (Google AI Studio).
"""
import os
import requests
import uuid
from io import BytesIO
from PIL import Image, ImageFilter
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


def get_nano_banana_client():
    """Get Nano Banana client with proper configuration."""
    global _nano_banana_client
    if _nano_banana_client is None:
        # Use Gemini API key from environment - NEVER hardcode!
        api_key = Config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
        
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set. Cannot generate cover art.")
            
        _nano_banana_client = genai.Client(api_key=api_key)
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
    Generates a creative Nano Banana prompt for book covers.
    
    IMPORTANT: We ask for FLAT cover art only. The Python code will
    create the 16:9 version with blurred background automatically.
    """
    metadata = metadata or {}
    title = metadata.get("title", "Untitled")
    author = metadata.get("author", "Unknown")
    year = metadata.get("publishing_year", "")
    category = metadata.get("category", "")
    synopsis = metadata.get("synopsis", "")
    
    # Build context about the book
    book_context = ""
    if category:
        book_context += f"This is a {category} book. "
    if synopsis:
        book_context += synopsis[:200]
    
    prompt = f"""Design a stunning, premium book cover for "{title}" by {author}.

{book_context}

ARTISTIC DIRECTION:
Create a masterpiece of cover art. You have full creative freedom with the artistic style.
The design should be rich, evocative, and high-quality - like a bestseller or classic edition.
Use lighting, color, and texture to create depth and atmosphere that matches the book's themes.

CRITICAL REQUIREMENTS:
1. Create FLAT, FULL-BLEED artwork that fills the ENTIRE image edge-to-edge
2. NO 3D book mockup - just the flat cover art itself
3. NO blurred background or frame around the art - the artwork IS the entire image
4. The artwork should seamlessly extend to all edges without borders or margins
5. Include the title "{title}" and author "{author}" with elegant, integrated typography

The final image should look like you're viewing JUST the front cover of a beautiful book,
not a book placed on a background. The art and typography should fill the complete canvas.
"""
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


def create_blurred_background_16_9(original: Image.Image) -> Image.Image:
    """
    Creates a 16:9 image with the original cover art in center and blurred background.
    
    The background is a zoomed, blurred, and darkened version of the cover art itself,
    creating a cohesive premium look while ensuring the cover is clearly visible.
    """
    from PIL import ImageEnhance
    
    # Target dimensions (HD)
    target_width = 1920
    target_height = 1080
    
    # Create canvas
    canvas = Image.new('RGB', (target_width, target_height), (0, 0, 0))
    
    # 1. Create Background (Zoomed + Blurred + Darkened)
    # Scale original so it fills the width
    bg_scale = target_width / original.width
    bg_width = target_width
    bg_height = int(original.height * bg_scale)
    
    # If height is still too small to fill (very wide image), scale by height instead
    if bg_height < target_height:
        bg_scale = target_height / original.height
        bg_height = target_height
        bg_width = int(original.width * bg_scale)
        
    background = original.resize((bg_width, bg_height), Image.Resampling.LANCZOS)
    
    # Crop center to fit 16:9
    left = (bg_width - target_width) // 2
    top = (bg_height - target_height) // 2
    background = background.crop((left, top, left + target_width, top + target_height))
    
    # Apply heavy blur
    background = background.filter(ImageFilter.GaussianBlur(radius=60))
    
    # Darken the background for better cover visibility (reduce brightness to 40%)
    enhancer = ImageEnhance.Brightness(background)
    background = enhancer.enhance(0.4)
    
    # 2. Place Foreground (Original Cover Art - LARGE)
    # Scale to fit 95% of height for maximum visibility
    fg_height = int(target_height * 0.95)
    fg_scale = fg_height / original.height
    fg_width = int(original.width * fg_scale)
    
    foreground = original.resize((fg_width, fg_height), Image.Resampling.LANCZOS)
    
    # Paste in center
    paste_x = (target_width - fg_width) // 2
    paste_y = (target_height - fg_height) // 2
    
    canvas.paste(background, (0, 0))
    canvas.paste(foreground, (paste_x, paste_y))
    
    return canvas


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
        
        # Generate image with Nano Banana (Imagen 4)
        response = client.models.generate_images(
            model="imagen-4.0-fast-generate-001",
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
            # Create 16:9 with blurred background
            img_16x9 = create_blurred_background_16_9(original)

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
