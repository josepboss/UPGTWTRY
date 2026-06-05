"""
PostPilot - Content Scraper & Ingestion Engine
Automatically discovers viral content from Reddit, TikTok, and YouTube,
processes it through editor.py, and queues it for posting.

Designed to run as a daily scheduled task via APScheduler.
"""

import os
import re
import json
import random
import hashlib
import shutil
import subprocess
import asyncio
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

# Niche-relevant generic hashtags to randomly append
HASHTAG_POOL = [
    "#viral", "#trending", "#fyp", "#explore", "#reels",
    "#amazing", "#interesting", "#mindblowing", "#satisfying",
    "#rare", "#unique", "#wow", "#incredible", "#mustwatch",
    "#shorts", "#dailymotion", "#contentcreator",
]


def _random_hashtags(count: int = 2) -> str:
    """Pick *count* random hashtags from the pool."""
    return " ".join(random.sample(HASHTAG_POOL, min(count, len(HASHTAG_POOL))))


def _clean_title(title: str) -> str:
    """
    Strip @mentions, original hashtags, and URLs from a title.
    Returns a clean caption ready for reposting.
    """
    if not title:
        return ""
    # Remove @mentions
    title = re.sub(r"@\w+", "", title)
    # Remove hashtags
    title = re.sub(r"#\w+", "", title)
    # Remove URLs
    title = re.sub(r"https?://\S+", "", title)
    # Collapse whitespace
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _random_schedule() -> datetime:
    """
    Return a random datetime between 2 PM and 7 PM today (or tomorrow if
    it's already past 7 PM). This optimises for peak engagement windows.
    """
    now = datetime.now(timezone.utc)
    # Choose a random hour between 14 (2 PM) and 19 (7 PM)
    hour = random.randint(14, 19)
    minute = random.randint(0, 59)
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if scheduled <= now:
        # If already past today's window, schedule for tomorrow
        scheduled += timedelta(days=1)
    return scheduled


def _ytdlp_available() -> bool:
    """Check whether yt-dlp is on the system PATH."""
    return os.system("yt-dlp --version > /dev/null 2>&1") == 0


