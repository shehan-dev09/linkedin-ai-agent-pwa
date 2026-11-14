import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
import requests

from app.agent import run_agent_workflow
from app.storage import save_post_record

# Sri Lanka Standard Time (UTC+05:30)
SLT_TIMEZONE = timezone(timedelta(hours=5, minutes=30))

SCHEDULER_FILE = Path("static/scheduler_config.json")
DRAFT_FILE = Path("static/generated_images/latest_draft.json")

DEFAULT_SCHEDULER_CONFIG = {
    "enabled": True,
    "peak_times": ["08:30", "12:30", "17:30", "21:00"],
    "ntfy_topic": "",  # Optional free mobile push topic (ntfy.sh)
    "last_triggered_slot": "",
    "last_run_at": "Never",
    "latest_notification": None
}


def get_slt_now() -> datetime:
    """Return the current datetime in Sri Lanka Standard Time (UTC+5:30)."""
    return datetime.now(SLT_TIMEZONE)


def load_scheduler_config() -> Dict[str, Any]:
    """Load scheduler configuration from disk or initialize defaults."""
    config = DEFAULT_SCHEDULER_CONFIG.copy()
    if SCHEDULER_FILE.exists():
        try:
            saved = json.loads(SCHEDULER_FILE.read_text(encoding="utf-8"))
            config.update(saved)
        except Exception:
            pass
    return config


def save_scheduler_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Persist scheduler settings to disk."""
    SCHEDULER_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULER_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


def get_next_scheduled_slot(peak_times: List[str]) -> str:
    """Calculate the next upcoming peak time slot in SLT."""
    if not peak_times:
        return "Not scheduled"

    now_slt = get_slt_now()
    current_hm = now_slt.strftime("%H:%M")
    sorted_times = sorted(peak_times)

    for slot in sorted_times:
        if slot > current_hm:
            return f"Today at {slot} SLT"

    return f"Tomorrow at {sorted_times[0]} SLT"


def send_optional_ntfy_push(title: str, source: str, ntfy_topic: str) -> None:
    """
    If user configured a free ntfy.sh topic name, send an instant mobile push
    notification to iOS/Android lock screen (100% free, no signup required).
    """
    topic = ntfy_topic.strip()
    if not topic:
        return
    try:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=f"New AI/ML Draft Ready: {title} ({source})".encode("utf-8"),
            headers={
                "Title": "LinkedIn AI Agent: Peak-Hour Draft Ready",
                "Priority": "high",
                "Tags": "robot,sparkles"
            },
            timeout=6
        )
    except Exception as e:
        print(f"⚠️ Optional ntfy push skipped: {e}")


def execute_scheduled_generation(trigger_reason: str = "Scheduled Peak Slot") -> Dict[str, Any]:
    """Run the AI Agent workflow synchronously and create a notification payload."""
    print(f"⏰ [{trigger_reason}] Auto-generating fresh LinkedIn post...")
    result = run_agent_workflow()

    now_slt = get_slt_now()
    normalized_path = result["image_path"].replace("\\", "/")
    image_url = f"/{normalized_path}?t={int(now_slt.timestamp())}"

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
        "created_at": now_slt.strftime("%Y-%m-%d %H:%M:%S")
    }

    DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
    DRAFT_FILE.write_text(json.dumps(draft_data, indent=2), encoding="utf-8")

    config = load_scheduler_config()
    notification_event = {
        "notif_id": int(now_slt.timestamp()),
        "post_id": post_id,
        "title": f"🔥 Peak-Hour Draft Ready ({trigger_reason})",
        "body": f"{result['news']['title']} • Tap to review & publish",
        "image_url": image_url,
        "created_at": now_slt.strftime("%Y-%m-%d %H:%M:%S SLT")
    }

    config["last_run_at"] = now_slt.strftime("%Y-%m-%d %H:%M:%S SLT")
    config["latest_notification"] = notification_event
    save_scheduler_config(config)

    send_optional_ntfy_push(
        title=result["news"]["title"],
        source=result["news"]["source"],
        ntfy_topic=config.get("ntfy_topic", "")
    )

    return draft_data


async def scheduler_background_loop() -> None:
    """
    Background asyncio loop that checks every 25 seconds if the current
    Sri Lanka Time (SLT) matches one of the 4 daily peak LinkedIn slots.
    """
    print("🚀 Autonomous Peak-Time Scheduler started (Sri Lanka Time UTC+5:30)")
    while True:
        try:
            config = load_scheduler_config()
            if config.get("enabled", True):
                now_slt = get_slt_now()
                current_hm = now_slt.strftime("%H:%M")
                today_slot_key = f"{now_slt.strftime('%Y-%m-%d')}_{current_hm}"

                peak_times = config.get("peak_times", ["08:30", "12:30", "17:30", "21:00"])

                if current_hm in peak_times and config.get("last_triggered_slot") != today_slot_key:
                    # Lock slot immediately so it never triggers twice in the same minute
                    config["last_triggered_slot"] = today_slot_key
                    save_scheduler_config(config)

                    # Run heavy AI generation in a background thread so FastAPI stays fast
                    await asyncio.to_thread(
                        execute_scheduled_generation,
                        f"Peak Slot {current_hm} SLT"
                    )
        except Exception as e:
            print(f"⚠️ Scheduler loop error: {e}")

        await asyncio.sleep(25)