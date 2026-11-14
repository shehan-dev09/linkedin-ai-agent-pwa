import os
import time
import random
import textwrap
from io import BytesIO
from pathlib import Path
from datetime import datetime
import feedparser
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
from dotenv import load_dotenv

from app.storage import is_topic_seen, mark_topic_seen

# Load environment variables from .env file
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

IMAGE_DIR = Path("static/generated_images")
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
AVATAR_PATH = Path("static/avatar.jpg")

# Curated high-resolution editorial tech backgrounds (100% watermark-free)
UNSPLASH_TECH_BACKGROUNDS = [
    "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1509228468518-180dd4864904?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=1200&q=85"
]

# RSS feeds focused on strictly recent AI/ML breakthroughs
RSS_FEEDS = [
    # Primary: Last 24 hours AI/ML news
    "https://news.google.com/rss/search?q=(Artificial+Intelligence+OR+Machine+Learning+OR+LLM+OR+Deep+Learning)+when:1d&hl=en-US&gl=US&ceid=US:en",
    # Secondary fallback: Last 7 days if all 24h stories were already used
    "https://news.google.com/rss/search?q=(OpenAI+OR+Anthropic+OR+PyTorch+OR+NVIDIA+AI+OR+Hugging+Face)+when:7d&hl=en-US&gl=US&ceid=US:en"
]


def get_available_gemini_models() -> list[str]:
    """Query Google API dynamically to find active text generation models."""
    if not GEMINI_API_KEY:
        return []
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return []

        data = resp.json()
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in methods and ("gemini" in name or "gemma" in name):
                if not any(skip in name for skip in ["vision", "image", "tts", "audio", "embedding", "robotics"]):
                    models.append(name)

        def priority_key(model_name: str) -> int:
            if "gemma-3-27b-it" in model_name:
                return 0
            if "lite" in model_name:
                return 1
            if "pro" in model_name:
                return 2
            if "flash" in model_name:
                return 3
            return 4

        models.sort(key=priority_key)
        return models
    except Exception as e:
        print(f"⚠️ Failed to list Gemini models: {e}")
        return []


def generate_text_fast(prompt: str) -> str:
    """Call Gemini REST API directly with strict timeout and automatic fallback."""
    models = get_available_gemini_models()
    if not models:
        models = ["models/gemma-3-27b-it", "models/gemini-2.0-flash-lite", "models/gemini-2.5-pro"]

    for model_name in models[:5]:
        try:
            print(f"🤖 Trying AI model: {model_name}...")
            url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 650}
            }
            response = requests.post(url, json=payload, timeout=12)

            if response.status_code == 200:
                data = response.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        text = parts[0]["text"].strip()
                        if len(text) > 80:
                            print(f"✅ Text generated via {model_name}!")
                            return text
            else:
                print(f"⚠️ {model_name} HTTP {response.status_code}. Switching model...")
        except Exception as e:
            print(f"⚠️ {model_name} timed out or failed ({e}). Switching model...")

    return ""


def fetch_latest_tech_news() -> dict:
    """
    Fetch the latest AI/ML news sorted strictly from newest to oldest,
    filtering out any article that has already been generated in SQLite.
    """
    print("🔍 Scanning live AI/ML RSS feeds for the latest unseen news...")

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        if not feed.entries:
            continue

        # Sort entries chronologically (newest published timestamp first)
        sorted_entries = sorted(
            feed.entries,
            key=lambda entry: entry.get("published_parsed") or time.gmtime(0),
            reverse=True
        )

        for entry in sorted_entries:
            raw_title = entry.get("title", "New AI Breakthrough")
            clean_title = raw_title.rsplit(" - ", 1)[0].strip()
            link = entry.get("link", "")
            source = entry.get("source", {}).get("title", "AI Research Wire")
            published_str = entry.get("published", datetime.now().strftime("%Y-%m-%d %H:%M UTC"))

            # Check SQLite deduplication table so we NEVER repeat an old news topic
            if not is_topic_seen(clean_title, link):
                mark_topic_seen(clean_title, link, source)
                print(f"✨ Selected fresh unseen news: {clean_title} ({published_str})")
                return {
                    "title": clean_title,
                    "link": link,
                    "published": published_str,
                    "source": source
                }

    # Ultimate fallback if somehow every single article in the feed was seen
    fallback_entry = feedparser.parse(RSS_FEEDS[0]).entries[0]
    clean_title = fallback_entry.title.rsplit(" - ", 1)[0].strip()
    return {
        "title": clean_title,
        "link": fallback_entry.link,
        "published": fallback_entry.get("published", "Just now"),
        "source": fallback_entry.get("source", {}).get("title", "AI News")
    }


