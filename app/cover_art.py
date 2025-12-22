"""
Cover art generation module for Honora.
Generates artistic book cover images using DALL-E, then adds title/author
with Pillow for perfect typography.
"""
import os
import requests
import uuid
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from openai import OpenAI
from supabase import create_client

# Lazy initialization
_openai_client = None
_supabase_client = None
_cached_fonts = {}  # Cache loaded fonts


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


def get_fonts_dir() -> Path:
    """Get the fonts directory path using pathlib for cross-platform support."""
    return Path(__file__).parent / "fonts"


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """
    Load bundled Cinzel font with caching.
    Falls back to default font if bundled fonts not found.
    """
    global _cached_fonts
    cache_key = f"{'bold' if bold else 'regular'}_{size}"
    
    if cache_key in _cached_fonts:
        return _cached_fonts[cache_key]
    
    fonts_dir = get_fonts_dir()
    font_file = "Cinzel-Bold.ttf" if bold else "Cinzel-Regular.ttf"
    font_path = fonts_dir / font_file
    
    print(f"[COVER ART] Looking for font at: {font_path}")
    print(f"[COVER ART] Font path exists: {font_path.exists()}")
    print(f"[COVER ART] Fonts dir contents: {list(fonts_dir.iterdir()) if fonts_dir.exists() else 'DIR NOT FOUND'}")
    
    try:
        if font_path.exists():
            font = ImageFont.truetype(str(font_path), size)
            print(f"[COVER ART] ✅ Successfully loaded {font_file} at size {size}")
            _cached_fonts[cache_key] = font
            return font
        else:
            print(f"[COVER ART] ⚠️ Font file not found: {font_path}")
    except Exception as e:
        print(f"[COVER ART] ❌ Error loading font: {e}")
    
    # Fallback: try to use any available font
    print("[COVER ART] Using default PIL font as fallback")
    try:
        # PIL 10.0+ has a larger default font option
        font = ImageFont.load_default(size=size)
    except TypeError:
        # Older PIL versions don't support size parameter
        font = ImageFont.load_default()
    
    _cached_fonts[cache_key] = font
    return font


# Genre-based font mapping (kept for future use)
CATEGORY_FONTS = {
    "Philosophy": "Georgia",
    "Fiction": "Georgia",
    "Mystery": "Arial",
    "Romance": "Georgia",
    "Fantasy": "Georgia",
    "Science Fiction": "Arial",
    "Biography": "Georgia",
    "Self-Help": "Arial",
    "History": "Georgia",
    "Business": "Arial",
    "Classic Literature": "Georgia",
    "Children": "Arial",
    "Young Adult": "Arial",
    "Poetry": "Georgia",
    "Religion": "Georgia",
    "Science": "Arial",
    "Non-Fiction": "Arial"
}


def generate_cover_art_prompt(metadata: dict) -> str:
    """
    Generates a DALL-E prompt with maximum creative freedom.
    Only 2 rules: no text on images, and artwork should be inspired by the book's content.
    """
    title = metadata.get("title", "Untitled")
    author = metadata.get("author", "")
    category = metadata.get("category", "")
    synopsis = metadata.get("synopsis", "")
    
    # Build context about the book
    book_context = f'Book title: "{title}"'
    if author:
        book_context += f' by {author}'
    if category:
        book_context += f'. Genre: {category}'
    if synopsis:
        book_context += f'. Synopsis: {synopsis[:500]}'
    
    prompt = f"""Create beautiful, unique artwork inspired by this book:

{book_context}

You have complete creative freedom! Choose any artistic style, colors, composition, mood, or visual approach that you feel best captures the essence and themes of this book.

ONLY 2 RULES:
1. ❌ NO TEXT whatsoever - no letters, words, titles, or any readable characters
2. ✅ The artwork must be inspired by and reflect the book's content, themes, or mood

Be creative and surprise me!"""

    return prompt


def get_dominant_brightness(image: Image.Image) -> float:
    """
    Analyzes the lower portion of the image to determine brightness.
    Returns value 0-255 (0=dark, 255=bright).
    """
    # Crop lower third where text will go
    width, height = image.size
    lower_region = image.crop((0, int(height * 0.65), width, height))
    
    # Convert to grayscale and get average
    gray = lower_region.convert('L')
    pixels = list(gray.getdata())
    avg_brightness = sum(pixels) / len(pixels)
    
    return avg_brightness


