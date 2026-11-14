import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
import requests

from app.agent import run_agent_workflow
from app.storage import get_latest_post_record

CONFIG_PATH = "static/scheduler_config.json"

# Sri Lanka Standard Time (UTC+05:30)
SLT_TIMEZONE = timezone(timedelta(hours=5, minutes=30))

DEFAULT_SCHEDULER_CONFIG = {
    "enabled": True,
    "times": ["08:30", "12:30", "17:30", "21:00"],
    "ntfy_topic": os.getenv("NTFY_TOPIC", "").strip(),
    "last_triggered_slot": "",
    "last_run_at": None,
}


def _clean_ntfy_topic(raw_topic: str) -> str:
    """Strip full URLs or slashes if the user pasted https://ntfy.sh/topic-name."""
    if not raw_topic:
        return os.getenv("NTFY_TOPIC", "").strip()
    t = raw_topic.strip()
    if "ntfy.sh/" in t:
        t = t.split("ntfy.sh/")[-1]
    return t.strip("/ ")


def load_scheduler_config() -> dict:
    os.makedirs("static", exist_ok=True)
    config = dict(DEFAULT_SCHEDULER_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                config.update(data)
        except Exception as e:
            print(f"Scheduler config read warning: {e}")

    # Always normalize topic and fallback to NTFY_TOPIC env var if empty
    config["ntfy_topic"] = _clean_ntfy_topic(config.get("ntfy_topic", ""))
    return config


def save_scheduler_config(new_config: dict) -> dict:
    os.makedirs("static", exist_ok=True)
    current = load_scheduler_config()
    current.update(new_config)

    # Clean and sort time slots
    raw_times = current.get("times", DEFAULT_SCHEDULER_CONFIG["times"])
    valid_times = []
    for t in raw_times:
        if isinstance(t, str) and len(t.strip()) == 5 and ":" in t:
            valid_times.append(t.strip())
    if not valid_times:
        valid_times = list(DEFAULT_SCHEDULER_CONFIG["times"])
    current["times"] = sorted(list(set(valid_times)))[:4]
    current["ntfy_topic"] = _clean_ntfy_topic(current.get("ntfy_topic", ""))

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
    return current


def compute_next_slot(times_list: list) -> dict:
    now_slt = datetime.now(SLT_TIMEZONE)
    today_str = now_slt.strftime("%Y-%m-%d")

    candidates = []
    for slot in sorted(times_list):
        try:
            hh, mm = map(int, slot.split(":"))
            slot_dt = now_slt.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if slot_dt <= now_slt:
                slot_dt += timedelta(days=1)
            candidates.append((slot_dt, slot))
        except Exception:
            continue

    if not candidates:
        return {"next_slot": "08:30", "countdown": "Scheduled", "current_slt": now_slt.strftime("%H:%M SLT")}

    candidates.sort(key=lambda x: x[0])
    next_dt, next_slot_str = candidates[0]
    diff = next_dt - now_slt
    total_minutes = int(diff.total_seconds() // 60)
    hours, mins = divmod(total_minutes, 60)

    is_today = next_dt.strftime("%Y-%m-%d") == today_str
    day_label = "Today" if is_today else "Tomorrow"

    return {
        "next_slot": f"{next_slot_str} SLT ({day_label})",
        "countdown": f"in {hours}h {mins}m" if hours > 0 else f"in {mins}m",
        "current_slt": now_slt.strftime("%H:%M SLT"),
    }


def get_scheduler_status() -> dict:
    cfg = load_scheduler_config()
    next_info = compute_next_slot(cfg.get("times", []))
    return {
        **cfg,
        **next_info,
        "timezone": "Asia/Colombo (UTC+05:30)",
        "daily_quota": len(cfg.get("times", [])),
    }


def send_ntfy_push(topic: str, title: str, message: str, click_url: str = "") -> bool:
    """
    Sends an instant mobile lock-screen push notification via ntfy.sh's UTF-8 JSON API.
    Works 100% reliably on iOS and Android without HTTP Latin-1 header encoding errors.
    """
    clean_topic = _clean_ntfy_topic(topic)
    if not clean_topic:
        print("ntfy push skipped: No topic configured.")
        return False

    payload = {
        "topic": clean_topic,
        "title": title,
        "message": message,
        "priority": 4,
        "tags": ["sparkles", "newspaper"],
    }
    if click_url:
        payload["click"] = click_url

    try:
        resp = requests.post(
            "https://ntfy.sh",
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=10,
        )
        print(f"ntfy push to '{clean_topic}' status: {resp.status_code}")
        return resp.status_code in (200, 201, 202)
    except Exception as e:
        print(f"ntfy push error: {e}")
        return False


async def scheduler_background_loop():
    """
    Autonomous 24/7 loop that checks Sri Lanka Standard Time every 25 seconds
    and generates 4 fresh AI/ML LinkedIn drafts per day at peak hours.
    """
    print("Autonomous 4x/Day LinkedIn Scheduler started (Timezone: UTC+05:30 SLT).")
    while True:
        try:
            cfg = load_scheduler_config()
            if cfg.get("enabled", True):
                now_slt = datetime.now(SLT_TIMEZONE)
                current_hhmm = now_slt.strftime("%H:%M")
                slot_key = f"{now_slt.strftime('%Y-%m-%d')}_{current_hhmm}"

                if current_hhmm in cfg.get("times", []) and cfg.get("last_triggered_slot") != slot_key:
                    print(f"[Auto-Pilot] Triggering scheduled slot: {slot_key}")
                    cfg["last_triggered_slot"] = slot_key
                    cfg["last_run_at"] = now_slt.strftime("%Y-%m-%d %H:%M:%S SLT")
                    save_scheduler_config(cfg)

                    # Run blocking AI/ML news + image generation in a worker thread
                    await asyncio.to_thread(run_agent_workflow)

                    latest = get_latest_post_record()
                    headline = latest.get("title", "New AI/ML News Draft Ready") if latest else "New AI/ML Draft Ready"

                    ntfy_topic = cfg.get("ntfy_topic", "").strip()
                    if ntfy_topic:
                        await asyncio.to_thread(
                            send_ntfy_push,
                            ntfy_topic,
                            "New LinkedIn AI/ML Draft Ready!",
                            f"Topic: {headline}\nTap to review & publish from your Studio.",
                        )
        except Exception as e:
            print(f"Scheduler loop error: {e}")

        await asyncio.sleep(25)