def generate_linkedin_post(news_item: dict) -> dict:
    """Generate an authentic AI/ML Engineer LinkedIn post."""
    prompt = f"""
    You are an experienced AI/ML Engineer and Technical Thought Leader writing a high-impact LinkedIn post.
    
    News Title: {news_item['title']}
    News Source: {news_item['source']}
    
    Instructions:
    1. Write an engaging, insightful LinkedIn post from the perspective of an AI/ML Engineer analyzing this news.
    2. Start with a strong hook on the first line (NO clichés like "Exciting news!" or "Buckle up!").
    3. Use short, clean paragraphs with empty lines between them for mobile readability.
    4. Provide 3 concise bullet points explaining the technical impact on AI/ML workflows, model deployment, or real-world AI engineering.
    5. End with a thoughtful technical question to encourage comments from fellow AI engineers and developers.
    6. Include 4 to 5 relevant hashtags at the bottom (e.g., #MachineLearning #AIEngineering #ArtificialIntelligence #LLM #DeepLearning).
    7. Do NOT include any markdown formatting like **bold** or ## headers because LinkedIn plain text does not render markdown.
    8. Output ONLY the final LinkedIn post text.
    """

    post_text = generate_text_fast(prompt)
    clean_Headline = news_item['title']

    if not post_text:
        post_text = (
            f"{clean_Headline}\n\n"
            f"The pace of innovation across AI and Machine Learning infrastructure continues to accelerate. "
            f"According to recent updates from {news_item['source']}, this development marks an important shift for applied AI engineering.\n\n"
            f"Key takeaways for AI/ML Engineers:\n"
            f"• Model Efficiency: Pushing higher performance-per-compute ratios in production workloads.\n"
            f"• Deployment Architecture: Changing how teams design scalable inference and agentic pipelines.\n"
            f"• Production Readiness: Moving rapidly from research benchmarks into real-world AI systems.\n\n"
            f"How do you see this impacting your ML pipelines or AI stack over the next quarter?\n\n"
            f"Read more: {news_item['link']}\n\n"
            f"#AIEngineering #MachineLearning #ArtificialIntelligence #DeepLearning #TechInnovation"
        )
    else:
        post_text = post_text.replace("**", "").replace("##", "").strip()
        if news_item["link"] not in post_text:
            post_text += f"\n\nSource: {news_item['link']}"

    return {
        "post_text": post_text,
        "image_prompt": "iOS Liquid Glass Visual Card (1080x1080)"
    }


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load clean system sans-serif fonts on Windows/Linux with safe fallback."""
    candidates = (
        ["segoeuib.ttf", "arialbd.ttf", "calibrib.ttf", "DejaVuSans-Bold.ttf"]
        if bold else
        ["segoeui.ttf", "arial.ttf", "calibri.ttf", "DejaVuSans.ttf"]
    )
    for font_name in candidates:
        try:
            return ImageFont.truetype(font_name, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _create_liquid_glass_background() -> Image.Image:
    """Fetch a high-res photo or build a deep rich gradient background."""
    bg_url = random.choice(UNSPLASH_TECH_BACKGROUNDS)
    try:
        resp = requests.get(bg_url, timeout=8)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGBA")
            img = img.resize((1080, 1080), Image.Resampling.LANCZOS)
            img = ImageEnhance.Brightness(img).enhance(0.68)
            img = ImageEnhance.Color(img).enhance(1.30)
            return img
    except Exception as e:
        print(f"⚠️ Background fetch fallback used: {e}")

    img = Image.new("RGBA", (1080, 1080), (12, 16, 32, 255))
    draw = ImageDraw.Draw(img)
    for y in range(1080):
        r = int(14 + (y / 1080) * 28)
        g = int(20 + (y / 1080) * 15)
        b = int(48 + (y / 1080) * 65)
        draw.line([(0, y), (1080, y)], fill=(r, g, b, 255))
    return img


def _paste_circular_avatar(canvas: Image.Image, draw: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    """Render user's real profile picture as a circle, or fallback to SN badge."""
    if AVATAR_PATH.exists():
        try:
            avatar_img = Image.open(AVATAR_PATH).convert("RGBA")
            avatar_img = ImageOps.fit(avatar_img, (size, size), Image.Resampling.LANCZOS)

            mask = Image.new("L", (size, size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, size, size), fill=255)

            canvas.paste(avatar_img, (x, y), mask)
            draw.ellipse([x, y, x + size, y + size], outline=(255, 255, 255, 210), width=3)
            return
        except Exception as e:
            print(f"⚠️ Avatar load error: {e}")

    font_avatar = _load_font(26, bold=True)
    draw.ellipse([x, y, x + size, y + size], fill=(56, 189, 248, 45), outline=(56, 189, 248, 200), width=2)
    draw.text((x + 17, y + 18), "SN", font=font_avatar, fill=(255, 255, 255, 255))