def _extract_info(url: str) -> dict:
    """Use yt-dlp to extract video info without downloading."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", url],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout.strip().split("\n")[0])
    except Exception as exc:
        print(f"[Scraper] yt-dlp info failed for {url}: {exc}")
    return {}


def _download_video(url: str, output_dir: str = None) -> str:
    """
    Download a video using yt-dlp.
    Returns the path to the downloaded file, or empty string on failure.
    """
    output_dir = output_dir or str(RAW_DIR)
    os.makedirs(output_dir, exist_ok=True)
    output_template = os.path.join(output_dir, f"dl_{uuid.uuid4().hex[:8]}.%(ext)s")

    try:
        cmd = [
            "yt-dlp",
            "-f", "best[height<=1080]",           # prefer up to 1080p
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

        # Find the downloaded file
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
    """
    Fetch top daily posts from a subreddit via the public JSON API.
    Returns a list of dicts with keys: title, url, upvotes, source_url.
    """
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

                # Find the actual video/media URL
                media_url = _reddit_media_url(post_data)
                if not media_url:
                    continue

                if upvotes < min_upvotes:
                    continue

                videos.append({
                    "title": title,
                    "url": media_url,
                    "upvotes": upvotes,
                    "source_url": post_url,
                    "source_name": f"r/{subreddit}",
                    "platform": "reddit",
                })
                print(f"[Scraper]   Found: {upvotes} upvotes — {title[:60]}")
    except Exception as exc:
        print(f"[Scraper] Reddit error: {exc}")

    return videos


def _reddit_media_url(post: dict) -> str:
    """Extract the best video URL from a Reddit post dict."""
    # Direct Reddit video (v.redd.it)
    if post.get("is_video") and post.get("domain") == "v.redd.it":
        media = post.get("media") or {}
        reddit_video = media.get("reddit_video") or {}
        fallback = reddit_video.get("fallback_url", "")
        if fallback and "DASH" in fallback:
            # Reddit DASH videos need to be converted — yt-dlp handles this
            return post.get("url", fallback)
        return post.get("url", "")

    # Crosspost
    crosspost = post.get("crosspost_parent_list") or []
    if crosspost:
        return _reddit_media_url(crosspost[0])

    # External video domains that yt-dlp can handle
    domain = post.get("domain", "")
    url = post.get("url", "")
    supported = ("youtube.com", "youtu.be", "tiktok.com", "vimeo.com",
                 "streamable.com", "gfycat.com", "reddit.com")
    if any(d in domain for d in supported):
        return url

    # Check if it's a gallery with video
    gallery = post.get("media_metadata") or {}
    if gallery:
        for item_id, item in gallery.items():
            if item.get("status") == "valid" and item.get("e") == "Video":
                return f"https://v.redd.it/{item_id.replace('_','')}"

    return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  TIKTOK SCRAPER (via yt-dlp)
# ═══════════════════════════════════════════════════════════════════════════════

async def scrape_tiktok(handle: str, min_views: int = 50000, limit: int = 10) -> list:
    """
    Fetch recent videos from a public TikTok handle using yt-dlp.
    Returns a list of dicts with keys: title, url, views, source_url.
    """
    print(f"[Scraper] TikTok: checking @{handle}...")
    profile_url = f"https://www.tiktok.com/@{handle}"
    videos = []

    try:
        # yt-dlp flat playlist to get video list
        cmd = [
            "yt-dlp", "--flat-playlist", "--dump-json",
            "--no-download", "--quiet",
            profile_url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"[Scraper] TikTok yt-dlp failed: {result.stderr[:200]}")
            return []

        lines = result.stdout.strip().split("\n")
        for line in lines[:limit]:
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
                    "title": title,
                    "url": url,
                    "views": views,
                    "source_url": url,
                    "source_name": f"@{handle}",
                    "platform": "tiktok",
                })
                print(f"[Scraper]   Found: {views} views — {title[:60]}")
            except json.JSONDecodeError:
                continue
    except Exception as exc:
        print(f"[Scraper] TikTok error: {exc}")

    return videos


# ═══════════════════════════════════════════════════════════════════════════════
#  YOUTUBE SHORTS SCRAPER (via yt-dlp)
# ═══════════════════════════════════════════════════════════════════════════════

async def scrape_youtube(channel_url: str, min_views: int = 10000, limit: int = 10) -> list:
    """
    Fetch recent Shorts from a YouTube channel using yt-dlp.
    *channel_url* can be a channel handle URL or channel ID URL.
    Returns a list of dicts.
    """
    print(f"[Scraper] YouTube: checking {channel_url}...")
    videos = []

    try:
        cmd = [
            "yt-dlp", "--flat-playlist", "--dump-json",
            "--no-download", "--quiet",
            channel_url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"[Scraper] YouTube yt-dlp failed: {result.stderr[:200]}")
            return []

        lines = result.stdout.strip().split("\n")
        for line in lines[:limit]:
            if not line.strip():
                continue
            try:
                info = json.loads(line)
                title = info.get("title", "")
                url = info.get("url") or info.get("webpage_url", "")
                views = info.get("view_count", 0) or 0

                # Filter for Shorts (videos under 60s or /shorts/ in URL)
                duration = info.get("duration", 999)
                is_short = "/shorts/" in url or (duration and duration <= 60)
                if not is_short:
                    continue
                if views < min_views:
                    continue

                videos.append({
                    "title": title,
                    "url": url,
                    "views": views,
                    "source_url": url,
                    "source_name": channel_url.split("/")[-1],
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
    """
    Clean a source title and append random hashtags.
    Returns a ready-to-use caption string.
    """
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
    # Keep under 400 chars for TikTok
    if len(caption) > 400:
        caption = caption[:397] + "..."
    return caption


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN SCRAPE LOOP
# ═══════════════════════════════════════════════════════════════════════════════

async def run_scrape_cycle() -> dict:
    """
    Full scrape cycle:
    1. Read active target sources from the database
    2. Scrape each source for viral content
    3. Download, process, and queue the best finds
    4. Log everything to the database
    Returns a summary dict.
    """
    db = SessionLocal()
    summary = {"sources_checked": 0, "videos_found": 0, "videos_downloaded": 0,
               "videos_queued": 0, "errors": []}

    try:
        # Check if scraper is enabled
        enabled = SystemSettings.get(db, "scraper_enabled", "true")
        if enabled != "true":
            print("[Scraper] Scraper is disabled via settings.")
            return {**summary, "message": "disabled"}

        # Get config
        max_daily = int(SystemSettings.get(db, "scraper_max_daily", "5"))
        min_upvotes = int(SystemSettings.get(db, "scraper_min_upvotes", "1000"))
        target_account_id = SystemSettings.get(db, "scraper_target_account", "")

        # Get active sources
        sources = db.query(TargetSource).filter(TargetSource.active == 1).all()
        summary["sources_checked"] = len(sources)
        print(f"[Scraper] Running cycle — {len(sources)} active sources")

        if not sources:
            print("[Scraper] No active sources configured.")
            return {**summary, "message": "no sources"}

        if not target_account_id:
            # Try to use the first active account as fallback
            first_acct = db.query(Account).filter(
                            Account.status == "Active"
                        ).first()
            if first_acct:
                target_account_id = str(first_acct.id)
            else:
                print("[Scraper] No target account set and no active accounts found.")
                return {**summary, "message": "no target account"}

        queued_count = 0

        # Resolve target account for platform mapping
                target_platform = "x"  # default
                target_profile_id = int(SystemSettings.get(db, "scraper_profile_id", "1"))
                if target_account_id:
                    acct = db.query(Account).filter(Account.id == int(target_account_id)).first()
                    if acct:
                        raw = acct.platform.lower()
                        target_platform = {"x": "x", "twitter": "x",
                                           "tiktok": "tiktok",
                                           "instagram": "instagram"}.get(raw, "x")
        
                for source in sources:
                    if queued_count >= max_daily:
                        break
        
                    videos = []
        
                    if source.platform == "reddit":
                        # Source name is the subreddit name (e.g., "damnthatsinteresting")
                        name = source.name.strip().lstrip("r/")
                        videos = await scrape_reddit(name, min_upvotes=min_upvotes)
                    elif source.platform == "tiktok":
                        handle = source.name.strip().lstrip("@")
                        videos = await scrape_tiktok(handle, min_views=min_upvotes)
                    elif source.platform == "youtube":
                        videos = await scrape_youtube(source.url or source.name,
                                                       min_views=min_upvotes)
                    else:
                        continue
        
                    summary["videos_found"] += len(videos)
        
                    # Update last_scraped timestamp
                    source.last_scraped = datetime.now(timezone.utc)
                    db.commit()
        
                    for vid in videos:
                        if queued_count >= max_daily:
                            break
        
                        # Download video
                        print(f"[Scraper] Downloading: {vid['url'][:80]}...")
                        dl_path = _download_video(vid["url"])
                        if not dl_path:
                            summary["errors"].append(f"Download failed: {vid['url'][:60]}")
                            continue
        
                        # ─── MD5 Dedup Check ────────────────────────────────────────
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
        
                        existing = db.query(VideoCache).filter(
                            VideoCache.video_hash == video_hash
                        ).first()
                        if existing:
                            print(f"[Scraper] ⏭ Duplicate (hash={video_hash[:12]}...) — skipping")
                            summary["errors"].append(
                                f"Duplicate video (hash={video_hash[:12]}...)"
                            )
                            try:
                                os.remove(dl_path)
                            except Exception:
                                pass
                            continue
        
                        summary["videos_downloaded"] += 1
        
                        # Process through editor.py
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
        
                        # Copy processed file to /static/videos/ for extension access
                        video_filename = f"scraped_{uuid.uuid4().hex[:12]}.mp4"
                        static_video_path = str(
                            BASE_DIR / "static" / "videos" / video_filename
                        )
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
                        db.add(VideoCache(
                            video_hash=video_hash,
                            source_url=vid["url"],
                        ))
                        db.commit()
        
                        # Generate caption
                        caption = generate_caption(vid["title"], source.platform)
        
                        # Build video_url (relative to VPS base)
                        video_url = f"/videos/{video_filename}"
        
                        # Create TaskQueue item for Chrome Extension
                        task_item = TaskQueue(
                            profile_id=target_profile_id,
                            platform=target_platform,
                            task_type="publish",
                            caption=caption,
                            file_path=static_video_path,
                            video_url=video_url,
                            is_completed=False,
                        )
                        db.add(task_item)
                        db.commit()
                        db.refresh(task_item)
        
                        # Also keep the ContentQueue entry for dashboard visibility
                        queue_item = ContentQueue(
                            account_id=int(target_account_id) if target_account_id else 0,
                            media_path=static_video_path,
                            caption=caption,
                            status="Pending",
                            scheduled_time=_random_schedule(),
                            log_message=f"Auto-scraped from {vid['source_name']} → task #{task_item.id}",
                        )
                        db.add(queue_item)
                        db.commit()
        
                        # Log the scrape
                        scrape_entry = ScrapeLog(
                            source_id=source.id,
                            source_name=vid["source_name"],
                            title=vid["title"][:200],
                            url=vid["url"],
                            downloaded_path=dl_path,
                            processed_path=processed_path,
                            queue_id=queue_item.id,
                            status="queued",
                        )
                        db.add(scrape_entry)
                        db.commit()
        
                        # Delete raw download to save space
                        try:
                            os.remove(dl_path)
                        except Exception:
                            pass
        
                        queued_count += 1
                        summary["videos_queued"] = queued_count
        
                        # Log to system
                        log_entry = SystemLog(
                            level="INFO",
                            message=f"Auto-queued '{vid['title'][:50]}...' from {vid['source_name']} (task #{task_item.id})",
                        )
                        db.add(log_entry)
                        db.commit()
        
                        print(f"[Scraper] ✅ Task #{task_item.id} queued: {vid['title'][:50]}")

        print(f"[Scraper] Cycle complete: {summary['videos_queued']} items queued")
        return {**summary, "message": "complete"}

    except Exception as exc:
        print(f"[Scraper] Cycle error: {exc}")
        summary["errors"].append(str(exc))
        return {**summary, "message": "error"}
    finally:
        db.close()