def wrap_text(draw: ImageDraw.Draw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """
    Wraps text to fit within max_width. Returns list of lines.
    """
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        line_width = bbox[2] - bbox[0]
        
        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    return lines if lines else [text]


def add_text_overlay(image: Image.Image, title: str, author: str, category: str) -> Image.Image:
    """
    Adds title and author text to the image using Pillow.
    Automatically chooses text color based on background brightness.
    Uses bundled Cinzel font with robust path handling.
    Long titles are wrapped to multiple lines with max 80% width.
    """
    img = image.copy()
    draw = ImageDraw.Draw(img)
    width, height = img.size
    
    # Max text width is 80% of image width
    max_text_width = int(width * 0.8)
    
    # Determine text color based on background brightness
    brightness = get_dominant_brightness(img)
    if brightness > 128:
        # Light background -> dark text
        text_color = (30, 30, 30)
        shadow_color = (255, 255, 255, 80)
    else:
        # Dark background -> light text
        text_color = (255, 255, 255)
        shadow_color = (0, 0, 0, 150)
    
    # Load fonts using robust helper function
    title_font = load_font(72, bold=True)
    author_font = load_font(36, bold=False)
    
    # Title in upper case
    title_upper = title.upper()
    
    # Wrap title if too long
    title_lines = wrap_text(draw, title_upper, title_font, max_text_width)
    
    # Calculate total title height
    line_spacing = 10
    title_line_height = draw.textbbox((0, 0), "A", font=title_font)[3]
    total_title_height = len(title_lines) * title_line_height + (len(title_lines) - 1) * line_spacing
    
    # Position title starting Y (in lower portion, adjusted for multi-line)
    title_start_y = int(height * 0.75) - (total_title_height // 2) + (title_line_height // 2)
    
    # Draw shadow for better readability
    shadow_offset = 3
    
    # Draw each title line, centered
    current_y = title_start_y
    for line in title_lines:
        line_bbox = draw.textbbox((0, 0), line, font=title_font)
        line_width = line_bbox[2] - line_bbox[0]
        line_x = (width - line_width) // 2
        
        # Draw shadow
        draw.text((line_x + shadow_offset, current_y + shadow_offset), 
                  line, font=title_font, fill=shadow_color)
        # Draw text
        draw.text((line_x, current_y), line, font=title_font, fill=text_color)
        
        current_y += title_line_height + line_spacing
    
    # Position author below title
    author_bbox = draw.textbbox((0, 0), author, font=author_font)
    author_width = author_bbox[2] - author_bbox[0]
    author_x = (width - author_width) // 2
    author_y = current_y + 10
    
    # Draw author shadow
    draw.text((author_x + shadow_offset, author_y + shadow_offset), 
              author, font=author_font, fill=shadow_color)
    # Draw author
    draw.text((author_x, author_y), author, font=author_font, fill=text_color)
    
    print(f"[COVER ART] ✅ Text overlay added: '{title_upper}' ({len(title_lines)} lines) by {author}")
    return img


def generate_cover_image(metadata: dict) -> dict:
    """
    Generates book cover artwork using DALL-E (pure artwork),
    then adds title/author with Pillow.
    Creates 1:1 square cover only.
    """
    prompt = generate_cover_art_prompt(metadata)
    title = metadata.get("title", "Untitled")
    author = metadata.get("author", "Unknown")
    category = metadata.get("category", "Fiction")
    
    print(f"[COVER ART] Generating artwork for: {title}")
    
    client = get_openai()
    
    # Generate image with DALL-E 3 (pure artwork, no text)
    # Using 1024x1024 for direct 1:1 - no cropping needed!
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",  # Direct 1:1 square
        quality="hd",
        n=1
    )
    
    image_url = response.data[0].url
    print(f"[COVER ART] Artwork generated (1024x1024), downloading...")
    
    # Download the image
    image_response = requests.get(image_url)
    if image_response.status_code != 200:
        raise Exception(f"Failed to download image: {image_response.status_code}")
    
    # Open image with PIL
    artwork = Image.open(BytesIO(image_response.content)).convert("RGBA")
    width, height = artwork.size
    print(f"[COVER ART] Downloaded artwork size: {width}x{height}")
    
    # Add text overlay
    print(f"[COVER ART] Adding title and author text...")
    artwork_with_text = add_text_overlay(artwork, title, author, category)
    final_image = artwork_with_text.convert("RGB")
    
    # Upload to Supabase Storage
    supabase = get_supabase()
    book_id = metadata.get("book_id", str(uuid.uuid4()))
    
    print(f"[COVER ART] Uploading to Supabase Storage...")
    
    # Upload 1:1 version
    buffer = BytesIO()
    final_image.save(buffer, format="PNG")
    buffer.seek(0)
    
    file_name = f"covers/{book_id}_1x1.png"
    supabase.storage.from_("audio").upload(
        file_name,
        buffer.getvalue(),
        {"content-type": "image/png", "x-upsert": "true"}
    )
    url = supabase.storage.from_("audio").get_public_url(file_name)
    
    print(f"[COVER ART] ✅ Upload complete! 1:1 cover with text overlay")
    
    return {
        "cover_art_url": url
    }


def update_book_cover_url(book_id: str, cover_urls: dict):
    """
    Updates the book record with the cover art URL.
    """
    supabase = get_supabase()
    supabase.table("books").update({
        "cover_art_url": cover_urls.get("cover_art_url")
    }).eq("id", book_id).execute()
    print(f"[COVER ART] ✅ Updated book {book_id} with cover URL")
