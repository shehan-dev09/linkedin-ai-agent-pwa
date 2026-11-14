import io
import os
import random
import textwrap
from dotenv import load_dotenv
import feedparser
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
import requests

# Load environment variables
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("Missing GEMINI_API_KEY in the .env file!")


def get_available_gemini_models() -> list:
    """Dynamically fetches working text-generation models from your Google API key."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            models = res.json().get("models", [])
            valid_models = [
                m["name"]
                for m in models
                if "generateContent" in m.get("supportedGenerationMethods", [])
                and "vision" not in m["name"]
                and "embedding" not in m["name"]
                and "imagen" not in m["name"]
                and "tts" not in m["name"]
                and "audio" not in m["name"]
            ]
            valid_models.sort(
                key=lambda x: (
                    0
                    if "gemma-3-27b" in x
                    else 1
                    if "lite" in x
                    else 2
                    if "pro" in x
                    else 3
                    if "flash" in x
                    else 4
                )
            )
            return valid_models
    except Exception as e:
        print(f"[WARNING] Model discovery warning: {e}")

    return [
        "models/gemma-3-27b-it",
        "models/gemini-2.5-flash",
        "models/gemini-3.8-flash",
    ]


def generate_text_fast(prompt: str) -> str:
    """Calls the Google AI REST API directly with automatic model switching."""
    models = get_available_gemini_models()

    for model_name in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            res = requests.post(url, json=payload, timeout=12)
            if res.status_code == 200:
                data = res.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                print(f"[INFO] Generated text instantly using {model_name}")
                return text.strip()
        except Exception:
            continue

    raise RuntimeError(
        "All Google AI models on your key are currently rate-limited or busy."
    )


def fetch_latest_tech_news():
    """Fetches the latest AI, Machine Learning, LLM, and Deep Learning news."""
    print("[INFO] Fetching the latest AI/ML news...")
    rss_url = "https://news.google.com/rss/search?q=Artificial+Intelligence+OR+Machine+Learning+OR+LLM+OR+Deep+Learning&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(rss_url)

    if feed.entries:
        # Pick randomly from the top 5 latest AI/ML articles for variety
        top_entries = feed.entries[:5]
        selected_entry = random.choice(top_entries)
        source = (
            selected_entry.source.title
            if hasattr(selected_entry, "source")
            else "AI Research News"
        )
        clean_title = selected_entry.title.rsplit(" - ", 1)[0]
        return {
            "title": clean_title,
            "source": source,
            "link": selected_entry.link,
        }
    return None


def generate_linkedin_post(news_title: str, news_source: str) -> str:
    """Generates a clean, high-converting LinkedIn post from an AI/ML Engineer's perspective."""
    print("[INFO] Generating LinkedIn post content...")
    prompt = f"""
    You are Shehan Nadeesha, an AI/ML Engineer passionate about Machine Learning, LLMs, and Autonomous AI Agents.
    Write a sharp, insightful, and professional LinkedIn post based on this trending AI/ML news:
    
    Topic: {news_title}
    Source: {news_source}
    
    Strict Guidelines:
    - Start with a strong, scroll-stopping 'Hook' in the first line.
    - Keep paragraphs short (1-2 sentences) with clean spacing.
    - Include 3 bullet points (using 🔹 or •) explaining the technical or practical impact on AI/ML engineering, model deployment, or the future of AI.
    - End with a specific question for fellow AI/ML engineers and tech enthusiasts to spark discussion in the comments.
    - Add 'Source: {news_source}' neatly before the hashtags.
    - Include 4 relevant hashtags (e.g., #MachineLearning #AIEngineering #ArtificialIntelligence #LLMs) at the very bottom.
    - Strictly NO markdown bolding (do NOT use **text**) and NO raw URLs.
    """
    return generate_text_fast(prompt)


