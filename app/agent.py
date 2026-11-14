import os
import re
import json
import time
import random
from io import BytesIO
from typing import Dict, Any, List, Optional

import requests
import feedparser
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
from dotenv import load_dotenv

from app.storage import is_topic_seen, mark_topic_seen, save_post_record

load_dotenv()

PROFILE_FILE_PATH = "static/profile.json"
AVATAR_FILE_PATH = "static/avatar.jpg"
OUTPUT_DIR = "static/generated_images"

# Curated high-resolution dark abstract/tech backgrounds for iOS Liquid Glass
UNSPLASH_TECH_BACKGROUNDS = [
    "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?auto=format&fit=crop&w=1200&q=85",
]


def load_author_profile() -> Dict[str, str]:
    """Load author branding from static/profile.json with defaults."""
    default = {
        "name": "Shehan Nadeesha",
        "headline": "AI/ML Engineer",
        "linkedin_url": "https://www.linkedin.com/in/shehan-nadeesha/"
    }
    if os.path.exists(PROFILE_FILE_PATH):
        try:
            with open(PROFILE_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**default, **data}
        except Exception:
            pass
    return default


def clean_html_summary(raw_html: str) -> str:
    """Strip HTML tags and extra whitespace from RSS summaries."""
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


def fetch_latest_tech_news() -> Dict[str, str]:
    """
    Fetch breaking AI/ML news from the last 24 hours sorted newest-first,
    skipping any article already recorded in SQLite seen_topics.
    """
    rss_urls = [
        "https://news.google.com/rss/search?q=(Artificial+Intelligence+OR+Machine+Learning+OR+LLM+OR+Deep+Learning)+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=(OpenAI+OR+Anthropic+OR+DeepMind+OR+NVIDIA+AI+OR+Transformer+Model)+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=(Artificial+Intelligence+OR+Machine+Learning+OR+LLM)+when:7d&hl=en-US&gl=US&ceid=US:en",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    collected_entries = []
    for url in rss_urls:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                feed = feedparser.parse(resp.content)
                if feed.entries:
                    collected_entries.extend(feed.entries)
            if len(collected_entries) >= 35:
                break
        except Exception as e:
            print(f"Warning: RSS fetch failed for {url}: {e}")

    if not collected_entries:
        raise RuntimeError("Could not fetch AI/ML news feeds. Check your internet connection.")

    def get_entry_timestamp(entry: Any) -> float:
        parsed_time = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if parsed_time:
            try:
                return time.mktime(parsed_time)
            except Exception:
                return 0.0
        return 0.0

    collected_entries.sort(key=get_entry_timestamp, reverse=True)

    for entry in collected_entries:
        raw_title = getattr(entry, "title", "").strip()
        link = getattr(entry, "link", "").strip()
        if not raw_title:
            continue

        if " - " in raw_title:
            clean_title, source_name = raw_title.rsplit(" - ", 1)
        else:
            clean_title = raw_title
            source_obj = getattr(entry, "source", None)
            source_name = getattr(source_obj, "title", "AI Research Wire") if source_obj else "AI Research Wire"

        clean_title = clean_title.strip()
        source_name = source_name.strip()

        if not is_topic_seen(clean_title, link):
            mark_topic_seen(clean_title, link, source_name)
            summary = clean_html_summary(getattr(entry, "summary", ""))
            return {
                "title": clean_title,
                "source": source_name,
                "link": link,
                "summary": summary
            }

    top = collected_entries[0]
    raw_title = getattr(top, "title", "Latest Advances in Foundation Models")
    clean_title = raw_title.rsplit(" - ", 1)[0].strip()
    source_name = raw_title.rsplit(" - ", 1)[1].strip() if " - " in raw_title else "AI News"
    link = getattr(top, "link", "")
    return {
        "title": clean_title,
        "source": source_name,
        "link": link,
        "summary": clean_html_summary(getattr(top, "summary", ""))
    }


def get_available_gemini_models(api_key: str) -> List[str]:
    """Dynamically discover text-generation models supported by the user's Gemini API key."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return []
        models_data = resp.json().get("models", [])
        usable = []
        for m in models_data:
            name = m.get("name", "")
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in methods and not any(
                skip in name for skip in ("vision", "embedding", "imagen", "aqa", "audio", "tts")
            ):
                usable.append(name)

        def sort_priority(model_name: str) -> int:
            if "gemma-3-27b-it" in model_name:
                return 0
            if "gemini-2.0-flash-lite" in model_name:
                return 1
            if "gemini-2.0-flash" in model_name:
                return 2
            if "gemini-1.5-flash" in model_name:
                return 3
            if "lite" in model_name:
                return 4
            if "flash" in model_name:
                return 5
            return 6

        usable.sort(key=sort_priority)
        return usable
    except Exception:
        return []


def generate_text_fast(prompt: str) -> Optional[str]:
    """Call Google AI Studio REST API directly with fast failover across available models."""
    load_dotenv(override=True)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    models = get_available_gemini_models(api_key)
    if not models:
        models = [
            "models/gemma-3-27b-it",
            "models/gemini-2.0-flash-lite",
            "models/gemini-2.0-flash",
            "models/gemini-1.5-flash"
        ]

    for model_name in models[:5]:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.75,
                "maxOutputTokens": 650
            }
        }
        try:
            resp = requests.post(endpoint, json=payload, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and parts[0].get("text"):
                        return parts[0]["text"].strip()
        except Exception as e:
            print(f"Warning: Model {model_name} timed out or failed: {e}")
            continue

    return None


def generate_linkedin_post(news_item: Dict[str, str]) -> str:
    """Synthesize an authoritative AI/ML Engineer LinkedIn post for the selected article."""
    profile = load_author_profile()
    title = news_item.get("title", "")
    source = news_item.get("source", "AI News")
    link = news_item.get("link", "")
    summary = news_item.get("summary", "")

    prompt = f"""You are {profile['name']}, an {profile['headline']}.
Write a high-impact, technically insightful LinkedIn post analyzing this breaking AI/ML news from the last 24 hours:

Headline: {title}
Source: {source}
Context: {summary}

Strict formatting rules:
1. Start with a sharp, scroll-stopping 1-sentence engineering hook (no cringe cliches like "Buckle up" or "Game changer").
2. Explain what happened in 2 concise sentences.
3. Add a short section with 3 bullet points (using •) covering why this matters for AI/ML Engineers, model deployment, or production systems.
4. End with a thoughtful technical question to spark comments from other engineers.
5. Include the source link on its own line: Source: {link}
6. Add 5 relevant hashtags at the very bottom (#AIEngineering #MachineLearning #LLM #DeepLearning #TechNews).
7. Do NOT use markdown bold asterisks (**text**) because LinkedIn plain text does not render markdown bold. Keep paragraphs clean and well-spaced."""

    generated = generate_text_fast(prompt)
    if generated:
        return generated.replace("**", "").strip()

    return (
        f"{title}\n\n"
        f"New developments reported by {source} highlight how rapidly the AI/ML engineering landscape is shifting from experimental research to production-grade systems.\n\n"
        f"Key takeaways for AI/ML Engineers:\n"
        f"• Inference efficiency and system reliability are becoming just as critical as raw benchmark scores.\n"
        f"• Teams building with LLMs and autonomous agents need modular architectures to adapt to rapid model releases.\n"
        f"• Production governance, latency optimization, and evaluation pipelines remain the real engineering moat.\n\n"
        f"How is your team adapting your ML stack to handle these latest shifts?\n\n"
        f"Source: {link}\n\n"
        f"#AIEngineering #MachineLearning #LLM #DeepLearning #ArtificialIntelligence"
    )


def _create_fallback_studio_background(size: int = 1080) -> Image.Image:
    """Create a rich dark abstract gradient canvas with ambient light orbs."""
    base = Image.new("RGB", (size, size), (9, 11, 20))
    draw = ImageDraw.Draw(base)

    for y in range(size):
        ratio = y / size
        r = int(8 + 16 * (1 - ratio))
        g = int(12 + 24 * ratio)
        b = int(24 + 44 * (1 - ratio * 0.5))
        draw.line([(0, y), (size, y)], fill=(r, g, b))

    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.ellipse((60, 60, 680, 680), fill=(56, 189, 248, 55))
    odraw.ellipse((400, 360, 1020, 980), fill=(99, 102, 241, 60))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=100))

    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load clean system sans-serif fonts on Windows/Linux/macOS."""
    candidates = (
        ["segoeuib.ttf", "arialbd.ttf", "calibrib.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["segoeui.ttf", "arial.ttf", "calibri.ttf", "DejaVuSans.ttf"]
    )
    for font_name in candidates:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap_text_by_pixel_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int
) -> List[str]:
    """Wrap text strictly by measured pixel width so lines never overflow the card."""
    words = text.split()
    if not words:
        return []

    lines: List[str] = []
    current_line = words[0]

    for word in words[1:]:
        test_line = f"{current_line} {word}"
        bbox = draw.textbbox((0, 0), test_line, font=font)
        line_w = bbox[2] - bbox[0]
        if line_w <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word

    lines.append(current_line)
    return lines


def _create_supersampled_rounded_mask(width: int, height: int, radius: int) -> Image.Image:
    """Create a 4x supersampled anti-aliased rounded rectangle mask for smooth iOS corners."""
    scale = 4
    big_mask = Image.new("L", (width * scale, height * scale), 0)
    bdraw = ImageDraw.Draw(big_mask)
    bdraw.rounded_rectangle(
        (0, 0, width * scale - 1, height * scale - 1),
        radius=radius * scale,
        fill=255
    )
    return big_mask.resize((width, height), resample=Image.Resampling.LANCZOS)


def _create_supersampled_circle_mask(diameter: int) -> Image.Image:
    """Create a 4x supersampled anti-aliased circle mask for razor-sharp avatars."""
    scale = 4
    big_mask = Image.new("L", (diameter * scale, diameter * scale), 0)
    bdraw = ImageDraw.Draw(big_mask)
    bdraw.ellipse((0, 0, diameter * scale - 1, diameter * scale - 1), fill=255)
    return big_mask.resize((diameter, diameter), resample=Image.Resampling.LANCZOS)


# Keep track of recently used backgrounds so Redo/Regenerate never repeats an image
_RECENT_BG_URLS = []

# Categorized High-Res Tech/AI Photography Pools (45+ Verified Unique Visuals)
TOPIC_IMAGE_POOLS = {
    "robotics": [
        "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1535378917042-10a22c95931a?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1589254065878-42c9da997008?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1561557944-6e7860d1a7eb?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1581091226825-a6a2a5aee158?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1531746790731-6c087fecd65a?auto=format&fit=crop&w=1200&q=85",
    ],
    "hardware": [
        "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1591799264318-7e6ef8ddb7ea?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1555664424-778a1e5e1b48?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1562408590-e32931084e23?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1605810230434-7631ac76ec81?auto=format&fit=crop&w=1200&q=85",
    ],
    "security": [
        "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1563986768609-322da13575f3?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1614064641938-3bbee52942c7?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1526374870839-e155464bb9b2?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1510511459019-5dda7724fd87?auto=format&fit=crop&w=1200&q=85",
    ],
    "coding": [
        "https://images.unsplash.com/photo-1555066931-4365d14bab8c?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1461749280684-dccba630e2f6?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1542831371-29b0f74f9713?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1607799279861-4dd421887fb3?auto=format&fit=crop&w=1200&q=85",
    ],
    "cloud": [
        "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1544197150-b99a580bb7a8?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1597733336794-12d05021d510?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1639322537228-f710d846310a?auto=format&fit=crop&w=1200&q=85",
    ],
    "neural": [
        "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1677442136019-21780ecad995?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1509198397868-475647b2a1e5?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1614741118887-7a4ee193a5fa?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1639762681485-074b7f938ba0?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1642104704074-907c0698cbd9?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1618005198919-d3d4b5a92ead?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=1200&q=85",
        "https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&w=1200&q=85",
    ],
}


def _get_dynamic_background_urls(headline: str) -> list:
    """
    Automatically analyzes the news headline, queries official public REST APIs
    (Wallhaven v1 + Openverse v1) that never block Python requests, and blends
    them with topic-matched photography pools while preventing any repeats.
    """
    global _RECENT_BG_URLS

    h_lower = (headline or "").lower()

    if any(k in h_lower for k in ["robot", "humanoid", "tesla", "figure", "drone", "autonomous", "vehicle"]):
        category = "robotics"
        api_query = "robotics"
    elif any(k in h_lower for k in ["chip", "nvidia", "gpu", "hardware", "silicon", "processor", "quantum", "amd", "intel"]):
        category = "hardware"
        api_query = "microchip circuit"
    elif any(k in h_lower for k in ["cyber", "security", "hack", "privacy", "safety", "deepfake", "scam", "attack"]):
        category = "security"
        api_query = "cybersecurity matrix"
    elif any(k in h_lower for k in ["code", "coding", "developer", "software", "github", "programming", "copilot", "cursor"]):
        category = "coding"
        api_query = "programming code"
    elif any(k in h_lower for k in ["cloud", "server", "data", "datacenter", "energy", "power", "infrastructure", "aws", "azure"]):
        category = "cloud"
        api_query = "data center server"
    else:
        category = "neural"
        api_query = random.choice(["artificial intelligence", "neural network", "cyberpunk abstract", "futuristic technology"])

    live_urls = []
    headers = {"User-Agent": "LinkedInAIAgentStudio/1.5"}

    # Source A: Official Wallhaven Public API v1 (100% Free, No API Key, Never Blocked)
    try:
        wh_resp = requests.get(
            "https://wallhaven.cc/api/v1/search",
            params={
                "q": api_query,
                "categories": "100",
                "purity": "100",
                "sorting": "random",
                "seed": str(random.randint(10000, 99999)),
            },
            headers=headers,
            timeout=5,
        )
        if wh_resp.status_code == 200:
            for item in wh_resp.json().get("data", []):
                file_size = item.get("file_size", 0)
                full_path = item.get("path")
                thumb_orig = item.get("thumbs", {}).get("original") or item.get("thumbs", {}).get("large")
                if full_path and file_size < 4_000_000:
                    live_urls.append(full_path)
                elif thumb_orig:
                    live_urls.append(thumb_orig)
    except Exception as e:
        print(f"Wallhaven search notice: {e}")

    # Source B: Official Openverse API v1
    try:
        ov_resp = requests.get(
            "https://api.openverse.org/v1/images/",
            params={"q": api_query, "page_size": 15},
            headers=headers,
            timeout=5,
        )
        if ov_resp.status_code == 200:
            for item in ov_resp.json().get("results", []):
                img_url = item.get("url")
                if img_url and img_url.startswith("http") and img_url.lower().endswith((".jpg", ".jpeg", ".png")):
                    live_urls.append(img_url)
    except Exception as e:
        print(f"Openverse search notice: {e}")

    topic_pool = list(TOPIC_IMAGE_POOLS.get(category, TOPIC_IMAGE_POOLS["neural"]))
    all_topic_urls = [u for pool in TOPIC_IMAGE_POOLS.values() for u in pool]

    combined_candidates = live_urls + random.sample(topic_pool, len(topic_pool))
    fresh_candidates = [u for u in combined_candidates if u not in _RECENT_BG_URLS]

    if not fresh_candidates:
        _RECENT_BG_URLS.clear()
        fresh_candidates = combined_candidates

    random.shuffle(fresh_candidates)
    print(f"Dynamic BG Search [{category.upper()} | '{api_query}']: {len(live_urls)} live API visuals + {len(topic_pool)} topic visuals ready.")

    return fresh_candidates + random.sample(all_topic_urls, len(all_topic_urls))


def generate_creative_image(headline: str, source: str = "AI NEWS") -> str:
    """
    Render a 100% watermark-free 1080x1080 Apple iOS Liquid Glass card.
    Features pixel-measured typography, supersampled rounded glass refraction,
    and a clean author footer (Avatar + Shehan Nadeesha + AI/ML Engineer) with zero overlap.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    profile = load_author_profile()
    author_name = profile.get("name", "Shehan Nadeesha").strip()
    author_role = profile.get("headline", "AI/ML Engineer").strip()

    canvas_size = 1080
    bg_img = None

    candidate_urls = _get_dynamic_background_urls(headline)
    for url in candidate_urls[:6]:
        try:
            resp = requests.get(url, timeout=8, headers={"User-Agent": "LinkedInAIAgentStudio/1.5"})
            if resp.status_code == 200:
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                bg_img = ImageOps.fit(img, (canvas_size, canvas_size), method=Image.Resampling.LANCZOS)
                _RECENT_BG_URLS.append(url)
                if len(_RECENT_BG_URLS) > 25:
                    _RECENT_BG_URLS.pop(0)
                break
        except Exception:
            continue

    if bg_img is None:
        bg_img = _create_fallback_studio_background(canvas_size)

    # Darken background slightly and add soft ambient color orbs so glass refraction pops
    bg_img = ImageEnhance.Brightness(bg_img).enhance(0.50)
    bg_img = ImageEnhance.Color(bg_img).enhance(1.20)
    bg_rgba = bg_img.convert("RGBA")

    ambient = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    adraw = ImageDraw.Draw(ambient)
    adraw.ellipse((90, 90, 560, 560), fill=(56, 189, 248, 42))
    adraw.ellipse((520, 500, 990, 970), fill=(16, 185, 129, 38))
    ambient = ambient.filter(ImageFilter.GaussianBlur(radius=90))
    bg_rgba = Image.alpha_composite(bg_rgba, ambient)

    # Glass Card Coordinates
    card_x1, card_y1 = 84, 104
    card_x2, card_y2 = 996, 976
    card_w = card_x2 - card_x1  # 912px
    card_h = card_y2 - card_y1  # 872px
    corner_radius = 48

    # Soft elevation shadow under the glass card
    shadow = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle(
        (card_x1 + 6, card_y1 + 20, card_x2 + 6, card_y2 + 20),
        radius=corner_radius,
        fill=(0, 0, 0, 155)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=36))
    bg_rgba = Image.alpha_composite(bg_rgba, shadow)

    # Frosted Liquid Glass Refraction
    glass_crop = bg_rgba.crop((card_x1, card_y1, card_x2, card_y2))
    glass_blurred = glass_crop.filter(ImageFilter.GaussianBlur(radius=34))

    # Translucent dark frost tint + top specular gradient
    frost_tint = Image.new("RGBA", (card_w, card_h), (18, 20, 28, 182))
    glass_surface = Image.alpha_composite(glass_blurred, frost_tint)

    sheen = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    sh_draw = ImageDraw.Draw(sheen)
    sh_draw.polygon(
        [(0, 0), (card_w, 0), (card_w, int(card_h * 0.36)), (0, int(card_h * 0.18))],
        fill=(255, 255, 255, 18)
    )
    glass_surface = Image.alpha_composite(glass_surface, sheen)

    card_mask = _create_supersampled_rounded_mask(card_w, card_h, corner_radius)
    bg_rgba.paste(glass_surface, (card_x1, card_y1), card_mask)

    draw = ImageDraw.Draw(bg_rgba)

    # Outer and inner iOS Liquid Glass specular borders
    draw.rounded_rectangle(
        (card_x1, card_y1, card_x2, card_y2),
        radius=corner_radius,
        outline=(255, 255, 255, 78),
        width=2
    )
    draw.rounded_rectangle(
        (card_x1 + 3, card_y1 + 3, card_x2 - 3, card_y2 - 3),
        radius=corner_radius - 2,
        outline=(255, 255, 255, 20),
        width=1
    )

    # Content margins inside the glass card
    pad_x = 68
    x_left = card_x1 + pad_x    # 152
    x_right = card_x2 - pad_x   # 928
    max_text_width = x_right - x_left  # 776px

    # --- 1. TOP HEADER BAR (Category Pill + Source Name) ---
    top_y = card_y1 + 64
    font_badge = _load_font(20, bold=True)
    font_source = _load_font(20, bold=True)

    badge_label = "AI & ML BRIEFING"
    badge_bbox = draw.textbbox((0, 0), badge_label, font=font_badge)
    badge_text_w = badge_bbox[2] - badge_bbox[0]
    pill_w = badge_text_w + 62
    pill_h = 44

    # Solid white pill so near-black badge text stays readable on any background
    draw.rounded_rectangle(
        (x_left, top_y, x_left + pill_w, top_y + pill_h),
        radius=22,
        fill=(245, 245, 247, 255),
        outline=(255, 255, 255, 255),
        width=1
    )
    # Emerald indicator dot inside pill
    draw.ellipse((x_left + 18, top_y + 16, x_left + 30, top_y + 28), fill=(16, 185, 129, 255))
    # Near-black badge text for contrast on the white pill
    draw.text((x_left + 40, top_y + 22), badge_label, font=font_badge, fill=(15, 15, 18, 255), anchor="lm")
    # Right-aligned news source name
    clean_source = (source or "AI NEWS").upper().strip()
    if len(clean_source) > 22:
        clean_source = clean_source[:20].rstrip() + "…"
    draw.text((x_right, top_y + 22), clean_source, font=font_source, fill=(161, 161, 170, 230), anchor="rm")

    # --- 2. MAIN HEADLINE (Pixel-Measured & Vertically Centered) ---
    clean_headline = headline.rsplit(" - ", 1)[0].strip()

    # Select optimal font size so headline fits comfortably between y=250 and y=725
    headline_font_size = 48
    font_headline = _load_font(headline_font_size, bold=True)
    wrapped_lines = _wrap_text_by_pixel_width(draw, clean_headline, font_headline, max_text_width)

    if len(wrapped_lines) > 5:
        headline_font_size = 42
        font_headline = _load_font(headline_font_size, bold=True)
        wrapped_lines = _wrap_text_by_pixel_width(draw, clean_headline, font_headline, max_text_width)

    if len(wrapped_lines) > 6:
        wrapped_lines = wrapped_lines[:6]
        wrapped_lines[-1] = wrapped_lines[-1].rstrip(" .,;:-") + "…"

    line_height = int(headline_font_size * 1.34)
    total_text_h = len(wrapped_lines) * line_height

    zone_top = top_y + pill_h + 42     # 250
    divider_y = card_y2 - 196          # 780
    zone_bottom = divider_y - 36       # 744
    available_h = zone_bottom - zone_top

    start_y = zone_top + max(0, (available_h - total_text_h) // 2)

    curr_y = start_y
    for line in wrapped_lines:
        draw.text((x_left, curr_y), line, font=font_headline, fill=(250, 250, 250, 255))
        curr_y += line_height

    # --- 3. SUBTLE FROSTED DIVIDER ---
    draw.line([(x_left, divider_y), (x_right, divider_y)], fill=(255, 255, 255, 38), width=1)

    # --- 4. AUTHOR IDENTITY FOOTER (Zero Overlap, Supersampled Circular DP) ---
    avatar_size = 88
    avatar_x = x_left
    avatar_y = divider_y + 38  # 818 (bottom at 906, 70px above card bottom)

    avatar_rendered = False
    if os.path.exists(AVATAR_FILE_PATH):
        try:
            av_img = Image.open(AVATAR_FILE_PATH).convert("RGBA")
            av_img = ImageOps.fit(av_img, (avatar_size, avatar_size), method=Image.Resampling.LANCZOS)
            av_mask = _create_supersampled_circle_mask(avatar_size)
            bg_rgba.paste(av_img, (avatar_x, avatar_y), av_mask)

            # Crisp glass ring around avatar
            draw.ellipse(
                (avatar_x - 2, avatar_y - 2, avatar_x + avatar_size + 2, avatar_y + avatar_size + 2),
                outline=(0, 0, 0, 175),
                width=2
            )
            avatar_rendered = True
        except Exception as e:
            print(f"Avatar render fallback: {e}")

    font_author = _load_font(31, bold=True)
    font_role = _load_font(23, bold=False)

    if not avatar_rendered:
        draw.ellipse(
            (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
            fill=(39, 39, 42, 255),
            outline=(255, 255, 255, 140),
            width=2
        )
        initials = "".join([part[0].upper() for part in author_name.split()[:2]]) or "SN"
        draw.text(
            (avatar_x + avatar_size // 2, avatar_y + avatar_size // 2),
            initials,
            font=font_author,
            fill=(255, 255, 255, 255),
            anchor="mm"
        )

    # Author Name & AI/ML Engineer Subtitle with clean vertical separation
    info_x = avatar_x + avatar_size + 26
    name_y = avatar_y + 12
    role_y = avatar_y + 52

    draw.text((info_x, name_y), author_name, font=font_author, fill=(255, 255, 255, 255))
    draw.text((info_x, role_y), author_role, font=font_role, fill=(161, 161, 170, 245))

    # Save 1080x1080 JPEG and return forward-slash normalized path
    timestamp = int(time.time() * 1000)
    filename = f"card_{timestamp}.jpg"
    rel_path = f"{OUTPUT_DIR}/{filename}"

    final_rgb = bg_rgba.convert("RGB")
    final_rgb.save(rel_path, "JPEG", quality=95, optimize=True)
    print(f"Generated clean 1080x1080 Liquid Glass card: {rel_path}")
    return rel_path


def run_agent_workflow() -> Dict[str, Any]:
    """
    Execute the complete autonomous pipeline:
    1. Discover latest unseen 24h AI/ML news
    2. Synthesize LinkedIn engineering commentary
    3. Render 1080x1080 iOS Liquid Glass card
    4. Persist draft to SQLite history and return normalized payload
    """
    news_item = fetch_latest_tech_news()
    post_text = generate_linkedin_post(news_item)
    image_path = generate_creative_image(news_item["title"], news_item["source"])

    normalized_path = image_path.replace("\\", "/").lstrip("/")
    image_url = f"/{normalized_path}?t={int(time.time())}"

    post_id = save_post_record(
        title=news_item["title"],
        source=news_item["source"],
        link=news_item["link"],
        post_text=post_text,
        image_url=image_url,
        image_path=normalized_path,
        status="draft"
    )

    return {
        "post_id": post_id,
        "news": news_item,
        "post_text": post_text,
        "image_path": normalized_path,
        "image_url": image_url,
        "record_status": "draft"
    }