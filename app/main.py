import os
import json
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.agent import run_agent_workflow, generate_linkedin_post, generate_creative_image
from app.storage import (
    init_db,
    update_draft_content,
    mark_post_published,
    delete_post_record,
    delete_all_drafts,
    get_post_history,
    get_latest_post_record,
    get_agent_stats
)
from app.scheduler import (
    load_scheduler_config,
    save_scheduler_config,
    get_scheduler_status,
    send_ntfy_push,
    scheduler_background_loop
)
from app.linkedin_service import (
    verify_linkedin_connection,
    save_configured_token,
    publish_to_linkedin
)

APP_VERSION = "1.5.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize SQLite storage and start the 24/7 background scheduler task."""
    init_db()
    scheduler_task = asyncio.create_task(scheduler_background_loop())
    yield
    scheduler_task.cancel()


app = FastAPI(
    title="LinkedIn Autonomous AI Agent",
    version=APP_VERSION,
    lifespan=lifespan
)

os.makedirs("static/generated_images", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

DRAFT_FILE_PATH = "static/generated_images/current_draft.json"
PROFILE_FILE_PATH = "static/profile.json"

DEFAULT_PROFILE = {
    "name": "Shehan Nadeesha",
    "headline": "AI/ML Engineer",
    "linkedin_url": "https://www.linkedin.com/in/shehan-nadeesha/",
    "avatar_url": "/static/avatar.jpg"
}


def get_profile_data() -> dict:
    if os.path.exists(PROFILE_FILE_PATH):
        try:
            with open(PROFILE_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_PROFILE, **data}
        except Exception:
            pass
    return DEFAULT_PROFILE.copy()


class PublishRequest(BaseModel):
    post_id: int | None = None
    final_text: str


class RegenerateRequest(BaseModel):
    post_id: int | None = None
    title: str | None = ""
    link: str | None = ""
    source: str | None = ""
    summary: str | None = ""


class SchedulerUpdateRequest(BaseModel):
    enabled: bool
    schedule_times: list[str]
    ntfy_topic: str = ""


class LinkedInTokenRequest(BaseModel):
    access_token: str


@app.get("/")
async def serve_pwa():
    return FileResponse("static/index.html")


@app.get("/api/meta")
async def get_app_meta():
    return {
        "status": "success",
        "version": APP_VERSION,
        "short_version": f"v{'.'.join(APP_VERSION.split('.')[:2])}"
    }


@app.get("/api/linkedin/status")
async def get_linkedin_status():
    status = await asyncio.to_thread(verify_linkedin_connection)
    return {"status": "success", "linkedin": status}


@app.post("/api/linkedin/token")
async def update_linkedin_token(request: LinkedInTokenRequest):
    token = request.access_token.strip()
    save_configured_token(token)
    status = await asyncio.to_thread(verify_linkedin_connection, token)
    return {"status": "success", "linkedin": status}


@app.get("/api/profile")
async def get_profile():
    profile = get_profile_data()
    has_custom_avatar = os.path.exists("static/avatar.jpg")
    return {
        "status": "success",
        "profile": profile,
        "has_custom_avatar": has_custom_avatar
    }


@app.post("/api/profile")
async def update_profile(
    name: str = Form("Shehan Nadeesha"),
    headline: str = Form("AI/ML Engineer"),
    linkedin_url: str = Form("https://www.linkedin.com/in/shehan-nadeesha/"),
    avatar: UploadFile | None = File(None)
):
    profile = get_profile_data()
    profile["name"] = name.strip() or "Shehan Nadeesha"
    profile["headline"] = headline.strip() or "AI/ML Engineer"
    profile["linkedin_url"] = linkedin_url.strip() or "https://www.linkedin.com/in/shehan-nadeesha/"

    if avatar and avatar.filename:
        content = await avatar.read()
        if content:
            with open("static/avatar.jpg", "wb") as f:
                f.write(content)
            profile["avatar_url"] = f"/static/avatar.jpg?t={int(datetime.now().timestamp())}"

    with open(PROFILE_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)

    return {"status": "success", "profile": profile}


@app.get("/api/scheduler")
async def get_scheduler():
    return {
        "status": "success",
        "scheduler": get_scheduler_status()
    }


@app.post("/api/scheduler")
async def update_scheduler(request: SchedulerUpdateRequest):
    clean_times = []
    for t in request.schedule_times:
        t_str = t.strip()
        if len(t_str) == 5 and ":" in t_str:
            clean_times.append(t_str)

    if not clean_times:
        clean_times = ["08:30", "12:30", "17:30", "21:00"]

    cfg = load_scheduler_config()
    cfg["enabled"] = request.enabled
    cfg["schedule_times"] = sorted(list(set(clean_times)))[:4]
    cfg["ntfy_topic"] = request.ntfy_topic.strip()
    save_scheduler_config(cfg)

    return {
        "status": "success",
        "scheduler": get_scheduler_status()
    }


@app.post("/api/scheduler/test-notification")
async def test_scheduler_notification():
    cfg = load_scheduler_config()
    topic = cfg.get("ntfy_topic", "").strip()
    if topic:
        await asyncio.to_thread(
            send_ntfy_push,
            topic,
            "LinkedIn AI Studio: Test Alert",
            "Your 4x/day Peak-Time LinkedIn AI Agent notifications are active!",
            "http://127.0.0.1:8000"
        )
    return {
        "status": "success",
        "message": "Test notification dispatched.",
        "ntfy_sent": bool(topic)
    }


@app.get("/api/draft")
async def get_current_draft():
    latest = get_latest_post_record()
    if latest:
        return {
            "status": "success",
            "data": {
                "post_id": latest["id"],
                "news": {
                    "title": latest["title"],
                    "source": latest["source"],
                    "link": latest["link"],
                    "summary": ""
                },
                "post_text": latest["post_text"],
                "image_url": latest["image_url"],
                "image_path": latest["image_path"],
                "record_status": latest["status"]
            },
            "stats": get_agent_stats()
        }

    if os.path.exists(DRAFT_FILE_PATH):
        with open(DRAFT_FILE_PATH, "r", encoding="utf-8") as f:
            return {"status": "success", "data": json.load(f), "stats": get_agent_stats()}

    return {"status": "empty", "data": None, "stats": get_agent_stats()}


@app.get("/api/history")
async def fetch_history(status: str = Query("all", description="Filter by all, published, or draft")):
    return {
        "status": "success",
        "history": get_post_history(status_filter=status, limit=100),
        "stats": get_agent_stats()
    }


@app.delete("/api/history/drafts/clear")
async def clear_all_unpublished_drafts():
    removed_count = delete_all_drafts()
    if os.path.exists(DRAFT_FILE_PATH):
        try:
            os.remove(DRAFT_FILE_PATH)
        except Exception:
            pass
    return {
        "status": "success",
        "removed_count": removed_count,
        "latest": get_latest_post_record(),
        "stats": get_agent_stats()
    }


@app.delete("/api/history/{post_id}")
async def remove_draft_post(post_id: int):
    deleted = delete_post_record(post_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Post record not found in database.")
    return {
        "status": "success",
        "deleted_id": post_id,
        "latest": get_latest_post_record(),
        "stats": get_agent_stats()
    }


@app.post("/api/generate")
async def trigger_agent():
    try:
        result = await asyncio.to_thread(run_agent_workflow)
        with open(DRAFT_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return {"status": "success", "data": result, "stats": get_agent_stats()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/regenerate")
async def regenerate_current_draft(request: RegenerateRequest):
    """
    Re-synthesizes both the LinkedIn post and the 1080x1080 iOS Liquid Glass card
    for the currently selected draft, updating SQLite history in-place.
    """
    try:
        target_id = request.post_id
        title = (request.title or "").strip()
        link = (request.link or "").strip()
        source = (request.source or "").strip()
        summary = (request.summary or "").strip()

        # Fallback lookup from SQLite if any field or post_id is missing
        existing_record = None
        if target_id:
            for item in get_post_history(status_filter="all", limit=100):
                if item["id"] == target_id:
                    existing_record = item
                    break
        if not existing_record:
            existing_record = get_latest_post_record()
            if existing_record and not target_id:
                target_id = existing_record["id"]

        if existing_record:
            title = title or existing_record.get("title", "")
            link = link or existing_record.get("link", "")
            source = source or existing_record.get("source", "AI News")

        if not title:
            raise HTTPException(status_code=400, detail="No draft headline available to regenerate.")

        news_item = {
            "title": title,
            "link": link,
            "source": source or "AI News",
            "summary": summary
        }

        post_text = await asyncio.to_thread(generate_linkedin_post, news_item)
        image_path = await asyncio.to_thread(generate_creative_image, news_item["title"], news_item["source"])
        normalized_path = image_path.replace("\\", "/").lstrip("/")
        timestamp = int(datetime.now().timestamp())
        image_url = f"/{normalized_path}?t={timestamp}"

        # Clean up previous image file if regenerating an existing SQLite record
        if existing_record and existing_record.get("image_path"):
            old_path = existing_record["image_path"]
            if old_path != normalized_path and os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass

        if target_id:
            update_draft_content(target_id, post_text, image_url, normalized_path)

        result = {
            "post_id": target_id,
            "news": news_item,
            "post_text": post_text,
            "image_path": normalized_path,
            "image_url": image_url,
            "record_status": existing_record.get("status", "draft") if existing_record else "draft"
        }
        with open(DRAFT_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        return {"status": "success", "data": result, "stats": get_agent_stats()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/publish")
async def approve_and_publish(request: PublishRequest):
    try:
        target_id = request.post_id
        image_path = None

        latest = get_latest_post_record()
        if not target_id and latest:
            target_id = latest["id"]

        history_items = get_post_history(status_filter="all", limit=100)
        for item in history_items:
            if item["id"] == target_id:
                image_path = item.get("image_path")
                break

        if not image_path and latest:
            image_path = latest.get("image_path")

        publish_result = await asyncio.to_thread(
            publish_to_linkedin,
            request.final_text,
            image_path
        )

        post_urn = publish_result.get("post_urn", f"urn:li:share:{int(datetime.now().timestamp())}")

        if target_id:
            mark_post_published(target_id, request.final_text, linkedin_urn=post_urn)

        if os.path.exists(DRAFT_FILE_PATH):
            with open(DRAFT_FILE_PATH, "r", encoding="utf-8") as f:
                draft_data = json.load(f)
            draft_data["post_text"] = request.final_text
            draft_data["record_status"] = "published"
            with open(DRAFT_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(draft_data, f, indent=2)

        return {
            "status": "published",
            "mode": publish_result.get("mode", "simulated"),
            "post_urn": post_urn,
            "post_url": publish_result.get("post_url"),
            "message": publish_result.get("message", "Post published."),
            "published_at": datetime.now().isoformat(),
            "stats": get_agent_stats()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))