def generate_creative_image(
    news_title: str,
    news_source: str = "AI News",
    output_path: str = "static/generated_images/latest_post.jpg",
) -> str:
    """Generates an Apple iOS / visionOS 'Liquid Glass' (Glassmorphism) LinkedIn visual (1080x1080)

    branded specifically for Shehan Nadeesha | AI/ML Engineer.
    """
    print("[INFO] Designing Apple iOS 'Liquid Glass' visual card...")

    unsplash_ai_photos = [
        "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=1080&q=85",  # AI Neural Network concept
        "https://images.unsplash.com/photo-1518770660439-4636190af475?w=1080&q=85",  # GPU / AI Hardware Chip
        "https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=1080&q=85",  # ML Code on screen
        "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=1080&q=85",  # Data Matrix
        "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?w=1080&q=85",  # Cyber / Neural nodes
        "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1080&q=85",  # Global Data Network
    ]

    try:
        # 1. Load & prepare rich background image
        bg_url = random.choice(unsplash_ai_photos)
        res = requests.get(bg_url, timeout=10)
        bg_img = Image.open(io.BytesIO(res.content)).convert("RGBA")

        w, h = bg_img.size
        min_dim = min(w, h)
        bg_img = bg_img.crop(
            (
                (w - min_dim) // 2,
                (h - min_dim) // 2,
                (w + min_dim) // 2,
                (h + min_dim) // 2,
            )
        )
        bg_img = bg_img.resize((1080, 1080), Image.Resampling.LANCZOS)
        bg_img = ImageEnhance.Brightness(bg_img).enhance(0.45)

        # 2. Add Apple-style ambient glowing orbs on background for rich liquid glass refraction
        ambient_orbs = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
        orb_draw = ImageDraw.Draw(ambient_orbs)
        orb_draw.ellipse(
            [(60, 100), (520, 560)], fill=(14, 165, 233, 135)
        )  # Cyan glow top-left
        orb_draw.ellipse(
            [(560, 520), (1020, 980)], fill=(139, 92, 246, 135)
        )  # Indigo/Purple glow bottom-right
        ambient_orbs = ambient_orbs.filter(
            ImageFilter.GaussianBlur(radius=95)
        )
        base_canvas = Image.alpha_composite(bg_img, ambient_orbs)

        # Glass Card Coordinates (Centered Floating iOS Squircle)
        card_box = (75, 165, 1005, 915)
        card_radius = 52

        # 3. Create 3D Drop Shadow under the floating glass panel
        shadow_layer = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        shadow_draw.rounded_rectangle(
            (75, 190, 1005, 940), radius=card_radius, fill=(0, 0, 0, 165)
        )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=30))
        base_canvas = Image.alpha_composite(base_canvas, shadow_layer)

        # 4. Create the Frosted Liquid Glass Layer (Heavy Gaussian Blur of underlying pixels)
        blurred_bg = base_canvas.filter(ImageFilter.GaussianBlur(radius=32))

        # Add Liquid Glass surface sheen
        glass_sheen = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
        sheen_draw = ImageDraw.Draw(glass_sheen)
        for y in range(card_box[1], card_box[3]):
            progress = (y - card_box[1]) / (card_box[3] - card_box[1])
            alpha = int(58 * (1 - progress) + 22 * progress)
            sheen_draw.line(
                [(card_box[0], y), (card_box[2], y)],
                fill=(255, 255, 255, alpha),
            )

        frosted_glass = Image.alpha_composite(blurred_bg, glass_sheen)

        # Mask the frosted glass to the exact rounded squircle shape
        glass_mask = Image.new("L", (1080, 1080), 0)
        mask_draw = ImageDraw.Draw(glass_mask)
        mask_draw.rounded_rectangle(card_box, radius=card_radius, fill=255)

        base_canvas.paste(frosted_glass, (0, 0), glass_mask)

        # 5. Draw Specular Liquid Glass Rim
        overlay = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        draw.rounded_rectangle(
            card_box,
            radius=card_radius,
            outline=(255, 255, 255, 150),
            width=2,
        )
        inner_box = (
            card_box[0] + 3,
            card_box[1] + 3,
            card_box[2] - 3,
            card_box[3] - 3,
        )
        draw.rounded_rectangle(
            inner_box,
            radius=card_radius - 2,
            outline=(255, 255, 255, 45),
            width=1,
        )

        # 6. Load Fonts (Segoe UI / Arial)
        try:
            font_badge = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 22)
            font_title = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 50)
            font_source = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 24)
            font_author = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 24)
            font_role = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 19)
            font_initials = ImageFont.truetype(
                "C:/Windows/Fonts/segoeuib.ttf", 22
            )
        except Exception:
            font_badge = font_title = font_source = font_author = font_role = (
                font_initials
            ) = ImageFont.load_default()

        # 7. Draw Top Frosted Glass Pill Badge
        pill_box = (135, 230, 465, 284)
        draw.rounded_rectangle(
            pill_box,
            radius=27,
            fill=(255, 255, 255, 38),
            outline=(255, 255, 255, 120),
            width=1,
        )
        draw.ellipse([(155, 249), (171, 265)], fill=(56, 189, 248, 255))
        draw.text(
            (185, 242),
            "AI & ML ENGINEERING",
            fill=(255, 255, 255, 245),
            font=font_badge,
        )

        # 8. Draw Wrapped News Headline with subtle depth shadow
        wrapped_lines = textwrap.wrap(news_title, width=25)[:5]
        y_text = 345 if len(wrapped_lines) <= 4 else 320
        for line in wrapped_lines:
            draw.text(
                (137, y_text + 2), line, fill=(0, 0, 0, 110), font=font_title
            )
            draw.text(
                (135, y_text),
                line,
                fill=(255, 255, 255, 255),
                font=font_title,
            )
            y_text += 68

        # 9. Draw Frosted Divider Line & Personal Branding Footer
        draw.line(
            [(135, 775), (945, 775)], fill=(255, 255, 255, 65), width=2
        )

        # Left: News Source
        short_source = (
            news_source[:30] + "..." if len(news_source) > 33 else news_source
        )
        draw.text(
            (135, 818),
            f"Source: {short_source}",
            fill=(226, 232, 240, 215),
            font=font_source,
        )

        # Right: Author Glass Pill with "SN" Avatar + "Shehan Nadeesha" + "AI/ML Engineer"
        author_pill = (625, 795, 945, 872)
        draw.rounded_rectangle(
            author_pill,
            radius=38,
            fill=(255, 255, 255, 32),
            outline=(255, 255, 255, 95),
            width=1,
        )

        # Avatar circle inside pill
        draw.ellipse([(638, 809), (688, 859)], fill=(14, 165, 233, 240))
        draw.text(
            (663, 834),
            "SN",
            fill=(255, 255, 255, 255),
            font=font_initials,
            anchor="mm",
        )

        # Author Name & Role Title
        draw.text(
            (702, 806),
            "Shehan Nadeesha",
            fill=(255, 255, 255, 255),
            font=font_author,
        )
        draw.text(
            (702, 837),
            "AI/ML Engineer",
            fill=(56, 189, 248, 255),
            font=font_role,
        )

        # Finalize & Save Image
        final_card = Image.alpha_composite(base_canvas, overlay).convert("RGB")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        final_card.save(output_path, "JPEG", quality=95)
        print(
            f"[SUCCESS] Apple iOS Liquid Glass Visual saved at: {output_path}"
        )
        return output_path

    except Exception as e:
        print(f"[ERROR] Image generation failed: {e}")
        return None


# Test execution block
if __name__ == "__main__":
    news = fetch_latest_tech_news()
    if news:
        print(f"\n--- SELECTED TOPIC ---\n{news['title']}\n")

        post_content = generate_linkedin_post(news["title"], news["source"])
        print(f"\n--- GENERATED POST ---\n{post_content}\n----------------------\n")

        image_path = generate_creative_image(news["title"], news["source"])
    else:
        print("[ERROR] Could not retrieve any news articles.")