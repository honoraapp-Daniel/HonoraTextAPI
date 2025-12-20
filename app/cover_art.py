"""
Cover art generation module for Honora.
Generates photorealistic book cover images using DALL-E and uploads to Supabase Storage.
"""
import os
import requests
import uuid
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
    Generates a DALL-E prompt for creating a photorealistic book cover image.
    
    Args:
        metadata: dict with title, author, category, synopsis
        
    Returns:
        str: DALL-E prompt
    """
    title = metadata.get("title", "Unknown Book")
    author = metadata.get("author", "Unknown Author")
    category = metadata.get("category", "Fiction")
    synopsis = metadata.get("synopsis", "")
    
    # Determine mood/color based on category
    category_moods = {
        "Fiction": "warm, inviting colors with soft lighting",
        "Mystery": "dark, moody atmosphere with dramatic shadows",
        "Romance": "soft pink and warm tones, romantic lighting",
        "Fantasy": "mystical, ethereal colors with magical glow",
        "Science Fiction": "cool blue and silver tones, futuristic lighting",
        "Biography": "classic, dignified colors with natural lighting",
        "Self-Help": "bright, optimistic colors with clean lighting",
        "History": "sepia and earth tones, vintage atmosphere",
        "Philosophy": "deep, contemplative tones, minimalist",
        "Business": "professional blues and grays, clean modern",
        "Classic Literature": "rich, timeless colors, elegant atmosphere",
        "Children": "vibrant, playful colors with cheerful lighting",
        "Young Adult": "dynamic, energetic colors with modern feel",
        "Poetry": "soft, artistic colors with dreamy atmosphere",
        "Religion": "sacred, peaceful tones with spiritual light",
        "Science": "clean, precise colors with clinical lighting",
        "Non-Fiction": "neutral, professional colors with clear lighting"
    }
    
    mood = category_moods.get(category, "warm, inviting colors with soft lighting")
    
    prompt = f"""A photorealistic image of a beautiful hardcover book placed elegantly on a wooden table or surface. 

The book has the title "{title}" by {author} embossed on the cover in elegant typography. 

The cover design reflects the {category.lower()} genre with {mood}.

The book is positioned at a slight angle, photographed with professional product photography lighting. Clean, minimalist composition with soft shadows. The background is slightly blurred, focusing attention on the book.

Style: High-end product photography, editorial quality, 8K resolution, photorealistic."""

    return prompt


def generate_cover_image(metadata: dict) -> str:
    """
    Generates a book cover image using DALL-E and uploads to Supabase Storage.
    
    Args:
        metadata: dict with book information
        
    Returns:
        str: Public URL of the uploaded cover image
    """
    prompt = generate_cover_art_prompt(metadata)
    
    print(f"[COVER ART] Generating cover for: {metadata.get('title')}")
    
    client = get_openai()
    
    # Generate image with DALL-E 3
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1
    )
    
    image_url = response.data[0].url
    print(f"[COVER ART] Image generated, downloading...")
    
    # Download the image
    image_response = requests.get(image_url)
    if image_response.status_code != 200:
        raise Exception(f"Failed to download image: {image_response.status_code}")
    
    # Upload to Supabase Storage
    supabase = get_supabase()
    book_id = metadata.get("book_id", str(uuid.uuid4()))
    file_name = f"covers/{book_id}.png"
    
    print(f"[COVER ART] Uploading to Supabase Storage: {file_name}")
    
    # Upload image bytes
    supabase.storage.from_("audio").upload(
        file_name,
        image_response.content,
        {"content-type": "image/png"}
    )
    
    # Get public URL
    public_url = supabase.storage.from_("audio").get_public_url(file_name)
    print(f"[COVER ART] Upload complete: {public_url}")
    
    return public_url


def update_book_cover_url(book_id: str, cover_url: str):
    """
    Updates the book record with the cover art URL.
    
    Args:
        book_id: UUID of the book
        cover_url: Public URL of the cover image
    """
    supabase = get_supabase()
    supabase.table("books").update({"cover_art_url": cover_url}).eq("id", book_id).execute()
    print(f"[COVER ART] Updated book {book_id} with cover URL")
