"""
Cover art generation module for Honora.
Generates artistic book cover images using DALL-E and uploads to Supabase Storage.
"""
import os
import requests
import uuid
from io import BytesIO
from PIL import Image
from openai import OpenAI
from supabase import create_client

# Lazy initialization
_openai_client = None
_supabase_client = None


def get_openai():
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY must be set")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


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
    Generates a DALL-E prompt for book cover artwork.
    Includes title and concrete visual elements representing the book's content.
    
    Args:
        metadata: dict with title, author, category, synopsis
        
    Returns:
        str: DALL-E prompt
    """
    title = metadata.get("title", "Untitled")
    author = metadata.get("author", "Unknown")
    category = metadata.get("category", "Fiction")
    synopsis = metadata.get("synopsis", "")
    
    # Determine visual style based on category
    category_styles = {
        "Fiction": "cinematic, narrative imagery with depth",
        "Mystery": "dark, moody atmosphere with shadowy elements",
        "Romance": "warm, romantic lighting with soft tones",
        "Fantasy": "magical, otherworldly landscapes and mystical symbols",
        "Science Fiction": "futuristic, cosmic imagery with technology",
        "Biography": "dignified portrait style with personal elements",
        "Self-Help": "uplifting, bright imagery with growth symbolism",
        "History": "historical imagery, period-appropriate visuals",
        "Philosophy": "contemplative, symbolic imagery with depth",
        "Business": "professional, dynamic imagery of success",
        "Classic Literature": "elegant, timeless artistic style",
        "Children": "colorful, whimsical, playful imagery",
        "Young Adult": "bold, energetic, emotionally resonant",
        "Poetry": "lyrical, artistic, emotionally evocative",
        "Religion": "sacred, peaceful, spiritually uplifting imagery",
        "Science": "scientific imagery, wonder of discovery",
        "Non-Fiction": "authentic, documentary-style imagery"
    }
    
    style = category_styles.get(category, "cinematic, narrative imagery with depth")
    
    # Create prompt with title and concrete imagery
    prompt = f"""Design a professional book cover for "{title}" by {author}.

LAYOUT REQUIREMENTS (CRITICAL):
- The book title "{title}" must be prominently displayed in elegant, readable typography
- Place the title in the VERTICAL CENTER of the image (middle third)
- Keep ALL important elements (title, main imagery) within the CENTER 60% of the image width
- The outer 20% on each side should be background only (no text or key elements) as it will be cropped

VISUAL CONTENT:
- The imagery should clearly represent the book's subject matter and themes
- Based on the synopsis: {synopsis[:300] if synopsis else 'Create visuals that match the title'}
- Style: {style}
- Include recognizable visual elements that indicate what the book is about (landmarks, symbols, objects, scenes relevant to the content)

DESIGN STYLE:
- Professional book cover design quality
- High contrast, readable title
- Rich, detailed background imagery
- The overall composition should look like a premium audiobook cover

Format: Square composition with all key elements centered."""

    return prompt



def generate_cover_image(metadata: dict) -> dict:
    """
    Generates book cover artwork using DALL-E and uploads to Supabase Storage.
    Creates two versions: 1:1 (square) and 2:3 (book format).
    
    Args:
        metadata: dict with book information
        
    Returns:
        dict: {"cover_art_url": "...", "cover_art_url_2x3": "..."}
    """
    prompt = generate_cover_art_prompt(metadata)
    
    print(f"[COVER ART] Generating artwork for: {metadata.get('title')}")
    
    client = get_openai()
    
    # Generate image with DALL-E 3 (1024x1024 for best quality)
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="hd",
        n=1
    )
    
    image_url = response.data[0].url
    print(f"[COVER ART] Image generated, downloading...")
    
    # Download the image
    image_response = requests.get(image_url)
    if image_response.status_code != 200:
        raise Exception(f"Failed to download image: {image_response.status_code}")
    
    # Open image with PIL
    original_image = Image.open(BytesIO(image_response.content))
    
    # Create 1:1 version (already 1024x1024)
    square_image = original_image.copy()
    
    # Create 2:3 version by cropping from center (682x1024)
    # From 1024x1024, we crop to 682 width centered
    width_2x3 = int(1024 * 2 / 3)  # 682
    left = (1024 - width_2x3) // 2  # Center crop
    portrait_image = original_image.crop((left, 0, left + width_2x3, 1024))
    
    # Upload to Supabase Storage
    supabase = get_supabase()
    book_id = metadata.get("book_id", str(uuid.uuid4()))
    
    print(f"[COVER ART] Uploading both versions to Supabase Storage...")
    
    # Upload 1:1 version
    square_buffer = BytesIO()
    square_image.save(square_buffer, format="PNG")
    square_buffer.seek(0)
    
    file_name_1x1 = f"covers/{book_id}_1x1.png"
    supabase.storage.from_("audio").upload(
        file_name_1x1,
        square_buffer.getvalue(),
        {"content-type": "image/png"}
    )
    url_1x1 = supabase.storage.from_("audio").get_public_url(file_name_1x1)
    
    # Upload 2:3 version
    portrait_buffer = BytesIO()
    portrait_image.save(portrait_buffer, format="PNG")
    portrait_buffer.seek(0)
    
    file_name_2x3 = f"covers/{book_id}_2x3.png"
    supabase.storage.from_("audio").upload(
        file_name_2x3,
        portrait_buffer.getvalue(),
        {"content-type": "image/png"}
    )
    url_2x3 = supabase.storage.from_("audio").get_public_url(file_name_2x3)
    
    print(f"[COVER ART] Upload complete: 1:1 and 2:3 versions")
    
    return {
        "cover_art_url": url_1x1,
        "cover_art_url_2x3": url_2x3
    }


def update_book_cover_url(book_id: str, cover_urls: dict):
    """
    Updates the book record with both cover art URLs.
    
    Args:
        book_id: UUID of the book
        cover_urls: dict with cover_art_url and cover_art_url_2x3
    """
    supabase = get_supabase()
    supabase.table("books").update({
        "cover_art_url": cover_urls.get("cover_art_url"),
        "cover_art_url_2x3": cover_urls.get("cover_art_url_2x3")
    }).eq("id", book_id).execute()
    print(f"[COVER ART] Updated book {book_id} with both cover URLs")

