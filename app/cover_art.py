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
    Generates a creative DALL-E prompt for book cover artwork.
    The prompt is intentionally open to artistic interpretation.
    
    Args:
        metadata: dict with title, author, category, synopsis
        
    Returns:
        str: DALL-E prompt
    """
    title = metadata.get("title", "Untitled")
    category = metadata.get("category", "Fiction")
    synopsis = metadata.get("synopsis", "")
    
    # Determine visual mood based on category
    category_moods = {
        "Fiction": "evocative, narrative, atmospheric",
        "Mystery": "dark, enigmatic, shadowy with hints of intrigue",
        "Romance": "warm, emotional, soft and dreamy",
        "Fantasy": "mystical, magical, ethereal and otherworldly",
        "Science Fiction": "futuristic, cosmic, technological wonder",
        "Biography": "dignified, personal, intimate portraiture style",
        "Self-Help": "uplifting, transformative, inspiring light",
        "History": "timeless, epic, classical grandeur",
        "Philosophy": "contemplative, abstract, thought-provoking",
        "Business": "dynamic, professional, forward-moving",
        "Classic Literature": "elegant, timeless, artistic sophistication",
        "Children": "whimsical, colorful, joyful and imaginative",
        "Young Adult": "bold, energetic, emotionally resonant",
        "Poetry": "lyrical, artistic, emotionally evocative",
        "Religion": "sacred, peaceful, spiritually uplifting",
        "Science": "precise, fascinating, wonder of discovery",
        "Non-Fiction": "authentic, compelling, visually engaging"
    }
    
    mood = category_moods.get(category, "evocative, narrative, atmospheric")
    
    # Create an open, artistic prompt
    prompt = f"""Create a stunning, artistic cover image that captures the essence of "{title}".

The artwork should be {mood}.

Visual inspiration from the book's theme: {synopsis[:200] if synopsis else 'A profound journey of discovery and meaning.'}

Style: High-quality digital art, visually striking, suitable as a book cover. The image should be symbolic and evocative, not literal. No text, no letters, no words - pure visual art only.

The composition should work beautifully both as a square format and when cropped vertically."""

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

