"""
Cover art generation module for Honora.
Generates artistic book cover images using DALL-E, then adds title/author
with Pillow for perfect typography.
"""
import os
import requests
import uuid
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter
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


# Genre-based font mapping (using system fonts available on most systems)
CATEGORY_FONTS = {
    "Philosophy": "Georgia",      # Serif, classic
    "Fiction": "Georgia",
    "Mystery": "Arial",           # Sans-serif, clean
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
    Generates a DALL-E prompt for PURE ARTWORK - no text.
    """
    title = metadata.get("title", "Untitled")
    category = metadata.get("category", "Fiction")
    synopsis = metadata.get("synopsis", "")
    
    # Visual styles based on category
    category_styles = {
        "Fiction": "cinematic, narrative imagery with depth and atmosphere",
        "Mystery": "dark, moody, shadowy atmosphere with hints of intrigue",
        "Romance": "warm, romantic lighting with soft, dreamy tones",
        "Fantasy": "magical, otherworldly landscapes with mystical elements",
        "Science Fiction": "futuristic, cosmic imagery with technology",
        "Biography": "dignified, personal, evocative portrait elements",
        "Self-Help": "uplifting, bright imagery symbolizing growth and transformation",
        "History": "historical imagery with period-appropriate grandeur",
        "Philosophy": "contemplative, symbolic imagery with ancient wisdom motifs",
        "Business": "professional, dynamic imagery of success and innovation",
        "Classic Literature": "elegant, timeless artistic style with rich detail",
        "Children": "colorful, whimsical, playful and imaginative",
        "Young Adult": "bold, energetic, emotionally resonant",
        "Poetry": "lyrical, artistic, emotionally evocative",
        "Religion": "sacred, peaceful, spiritually uplifting",
        "Science": "scientific wonder, discovery, precision",
        "Non-Fiction": "authentic, documentary-style, compelling"
    }
    
    style = category_styles.get(category, "cinematic, narrative imagery")
    
    # Create prompt for PURE ARTWORK - NO TEXT
    prompt = f"""Create stunning visual artwork for a book called "{title}".

CRITICAL: NO TEXT, NO LETTERS, NO WORDS, NO TYPOGRAPHY in the image. Pure visual art only.

VISUAL CONTENT:
- The imagery should represent the book's themes: {synopsis[:250] if synopsis else 'inspired by the title'}
- Style: {style}
- Include symbolic visual elements that represent the book's subject matter
- Rich, detailed, high-quality digital art

COMPOSITION:
- Leave space in the lower third for text to be added later
- The main visual elements should be in the upper two-thirds
- The image should work as a beautiful background for a book cover

Format: Square, 1024x1024, with visual focus in center-upper area."""

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


def add_text_overlay(image: Image.Image, title: str, author: str, category: str) -> Image.Image:
    """
    Adds title and author text to the image using Pillow.
    Automatically chooses text color based on background brightness.
    """
    img = image.copy()
    draw = ImageDraw.Draw(img)
    width, height = img.size
    
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
    
    # Try to load a nice font, fallback to default
    try:
        # Try common font paths
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",  # Linux
            "/System/Library/Fonts/Georgia.ttf",  # macOS
            "/System/Library/Fonts/Supplemental/Georgia.ttf",  # macOS newer
            "C:/Windows/Fonts/georgia.ttf",  # Windows
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",  # Linux alt
        ]
        
        title_font = None
        author_font = None
        
        for path in font_paths:
            if os.path.exists(path):
                title_font = ImageFont.truetype(path, 72)
                author_font = ImageFont.truetype(path, 36)
                break
        
        if title_font is None:
            # Fallback to default font with larger size
            title_font = ImageFont.load_default()
            author_font = ImageFont.load_default()
            
    except Exception:
        title_font = ImageFont.load_default()
        author_font = ImageFont.load_default()
    
    # Calculate text positions
    # Title in lower third, centered
    title_upper = title.upper()
    
    # Get text bounding box
    title_bbox = draw.textbbox((0, 0), title_upper, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    title_height = title_bbox[3] - title_bbox[1]
    
    author_bbox = draw.textbbox((0, 0), author, font=author_font)
    author_width = author_bbox[2] - author_bbox[0]
    
    # Position title centered, in lower portion
    title_x = (width - title_width) // 2
    title_y = int(height * 0.75)
    
    # Position author below title
    author_x = (width - author_width) // 2
    author_y = title_y + title_height + 20
    
    # Draw shadow for better readability
    shadow_offset = 3
    
    # Draw title shadow
    draw.text((title_x + shadow_offset, title_y + shadow_offset), 
              title_upper, font=title_font, fill=shadow_color)
    # Draw title
    draw.text((title_x, title_y), title_upper, font=title_font, fill=text_color)
    
    # Draw author shadow
    draw.text((author_x + shadow_offset, author_y + shadow_offset), 
              author, font=author_font, fill=shadow_color)
    # Draw author
    draw.text((author_x, author_y), author, font=author_font, fill=text_color)
    
    return img


def generate_cover_image(metadata: dict) -> dict:
    """
    Generates book cover artwork using DALL-E (pure artwork),
    then adds title/author with Pillow.
    Creates two versions: 1:1 (square) and 2:3 (book format).
    """
    prompt = generate_cover_art_prompt(metadata)
    title = metadata.get("title", "Untitled")
    author = metadata.get("author", "Unknown")
    category = metadata.get("category", "Fiction")
    
    print(f"[COVER ART] Generating artwork for: {title}")
    
    client = get_openai()
    
    # Generate image with DALL-E 3 (pure artwork, no text)
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="hd",
        n=1
    )
    
    image_url = response.data[0].url
    print(f"[COVER ART] Artwork generated, downloading...")
    
    # Download the image
    image_response = requests.get(image_url)
    if image_response.status_code != 200:
        raise Exception(f"Failed to download image: {image_response.status_code}")
    
    # Open image with PIL
    artwork = Image.open(BytesIO(image_response.content)).convert("RGBA")
    
    # Add text overlay with Pillow
    print(f"[COVER ART] Adding title and author text...")
    cover_with_text = add_text_overlay(artwork, title, author, category)
    
    # Convert back to RGB for saving as PNG
    final_image = cover_with_text.convert("RGB")
    
    # Create 1:1 version
    square_image = final_image.copy()
    
    # Create 2:3 version by cropping from center
    width_2x3 = int(1024 * 2 / 3)  # 682
    left = (1024 - width_2x3) // 2
    portrait_image = final_image.crop((left, 0, left + width_2x3, 1024))
    
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
    
    print(f"[COVER ART] Upload complete: 1:1 and 2:3 versions with text overlay")
    
    return {
        "cover_art_url": url_1x1,
        "cover_art_url_2x3": url_2x3
    }


def update_book_cover_url(book_id: str, cover_urls: dict):
    """
    Updates the book record with both cover art URLs.
    """
    supabase = get_supabase()
    supabase.table("books").update({
        "cover_art_url": cover_urls.get("cover_art_url"),
        "cover_art_url_2x3": cover_urls.get("cover_art_url_2x3")
    }).eq("id", book_id).execute()
    print(f"[COVER ART] Updated book {book_id} with both cover URLs")
