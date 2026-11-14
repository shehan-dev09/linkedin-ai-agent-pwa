import os
import json
import asyncio
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

from app.agent import run_agent_workflow

# Sri Lanka Standard Time (UTC+05:30)
SLT_TZ = timezone(timedelta(hours=5, minutes=30))

SCHEDULER_CONFIG_PATH = Path("static/scheduler_config.json")
DRAFT_FILE_PATH = Path("static/generated_images/current_draft.json")

DEFAULT_SCHEDULER_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "schedule_times": ["08:30", "12:30", "17:30", "21:00"],
    "ntfy_topic": "",
    "last_triggered_slot": "",
    "last_run_at": None,
    "last_notification": None
}


def load_scheduler_config() -> Dict[str, Any]:
    """Load the 4x/day scheduler configuration from disk."""
    SCHEDULER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SCHEDULER_CONFIG_PATH.exists():
        try:
            with open(SCHEDULER_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_SCHEDULER_CONFIG, **data}
        except Exception:
            pass
    return DEFAULT_SCHEDULER_CONFIG.copy()


def save_scheduler_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Persist the scheduler configuration to disk."""
    SCHEDULER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged = {**DEFAULT_SCHEDULER_CONFIG, **config}
    with open(SCHEDULER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    return merged


def compute_next_slot(schedule_times: List[str], enabled: bool) -> str:
    """Calculate the next upcoming daily slot in Sri Lanka Standard Time."""
    if not enabled or not schedule_times:
        return "PAUSED"

    now_slt = datetime.now(SLT_TZ)
    current_hm = now_slt.strftime("%H:%M")
    sorted_slots = sorted(schedule_times)

    for slot in sorted_slots:
        if slot > current_hm:
            return f"{slot} SLT"

    return f"{sorted_slots[0]} SLT (Tomorrow)"


def get_scheduler_status() -> Dict[str, Any]:
    """Return full scheduler state including the next upcoming SLT execution slot."""
    cfg = load_scheduler_config()
    now_slt = datetime.now(SLT_TZ)
    return {
        **cfg,
        "current_time_slt": now_slt.strftime("%H:%M"),
        "next_slot_slt": compute_next_slot(cfg.get("schedule_times", []), cfg.get("enabled", True))
    }


def send_ntfy_push(
    topic: str,
    title: str,
    message: str,
    click_url: str = "http://127.0.0.1:8000"
) -> bool:
    """Send a free push notification via ntfy.sh to iOS/Android devices."""
    clean_topic = topic.strip()
    if not clean_topic:
        return False

    try:
        headers = {
            "Title": title[:100],
            "Priority": "high",
            "Tags": "sparkles,newspaper",
            "Click": click_url
        }
        resp = requests.post(
            f"https://ntfy.sh/{clean_topic}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=10
        )
        return resp.status_code in (200, 201)
    except Exception as e:
        print(f"Warning: ntfy push notification failed: {e}")
        return False


async def scheduler_background_loop() -> None:
    """
    24/7 background loop that checks the current Sri Lanka time every 20 seconds
    and autonomously generates a fresh LinkedIn post draft at the 4 daily peak times.
    Automatically repeats every day without requiring manual re-activation.
    """
    print("Autonomous 4x/Day LinkedIn Scheduler started (Timezone: UTC+05:30 SLT).")
    while True:
        try:
            cfg = load_scheduler_config()
            if cfg.get("enabled", True):
                now_slt = datetime.now(SLT_TZ)
                today_str = now_slt.strftime("%Y-%m-%d")
                current_hm = now_slt.strftime("%H:%M")
                slot_key = f"{today_str}_{current_hm}"

                schedule_times = cfg.get("schedule_times", ["08:30", "12:30", "17:30", "21:00"])

                if current_hm in schedule_times and cfg.get("last_triggered_slot") != slot_key:
                    print(f"[Auto-Pilot] Triggering scheduled peak slot: {slot_key} SLT")
                    cfg["last_triggered_slot"] = slot_key
                    save_scheduler_config(cfg)

                    # Run the AI Agent workflow in a worker thread
                    result = await asyncio.to_thread(run_agent_workflow)

                    DRAFT_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    with open(DRAFT_FILE_PATH, "w", encoding="utf-8") as f:
                        json.dump(result, f, indent=2)

                    news_info = result.get("news", {})
                    news_title = news_info.get("title", "New AI/ML Engineering Briefing")
                    news_source = news_info.get("source", "AI News")

                    cfg = load_scheduler_config()
                    cfg["last_run_at"] = now_slt.isoformat()
                    cfg["last_notification"] = {
                        "slot": current_hm,
                        "title": news_title,
                        "source": news_source,
                        "timestamp": now_slt.isoformat()
                    }
                    save_scheduler_config(cfg)

                    # Dispatch mobile lock-screen push if ntfy topic is configured
                    ntfy_topic = cfg.get("ntfy_topic", "").strip()
                    if ntfy_topic:
                        await asyncio.to_thread(
                            send_ntfy_push,
                            ntfy_topic,
                            f"LinkedIn Draft Ready ({current_hm} SLT)",
                            f"{news_title} ({news_source}) — Tap to review & publish in Studio."
                        )

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Auto-Pilot Scheduler Error]: {e}")

        await asyncio.sleep(20)