import json
from io import BytesIO
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from PIL import Image, ImageOps

from app.agent import run_agent_workflow
from app.storage import (
    init_db,
    save_post_record,
    update_post_status,
    delete_post_record,
    delete_all_drafts,
    get_post_history,
    get_latest_post_record,
    get_agent_stats
)

app = FastAPI(
    title="LinkedIn Autonomous AI Agent",
    description="Human-in-the-Loop PWA for automated LinkedIn content creation",
    version="1.3.0"
)

# Mount static directory for images and assets
app.mount("/static", StaticFiles(directory="static"), name="static")

DRAFT_FILE = Path("static/generated_images/latest_draft.json")
PROFILE_FILE = Path("static/profile.json")
AVATAR_FILE = Path("static/avatar.jpg")

DEFAULT_PROFILE = {
    "name": "Shehan Nadeesha",
    "headline": "AI/ML Engineer",
    "linkedin_url": "https://www.linkedin.com/in/shehan-nadeesha/",
    "avatar_url": ""
}

# Initialize SQLite tables on server startup
init_db()


class PublishRequest(BaseModel):
    post_text: str
    image_path: str
    post_id: int | None = None


def get_profile_data() -> dict:
    """Load saved LinkedIn profile metadata or return defaults."""
    profile = DEFAULT_PROFILE.copy()
    if PROFILE_FILE.exists():
        try:
            saved = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
            profile.update(saved)
        except Exception:
            pass
    if AVATAR_FILE.exists():
        profile["avatar_url"] = f"/static/avatar.jpg?t={int(AVATAR_FILE.stat().st_mtime)}"
    return profile


def sync_latest_draft_file() -> dict | None:
    """Keep latest_draft.json synchronized with the latest record in SQLite."""
    latest = get_latest_post_record()
    if latest:
        DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
        DRAFT_FILE.write_text(json.dumps(latest, indent=2), encoding="utf-8")
        return latest
    else:
        if DRAFT_FILE.exists():
            DRAFT_FILE.unlink()
        return None


@app.get("/")
async def serve_pwa():
    """Serve the main Progressive Web App interface."""
    return FileResponse("static/index.html")


@app.get("/api/profile")
async def get_profile():
    """Return user's LinkedIn profile settings."""
    return {"status": "success", "profile": get_profile_data()}


@app.post("/api/profile")
async def update_profile(
    name: str = Form("Shehan Nadeesha"),
    headline: str = Form("AI/ML Engineer"),
    linkedin_url: str = Form("https://www.linkedin.com/in/shehan-nadeesha/"),
    avatar: UploadFile | None = File(None)
):
    """Save user's LinkedIn profile metadata and optional profile photo."""
    try:
        if avatar and avatar.filename:
            raw_bytes = await avatar.read()
            img = Image.open(BytesIO(raw_bytes)).convert("RGB")
            img = ImageOps.fit(img, (400, 400), Image.Resampling.LANCZOS)
            AVATAR_FILE.parent.mkdir(parents=True, exist_ok=True)
            img.save(AVATAR_FILE, "JPEG", quality=92)

        profile_data = {
            "name": name.strip() or "Shehan Nadeesha",
            "headline": headline.strip() or "AI/ML Engineer",
            "linkedin_url": linkedin_url.strip() or "https://www.linkedin.com/in/shehan-nadeesha/"
        }
        PROFILE_FILE.write_text(json.dumps(profile_data, indent=2), encoding="utf-8")
        return {"status": "success", "profile": get_profile_data()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/draft")
async def get_latest_draft():
    """Retrieve the currently active draft along with live agent stats."""
    stats = get_agent_stats()
    latest = get_latest_post_record()
    if latest:
        return {"status": "ready", "draft": latest, "stats": stats}
    return {"status": "empty", "draft": None, "stats": stats}


@app.get("/api/history")
async def get_history(status: str | None = Query(None)):
    """Return past generated/published posts with optional status filter ('published' or 'draft')."""
    return {
        "status": "success",
        "stats": get_agent_stats(),
        "history": get_post_history(status_filter=status, limit=100)
    }


@app.delete("/api/history/drafts/clear")
async def clear_unwanted_drafts():
    """Delete all unpublished drafts at once while keeping their topics marked as seen."""
    deleted_count = delete_all_drafts()
    next_draft = sync_latest_draft_file()
    return {
        "status": "success",
        "deleted_count": deleted_count,
        "next_draft": next_draft,
        "stats": get_agent_stats()
    }


@app.delete("/api/history/{post_id}")
async def delete_single_post(post_id: int):
    """Delete a specific draft or post by ID."""
    removed = delete_post_record(post_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Post not found")
    next_draft = sync_latest_draft_file()
    return {
        "status": "success",
        "deleted_id": post_id,
        "next_draft": next_draft,
        "stats": get_agent_stats()
    }


@app.post("/api/generate")
@app.post("/api/regenerate")
async def generate_new_draft():
    """Trigger the AI Agent to fetch a fresh unseen news item and log it to SQLite."""
    try:
        result = run_agent_workflow()
        normalized_path = result["image_path"].replace("\\", "/")
        image_url = f"/{normalized_path}?t={int(datetime.now().timestamp())}"

        post_id = save_post_record(
            title=result["news"]["title"],
            source=result["news"]["source"],
            link=result["news"]["link"],
            post_text=result["post_text"],
            image_url=image_url,
            image_path=result["image_path"],
            status="draft"
        )

        draft_data = {
            "id": post_id,
            "title": result["news"]["title"],
            "source": result["news"]["source"],
            "link": result["news"]["link"],
            "published": result["news"].get("published", "Recent"),
            "post_text": result["post_text"],
            "image_prompt": result["image_prompt"],
            "image_url": image_url,
            "image_path": result["image_path"],
            "status": "draft",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
        DRAFT_FILE.write_text(json.dumps(draft_data, indent=2), encoding="utf-8")

        return {
            "status": "success",
            "draft": draft_data,
            "stats": get_agent_stats()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/publish")
async def publish_to_linkedin(request: PublishRequest):
    """Approve the post, update its status to 'published' in SQLite, and publish."""
    if not request.post_text.strip():
        raise HTTPException(status_code=400, detail="Post text cannot be empty")

    if request.post_id:
        update_post_status(
            post_id=request.post_id,
            post_text=request.post_text,
            status="published"
        )

    sync_latest_draft_file()

    return {
        "status": "published",
        "message": "Post approved and marked as Published in History!",
        "stats": get_agent_stats(),
        "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }