"""
PostPilot - Content Scraper & Ingestion Engine
Automatically discovers viral content from Reddit, TikTok, and YouTube,
processes it through editor.py, and queues it for posting.

Designed to run as a daily scheduled task via APScheduler.
Applies a 1:3 publish-to-interact ratio to maintain a trusted human footprint.
"""

import os
import re
import json
import random
import hashlib
import shutil
import subprocess
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from models import (
    SessionLocal, TargetSource, ContentQueue, ScrapeLog,
    SystemSettings, SystemLog, Account, VideoCache, TaskQueue,
)
from editor import clean_and_alter_video

# ─── Paths ───────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "staged" / "raw_downloads"
PROCESSED_DIR = BASE_DIR / "staged"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# ─── Helpers ─────────────────────────────────────────────────────────────────

HASHTAG_POOL = [
    "#viral", "#trending", "#fyp", "#explore", "#reels",
    "#amazing", "#interesting", "#mindblowing", "#satisfying",
    "#rare", "#unique", "#wow", "#incredible", "#mustwatch",
    "#shorts", "#dailymotion", "#contentcreator",
]


def _random_hashtags(count: int = 2) -> str:
    return " ".join(random.sample(HASHTAG_POOL, min(count, len(HASHTAG_POOL))))


def _clean_title(title: str) -> str:
    if not title:
        return ""
    title = re.sub(r"@\w+", "", title)
    title = re.sub(r"#\w+", "", title)
    title = re.sub(r"https?://\S+", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _random_schedule() -> datetime:
    """Random time between 2 PM and 7 PM today (or tomorrow if past)."""
    now = datetime.now(timezone.utc)
    hour = random.randint(14, 19)
    minute = random.randint(0, 59)
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if scheduled <= now:
        scheduled += timedelta(days=1)
    return scheduled


def _random_interact_schedule(base=None):
    """
    Return a random time within the next 1-12 hours from *base*.
    Used to spread interact tasks across the day.
    """
    base = base or datetime.now(timezone.utc)
    offset_hours = random.randint(1, 12)
    offset_minutes = random.randint(0, 59)
    return base + timedelta(hours=offset_hours, minutes=offset_minutes)


def _generate_interact_tasks(profile_id: int, platform: str, count: int) -> list[dict]:
    """
    Generate *count* interact task dicts for the same Chrome profile & platform.
    Each gets a randomly staggered schedule across the next 1-12 hours.
    Returns a list of dicts ready for db insertion.
    """
    tasks = []
    now = datetime.now(timezone.utc)
    for _ in range(count):
        tasks.append({
            "profile_id": profile_id,
            "platform": platform,
            "task_type": "interact",
            "caption": None,
            "file_path": None,
            "video_url": None,
            "is_completed": False,
            "created_at": _random_interact_schedule(now),
        })
    return tasks


def _download_video(url: str, output_dir: str = None) -> str:
    """Download a video via yt-dlp. Returns path or empty string."""
    output_dir = output_dir or str(RAW_DIR)
    os.makedirs(output_dir, exist_ok=True)
    output_template = os.path.join(output_dir, f"dl_{uuid.uuid4().hex[:8]}.%(ext)s")

    try:
        cmd = [
            "yt-dlp",
            "-f", "best[height<=1080]",
            "-o", output_template,
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[Scraper] Download failed: {result.stderr[:200]}")
            return ""

        for f in os.listdir(output_dir):
            if f.startswith(os.path.basename(output_template).split(".")[0]):
                return os.path.join(output_dir, f)
        return ""
    except Exception as exc:
        print(f"[Scraper] Download error: {exc}")
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  REDDIT SCRAPER
# ═══════════════════════════════════════════════════════════════════════════════

async def scrape_reddit(subreddit: str, min_upvotes: int = 1000, limit: int = 15) -> list:
    print(f"[Scraper] Reddit: checking r/{subreddit}...")
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=day&limit={limit}"
    headers = {"User-Agent": "PostPilot/1.0 (content scraper)"}
    videos = []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                print(f"[Scraper] Reddit returned {response.status_code}")
                return []

            data = response.json()
            for post in data.get("data", {}).get("children", []):
                post_data = post.get("data", {})
                title = post_data.get("title", "")
                upvotes = post_data.get("ups", 0)
                permalink = post_data.get("permalink", "")
                post_url = f"https://www.reddit.com{permalink}"
                media_url = _reddit_media_url(post_data)
                if not media_url or upvotes < min_upvotes:
                    continue
                videos.append({
                    "title": title, "url": media_url,
                    "upvotes": upvotes, "source_url": post_url,
                    "source_name": f"r/{subreddit}", "platform": "reddit",
                })
                print(f"[Scraper]   Found: {upvotes} upvotes — {title[:60]}")
    except Exception as exc:
        print(f"[Scraper] Reddit error: {exc}")
    return videos


def _reddit_media_url(post: dict) -> str:
    if post.get("is_video") and post.get("domain") == "v.redd.it":
        media = post.get("media") or {}
        rv = media.get("reddit_video") or {}
        fallback = rv.get("fallback_url", "")
        return post.get("url", fallback)
    crosspost = post.get("crosspost_parent_list") or []
    if crosspost:
        return _reddit_media_url(crosspost[0])
    domain = post.get("domain", "")
    url = post.get("url", "")
    supported = ("youtube.com", "youtu.be", "tiktok.com", "vimeo.com",
                 "streamable.com", "gfycat.com", "reddit.com")
    if any(d in domain for d in supported):
        return url
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  TIKTOK SCRAPER
# ═══════════════════════════════════════════════════════════════════════════════

async def scrape_tiktok(handle: str, min_views: int = 50000, limit: int = 10) -> list:
    print(f"[Scraper] TikTok: checking @{handle}...")
    profile_url = f"https://www.tiktok.com/@{handle}"
    videos = []

    try:
        cmd = ["yt-dlp", "--flat-playlist", "--dump-json", "--no-download", "--quiet", profile_url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"[Scraper] TikTok yt-dlp failed: {result.stderr[:200]}")
            return []

        for line in result.stdout.strip().split("\n")[:limit]:
            if not line.strip():
                continue
            try:
                info = json.loads(line)
                title = info.get("title", "") or info.get("description", "")
                url = info.get("url") or info.get("webpage_url", "")
                views = info.get("view_count", 0) or 0
                if views < min_views:
                    continue
                videos.append({
                    "title": title, "url": url, "views": views,
                    "source_url": url, "source_name": f"@{handle}", "platform": "tiktok",
                })
                print(f"[Scraper]   Found: {views} views — {title[:60]}")
            except json.JSONDecodeError:
                continue
    except Exception as exc:
        print(f"[Scraper] TikTok error: {exc}")
    return videos


# ═══════════════════════════════════════════════════════════════════════════════
#  YOUTUBE SHORTS SCRAPER
# ═══════════════════════════════════════════════════════════════════════════════

async def scrape_youtube(channel_url: str, min_views: int = 10000, limit: int = 10) -> list:
    print(f"[Scraper] YouTube: checking {channel_url}...")
    videos = []

    try:
        cmd = ["yt-dlp", "--flat-playlist", "--dump-json", "--no-download", "--quiet", channel_url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"[Scraper] YouTube yt-dlp failed: {result.stderr[:200]}")
            return []

        for line in result.stdout.strip().split("\n")[:limit]:
            if not line.strip():
                continue
            try:
                info = json.loads(line)
                title = info.get("title", "")
                url = info.get("url") or info.get("webpage_url", "")
                views = info.get("view_count", 0) or 0
                duration = info.get("duration", 999)
                is_short = "/shorts/" in url or (duration and duration <= 60)
                if not is_short or views < min_views:
                    continue
                videos.append({
                    "title": title, "url": url, "views": views,
                    "source_url": url, "source_name": channel_url.split("/")[-1],
                    "platform": "youtube",
                })
                print(f"[Scraper]   Found: {views} views — {title[:60]}")
            except json.JSONDecodeError:
                continue
    except Exception as exc:
        print(f"[Scraper] YouTube error: {exc}")
    return videos


# ═══════════════════════════════════════════════════════════════════════════════
#  CAPTION GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

def generate_caption(title: str, platform: str = "") -> str:
    cleaned = _clean_title(title)
    if not cleaned:
        fallbacks = {
            "reddit": "Check this out!",
            "tiktok": "Found this on TikTok!",
            "youtube": "YouTube Shorts find!",
        }
        cleaned = fallbacks.get(platform, "Amazing content!")
    hashtags = _random_hashtags(2)
    caption = f"{cleaned}\n\n{hashtags}"
    if len(caption) > 400:
        caption = caption[:397] + "..."
    return caption


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN SCRAPE LOOP
# ═══════════════════════════════════════════════════════════════════════════════

async def run_scrape_cycle() -> dict:
    """
    Full scrape cycle:
    1. Read active target sources from database
    2. Scrape each source for viral content
    3. Download, process, and queue the best finds
    4. Log everything
    5. For every publish task, auto-generate 2-3 interact tasks (1:3 ratio)
    """
    db = SessionLocal()
    summary = {"sources_checked": 0, "videos_found": 0, "videos_downloaded": 0,
               "videos_queued": 0, "interact_generated": 0, "errors": []}

    try:
        enabled = SystemSettings.get(db, "scraper_enabled", "true")
        if enabled != "true":
            print("[Scraper] Disabled via settings.")
            return {**summary, "message": "disabled"}

        max_daily = int(SystemSettings.get(db, "scraper_max_daily", "5"))
        min_upvotes = int(SystemSettings.get(db, "scraper_min_upvotes", "1000"))
        target_account_id = SystemSettings.get(db, "scraper_target_account", "")
        target_profile_id = int(SystemSettings.get(db, "scraper_profile_id", "1"))

        # Resolve target platform from the Account
        target_platform = "x"
        if target_account_id:
            acct = db.query(Account).filter(Account.id == int(target_account_id)).first()
            if acct:
                raw = acct.platform.lower()
                target_platform = {"x": "x", "twitter": "x",
                                   "tiktok": "tiktok",
                                   "instagram": "instagram"}.get(raw, "x")

        sources = db.query(TargetSource).filter(TargetSource.active == 1).all()
        summary["sources_checked"] = len(sources)
        print(f"[Scraper] Running cycle — {len(sources)} active sources → {target_platform}")

        if not sources:
            return {**summary, "message": "no sources"}

        if not target_account_id:
            first_acct = db.query(Account).filter(Account.status == "Active").first()
            if first_acct:
                target_account_id = str(first_acct.id)
            else:
                print("[Scraper] No target account found.")
                return {**summary, "message": "no target account"}

        queued_count = 0
        all_new_task_ids = []

        for source in sources:
            if queued_count >= max_daily:
                break
            videos = []

            if source.platform == "reddit":
                name = source.name.strip().lstrip("r/")
                videos = await scrape_reddit(name, min_upvotes=min_upvotes)
            elif source.platform == "tiktok":
                handle = source.name.strip().lstrip("@")
                videos = await scrape_tiktok(handle, min_views=min_upvotes)
            elif source.platform == "youtube":
                videos = await scrape_youtube(source.url or source.name, min_views=min_upvotes)
            else:
                continue

            summary["videos_found"] += len(videos)
            source.last_scraped = datetime.now(timezone.utc)
            db.commit()

            for vid in videos:
                if queued_count >= max_daily:
                    break

                # Download
                print(f"[Scraper] Downloading: {vid['url'][:80]}...")
                dl_path = _download_video(vid["url"])
                if not dl_path:
                    summary["errors"].append(f"Download failed: {vid['url'][:60]}")
                    continue

                # MD5 Dedup
                try:
                    with open(dl_path, "rb") as f:
                        raw_bytes = f.read()
                    video_hash = hashlib.md5(raw_bytes).hexdigest()
                except Exception as exc:
                    summary["errors"].append(f"Hash error: {exc}")
                    try:
                        os.remove(dl_path)
                    except Exception:
                        pass
                    continue

                existing = db.query(VideoCache).filter(VideoCache.video_hash == video_hash).first()
                if existing:
                    print(f"[Scraper] ⏭ Duplicate (hash={video_hash[:12]}...) — skipping")
                    summary["errors"].append(f"Duplicate video (hash={video_hash[:12]}...)")
                    try:
                        os.remove(dl_path)
                    except Exception:
                        pass
                    continue

                summary["videos_downloaded"] += 1

                # Process through editor
                try:
                    processed_path = clean_and_alter_video(
                        dl_path,
                        str(PROCESSED_DIR / f"scraped_{uuid.uuid4().hex[:12]}.mp4"),
                    )
                except Exception as exc:
                    summary["errors"].append(f"Processing error: {exc}")
                    try:
                        os.remove(dl_path)
                    except Exception:
                        pass
                    continue

                # Copy to /static/videos/
                video_filename = f"scraped_{uuid.uuid4().hex[:12]}.mp4"
                static_video_path = str(BASE_DIR / "static" / "videos" / video_filename)
                try:
                    shutil.copy2(processed_path, static_video_path)
                except Exception as exc:
                    summary["errors"].append(f"Copy to static failed: {exc}")
                    try:
                        os.remove(dl_path)
                    except Exception:
                        pass
                    continue

                # Record in VideoCache (kept forever)
                db.add(VideoCache(video_hash=video_hash, source_url=vid["url"]))
                db.commit()

                # Generate caption
                caption = generate_caption(vid["title"], source.platform)

                # ─── Create the PUBLISH task ─────────────────────────────────
                publish_task = TaskQueue(
                    profile_id=target_profile_id,
                    platform=target_platform,
                    task_type="publish",
                    caption=caption,
                    file_path=static_video_path,
                    video_url=f"/videos/{video_filename}",
                    is_completed=False,
                )
                db.add(publish_task)
                db.commit()
                db.refresh(publish_task)
                all_new_task_ids.append(publish_task.id)

                # ContentQueue for dashboard visibility
                queue_item = ContentQueue(
                    account_id=int(target_account_id) if target_account_id else 0,
                    media_path=static_video_path,
                    caption=caption,
                    status="Pending",
                    scheduled_time=_random_schedule(),
                    log_message=f"Auto-scraped from {vid['source_name']} → task #{publish_task.id}",
                )
                db.add(queue_item)
                db.commit()

                # ScrapeLog
                db.add(ScrapeLog(
                    source_id=source.id, source_name=vid["source_name"],
                    title=vid["title"][:200], url=vid["url"],
                    downloaded_path=dl_path, processed_path=processed_path,
                    queue_id=queue_item.id, status="queued",
                ))
                db.commit()

                # Clean up raw download
                try:
                    os.remove(dl_path)
                except Exception:
                    pass

                queued_count += 1
                summary["videos_queued"] = queued_count

                # ─── 1:3 Ratio — generate 2-3 INTERACT tasks ─────────────────
                interact_count = random.randint(2, 3)
                interact_tasks = _generate_interact_tasks(
                    target_profile_id, target_platform, interact_count
                )
                for itask in interact_tasks:
                    db.add(TaskQueue(**itask))
                db.commit()
                summary["interact_generated"] = summary.get("interact_generated", 0) + interact_count

                msg = (f"Auto-queued '{vid['title'][:50]}...' from {vid['source_name']} "
                       f"(publish #{publish_task.id} + {interact_count} interact)")
                db.add(SystemLog(level="INFO", message=msg))
                db.commit()
                print(f"[Scraper] ✅ Publish #{publish_task.id} + {interact_count} interact: {vid['title'][:50]}")

        total = summary["videos_queued"] + summary.get("interact_generated", 0)
        print(f"[Scraper] Cycle complete: {summary['videos_queued']} publish + "
              f"{summary.get('interact_generated', 0)} interact = {total} total tasks")
        return {**summary, "message": "complete"}

    except Exception as exc:
        print(f"[Scraper] Cycle error: {exc}")
        summary["errors"].append(str(exc))
        return {**summary, "message": "error"}
    finally:
        db.close()