def generate_creative_image(image_prompt: str, headline: str = "", source: str = "AI RESEARCH") -> str:
    """
    Create an Apple iOS Liquid Glass 1080x1080 visual card featuring
    Shehan Nadeesha | AI/ML Engineer and real profile photo.
    """
    print("🎨 Rendering iOS Liquid Glass 1080x1080 card...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    image_path = IMAGE_DIR / f"post_{timestamp}.jpg"

    base_img = _create_liquid_glass_background()

    # Ambient light orbs behind glass
    glow_layer = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    glow_draw.ellipse([80, 80, 560, 560], fill=(56, 189, 248, 95))
    glow_draw.ellipse([540, 500, 1000, 960], fill=(139, 92, 246, 95))
    glow_draw.ellipse([260, 620, 680, 1020], fill=(16, 185, 129, 65))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=95))
    base_img = Image.alpha_composite(base_img, glow_layer)

    # Frosted Liquid Glass Card
    card_box = (85, 115, 995, 965)
    card_w = card_box[2] - card_box[0]
    card_h = card_box[3] - card_box[1]

    cropped_region = base_img.crop(card_box).filter(ImageFilter.GaussianBlur(radius=38))
    cropped_region = ImageEnhance.Brightness(cropped_region).enhance(1.12)

    mask = Image.new("L", (card_w, card_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, card_w, card_h], radius=56, fill=255)

    frost_tint = Image.new("RGBA", (card_w, card_h), (255, 255, 255, 0))
    tint_draw = ImageDraw.Draw(frost_tint)
    for y in range(card_h):
        alpha = int(58 - (y / card_h) * 32)
        tint_draw.line([(0, y), (card_w, y)], fill=(255, 255, 255, max(18, alpha)))

    sheen = Image.new("RGBA", (card_w, card_h), (255, 255, 255, 0))
    sheen_draw = ImageDraw.Draw(sheen)
    sheen_draw.polygon([(0, 0), (card_w, 0), (int(card_w * 0.65), int(card_h * 0.45)), (0, int(card_h * 0.25))], fill=(255, 255, 255, 22))

    frosted_card = Image.alpha_composite(cropped_region, frost_tint)
    frosted_card = Image.alpha_composite(frosted_card, sheen)

    shadow = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle([card_box[0] + 10, card_box[1] + 24, card_box[2] + 10, card_box[3] + 24], radius=56, fill=(0, 0, 0, 115))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=30))
    base_img = Image.alpha_composite(base_img, shadow)

    base_img.paste(frosted_card, (card_box[0], card_box[1]), mask)

    overlay = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    draw.rounded_rectangle(card_box, radius=56, outline=(255, 255, 255, 115), width=3)
    draw.rounded_rectangle([card_box[0] + 3, card_box[1] + 3, card_box[2] - 3, card_box[3] - 3], radius=53, outline=(255, 255, 255, 35), width=1)

    font_pill = _load_font(23, bold=True)
    font_title = _load_font(52, bold=True)
    font_source = _load_font(25, bold=False)
    font_brand = _load_font(28, bold=True)
    font_role = _load_font(23, bold=False)

    pill_box = [145, 180, 465, 234]
    draw.rounded_rectangle(pill_box, radius=27, fill=(255, 255, 255, 38), outline=(255, 255, 255, 120), width=2)
    draw.ellipse([167, 198, 185, 216], fill=(56, 189, 248, 255))
    draw.text((200, 192), "AI / ML BRIEFING", font=font_pill, fill=(255, 255, 255, 250))

    clean_title = headline if headline else "Next-Gen Breakthrough in Artificial Intelligence"
    wrapped_lines = textwrap.wrap(clean_title, width=24)[:6]

    y_cursor = 285
    for line in wrapped_lines:
        draw.text((147, y_cursor + 2), line, font=font_title, fill=(0, 0, 0, 95))
        draw.text((145, y_cursor), line, font=font_title, fill=(255, 255, 255, 252))
        y_cursor += 70

    source_y = max(y_cursor + 20, 720)
    draw.rounded_rectangle([145, source_y, 215, source_y + 6], radius=3, fill=(56, 189, 248, 230))
    draw.text((145, source_y + 22), f"SOURCE  •  {source.upper()[:36]}", font=font_source, fill=(225, 232, 240, 220))

    draw.line([(145, 815), (935, 815)], fill=(255, 255, 255, 50), width=2)

    final_img = Image.alpha_composite(base_img, overlay)
    final_draw = ImageDraw.Draw(final_img)

    _paste_circular_avatar(final_img, final_draw, x=145, y=840, size=72)

    final_draw.text((235, 845), "Shehan Nadeesha", font=font_brand, fill=(255, 255, 255, 250))
    final_draw.text((235, 882), "AI/ML Engineer", font=font_role, fill=(195, 210, 230, 215))

    final_img.convert("RGB").save(image_path, "JPEG", quality=95)
    print(f"✅ Liquid Glass image saved to {image_path}")
    return str(image_path)


def run_agent_workflow() -> dict:
    """Execute the full pipeline: fetch fresh unseen news, write post, and render image."""
    news = fetch_latest_tech_news()
    content = generate_linkedin_post(news)
    image_path = generate_creative_image(
        content["image_prompt"],
        headline=news["title"],
        source=news["source"]
    )

    return {
        "news": news,
        "post_text": content["post_text"],
        "image_prompt": content["image_prompt"],
        "image_path": image_path
    }