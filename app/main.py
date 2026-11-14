"""FastAPI Backend for Human-in-the-Loop (HITL) LinkedIn AI Agent."""

import base64
import io
import json
import os
import time
from typing import Any, Dict, Optional
from app import agent
from app.linkedin_service import publish_to_linkedin
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

app = FastAPI(
    title="Shehan Nadeesha | LinkedIn AI Agent",
    description="Human-in-the-loop AI/ML content agent with live LinkedIn profile integration.",
    version="1.1.0",
)

os.makedirs("static/generated_images", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

DRAFT_FILE = "static/generated_images/current_draft.json"
PROFILE_FILE = "static/profile.json"
AVATAR_FILE = "static/avatar.jpg"

DEFAULT_PROFILE = {
    "name": "Shehan Nadeesha",
    "headline": "AI/ML Engineer | Machine Learning, LLMs & Autonomous AI Agents",
    "profile_url": "https://www.linkedin.com/in/shehan-nadeesha/",
    "avatar_url": None,
}


class PublishRequest(BaseModel):
    post_text: str


class ProfileUpdateRequest(BaseModel):
    name: str
    headline: str
    profile_url: str
    avatar_base64: Optional[str] = None


def _load_profile() -> Dict[str, Any]:
    """Loads saved LinkedIn profile metadata and checks for local avatar."""
    profile = DEFAULT_PROFILE.copy()
    if os.path.exists(PROFILE_FILE):
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                profile.update(json.load(f))
        except Exception:
            pass

    if os.path.exists(AVATAR_FILE):
        profile["avatar_url"] = f"/{AVATAR_FILE}?t={int(os.path.getmtime(AVATAR_FILE))}"
    return profile


def _build_draft() -> Dict[str, Any]:
    """Executes the AI Agent pipeline to generate a new post and visual card."""
    news = agent.fetch_latest_tech_news()
    if not news:
        raise HTTPException(
            status_code=502, detail="Could not fetch AI/ML news."
        )

    post_text = agent.generate_linkedin_post(news["title"], news["source"])
    image_path = agent.generate_creative_image(news["title"], news["source"])

    if not image_path:
        raise HTTPException(
            status_code=502, detail="Could not generate visual card."
        )

    ts = int(time.time())
    draft_data = {
        "has_draft": True,
        "title": news["title"],
        "source": news["source"],
        "link": news["link"],
        "post_text": post_text,
        "image_path": image_path,
        "image_url": f"/{image_path}?t={ts}",
        "status": "pending",
        "created_at": ts,
    }

    with open(DRAFT_FILE, "w", encoding="utf-8") as f:
        json.dump(draft_data, f, indent=2)

    return draft_data


@app.get("/")
def serve_dashboard():
    return FileResponse("static/index.html")


@app.get("/api/profile")
def get_profile():
    """Returns Shehan Nadeesha's LinkedIn profile metadata for the live feed preview."""
    return _load_profile()


@app.post("/api/profile")
def update_profile(payload: ProfileUpdateRequest):
    """Updates LinkedIn profile metadata and saves the uploaded profile photo."""
    if payload.avatar_base64 and "," in payload.avatar_base64:
        try:
            header, encoded = payload.avatar_base64.split(",", 1)
            img_bytes = base64.b64decode(encoded)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            w, h = img.size
            min_dim = min(w, h)
            img = img.crop(
                (
                    (w - min_dim) // 2,
                    (h - min_dim) // 2,
                    (w + min_dim) // 2,
                    (h + min_dim) // 2,
                )
            )
            img = img.resize((400, 400), Image.Resampling.LANCZOS)
            img.save(AVATAR_FILE, "JPEG", quality=95)
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid image file: {e}"
            )

    profile_data = {
        "name": payload.name.strip() or DEFAULT_PROFILE["name"],
        "headline": payload.headline.strip() or DEFAULT_PROFILE["headline"],
        "profile_url": payload.profile_url.strip()
        or DEFAULT_PROFILE["profile_url"],
    }
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profile_data, f, indent=2)

    return _load_profile()


@app.get("/api/draft")
def get_draft():
    if os.path.exists(DRAFT_FILE):
        with open(DRAFT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"has_draft": False}


@app.post("/api/generate")
@app.post("/api/regenerate")
def generate_new_draft():
    return _build_draft()


@app.post("/api/publish")
def approve_and_publish(request: PublishRequest):
    image_path = "static/generated_images/latest_post.jpg"
    if not os.path.exists(image_path):
        raise HTTPException(
            status_code=400, detail="No generated image found to publish."
        )

    result = publish_to_linkedin(request.post_text, image_path)
    return result