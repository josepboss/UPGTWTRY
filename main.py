"""
PostPilot - FastAPI Application
Routes, scheduler, and API endpoints for the Social Media Content Automator.
"""

import os
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from models import (
    init_db, SessionLocal, Account, ContentQueue,
    SystemSettings, SystemLog,
)
from editor import process_media
from automation import post_to_platform

# ─── Paths ───────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
STAGED_DIR = BASE_DIR / "staged"

TEMPLATES_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
STAGED_DIR.mkdir(exist_ok=True)

# ─── Scheduler ───────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler()


# ─── App Lifespan ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start scheduler on boot, shut down cleanly on exit."""
    print("[PostPilot] Starting up...")
    init_db()
    scheduler.start()
    print("[PostPilot] Scheduler started.")
    yield
    scheduler.shutdown(wait=False)
    print("[PostPilot] Shut down.")


# ─── FastAPI App ─────────────────────────────────────────────────────────────

app = FastAPI(title="PostPilot", version="1.0.0", lifespan=lifespan)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Mount static files (images, etc.)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def add_log(level: str, message: str):
    """Insert a log entry into the database and print to console."""
    db = SessionLocal()
    try:
        db.add(SystemLog(level=level, message=message))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
    print(f"[PostPilot] [{level}] {message}")


def get_today_post_count(db) -> int:
    """Return how many posts were made today across all accounts."""
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.query(func.count(ContentQueue.id)).filter(
        ContentQueue.status == "Posted",
        ContentQueue.created_at >= start,
    ).scalar() or 0


# ═══════════════════════════════════════════════════════════════════════════════
#  PAGES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Render the main dashboard."""
    db = SessionLocal()
    try:
        accounts = db.query(Account).all()
        total_accounts = len(accounts)
        active_accounts = sum(1 for a in accounts if a.status == "Active")
        paused_accounts = sum(1 for a in accounts if a.status == "Paused")
        flagged_accounts = sum(1 for a in accounts if a.status in ("Flagged", "Needs Auth"))

        queue = db.query(ContentQueue).order_by(ContentQueue.created_at.desc()).limit(50).all()
        pending_count = sum(1 for q in queue if q.status == "Pending")
        posted_count = sum(1 for q in queue if q.status == "Posted")
        failed_count = sum(1 for q in queue if q.status == "Failed")
        today_posts = get_today_post_count(db)

        # System settings
        max_posts = SystemSettings.get(db, "max_posts_per_day", "10")
        min_delay = SystemSettings.get(db, "min_delay_minutes", "15")
        safe_mode = SystemSettings.get(db, "safe_mode", "true")

        # Recent logs
        recent_logs = db.query(SystemLog).order_by(SystemLog.id.desc()).limit(30).all()

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "accounts": accounts,
            "queue": queue,
            "total_accounts": total_accounts,
            "active_accounts": active_accounts,
            "paused_accounts": paused_accounts,
            "flagged_accounts": flagged_accounts,
            "pending_count": pending_count,
            "posted_count": posted_count,
            "failed_count": failed_count,
            "today_posts": today_posts,
            "max_posts": max_posts,
            "min_delay": min_delay,
            "safe_mode": safe_mode,
            "recent_logs": recent_logs,
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  ACCOUNTS API
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/accounts/add")
async def add_account(
    platform: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    proxy: str = Form(""),
):
    """Add a new social media account."""
    db = SessionLocal()
    try:
        # Generate a unique profile folder path
        profile_folder = str(BASE_DIR / "profiles" / f"profile_{uuid.uuid4().hex[:8]}")
        account = Account(
            platform=platform,
            username=username,
            password=password,
            proxy_string=proxy,
            profile_folder=profile_folder,
            status="Paused",
        )
        db.add(account)
        db.commit()
        add_log("INFO", f"Account added: {platform}/{username}")
        return RedirectResponse(url="/dashboard", status_code=303)
    except Exception as exc:
        db.rollback()
        add_log("ERROR", f"Failed to add account: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        db.close()


@app.post("/api/accounts/{account_id}/toggle")
async def toggle_account(account_id: int):
    """Toggle an account between Active and Paused."""
    db = SessionLocal()
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        account.status = "Paused" if account.status == "Active" else "Active"
        db.commit()
        add_log("INFO", f"Account {account.username} set to {account.status}")
        return {"status": account.status}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


@app.delete("/api/accounts/{account_id}")
@app.post("/api/accounts/{account_id}/delete")
async def delete_account(account_id: int):
    """Remove an account and its queued content."""
    db = SessionLocal()
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Delete associated queue items
        db.query(ContentQueue).filter(ContentQueue.account_id == account_id).delete()
        db.delete(account)
        db.commit()
        add_log("INFO", f"Account {account.username} deleted")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTENT QUEUE API
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/queue/add")
async def add_to_queue(
    account_id: int = Form(...),
    caption: str = Form(""),
    media: UploadFile = File(None),
):
    """Queue a new content item for posting."""
    db = SessionLocal()
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        media_path = ""
        if media and media.filename:
            # Save uploaded file to a temporary location
            upload_dir = STAGED_DIR / "uploads"
            upload_dir.mkdir(exist_ok=True)
            safe_name = f"{uuid.uuid4().hex}_{media.filename}"
            dest = upload_dir / safe_name
            with open(dest, "wb") as f:
                content = await media.read()
                f.write(content)
            media_path = str(dest)

        item = ContentQueue(
            account_id=account_id,
            media_path=media_path,
            caption=caption,
            status="Pending",
        )
        db.add(item)
        db.commit()
        add_log("INFO", f"Content queued for account #{account_id}")
        return RedirectResponse(url="/dashboard", status_code=303)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        add_log("ERROR", f"Failed to queue content: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


@app.post("/api/queue/{item_id}/retry")
async def retry_queue_item(item_id: int):
    """Reset a failed queue item back to Pending."""
    db = SessionLocal()
    try:
        item = db.query(ContentQueue).filter(ContentQueue.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Queue item not found")
        item.status = "Pending"
        item.log_message = ""
        db.commit()
        add_log("INFO", f"Queue item #{item_id} reset to Pending")
        return {"status": "Pending"}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


@app.delete("/api/queue/{item_id}")
@app.post("/api/queue/{item_id}/delete")
async def delete_queue_item(item_id: int):
    """Remove a queue item."""
    db = SessionLocal()
    try:
        item = db.query(ContentQueue).filter(ContentQueue.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Queue item not found")
        db.delete(item)
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  SETTINGS API
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/settings/update")
async def update_settings(
    max_posts: int = Form(10),
    min_delay: int = Form(15),
    safe_mode: str = Form("true"),
):
    """Update global system settings."""
    db = SessionLocal()
    try:
        SystemSettings.set(db, "max_posts_per_day", str(max_posts),
                           "Maximum posts per day per account")
        SystemSettings.set(db, "min_delay_minutes", str(min_delay),
                           "Minimum delay in minutes between posts")
        SystemSettings.set(db, "safe_mode", safe_mode,
                           "Global safety toggle")
        add_log("INFO", "System settings updated")
        return RedirectResponse(url="/dashboard", status_code=303)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  LOGS API
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/logs")
async def get_logs():
    """Return recent logs as JSON for live streaming."""
    db = SessionLocal()
    try:
        logs = db.query(SystemLog).order_by(SystemLog.id.desc()).limit(30).all()
        return [
            {
                "id": log.id,
                "level": log.level,
                "message": log.message,
                "time": log.created_at.strftime("%H:%M:%S") if log.created_at else "",
            }
            for log in logs
        ]
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  SYSTEM ACTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/system/process-queue")
async def process_queue_endpoint():
    """
    Manually trigger processing of the next pending queue item.
    The scheduler also calls this automatically.
    """
    result = await process_next_queue_item()
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  SCHEDULED TASK
# ═══════════════════════════════════════════════════════════════════════════════

async def process_next_queue_item() -> dict:
    """
    Pick the next pending item from the queue, process its media,
    post to the target platform, and update the database accordingly.
    """
    db = SessionLocal()
    try:
        # Fetch the oldest pending item
        item = (
            db.query(ContentQueue)
            .filter(ContentQueue.status == "Pending")
            .order_by(ContentQueue.created_at.asc())
            .first()
        )
        if not item:
            return {"status": "idle", "message": "No pending items"}

        # Fetch the associated account
        account = db.query(Account).filter(Account.id == item.account_id).first()
        if not account:
            item.status = "Failed"
            item.log_message = "Account not found"
            db.commit()
            return {"status": "error", "message": "Account not found"}

        # Check safe mode / daily limits
        safe_mode = SystemSettings.get(db, "safe_mode", "true") == "true"
        max_posts = int(SystemSettings.get(db, "max_posts_per_day", "10"))
        today_count = get_today_post_count(db)

        if safe_mode and today_count >= max_posts:
            add_log("WARN", f"Daily post limit ({max_posts}) reached — skipping")
            return {"status": "throttled", "message": f"Daily limit {max_posts} reached"}

        # Mark as processing
        item.status = "Processing"
        db.commit()

        # Process media if present
        processed_media = item.media_path
        if item.media_path and os.path.isfile(item.media_path):
            try:
                processed_media = process_media(item.media_path)
                add_log("INFO", f"Media processed for queue item #{item.id}")
            except Exception as exc:
                item.status = "Failed"
                item.log_message = f"Media processing error: {exc}"
                db.commit()
                add_log("ERROR", f"Media processing failed: {exc}")
                return {"status": "error", "message": str(exc)}

        # Post to platform
        try:
            add_log("INFO", f"Posting to {account.platform} as @{account.username}...")
            post_id = await post_to_platform(
                platform=account.platform,
                profile_dir=account.profile_folder,
                proxy_string=account.proxy_string,
                caption=item.caption,
                media_path=processed_media or "",
            )
            item.status = "Posted"
            item.platform_post_id = post_id or ""
            item.log_message = "Posted successfully"
            add_log("INFO", f"Queue item #{item.id} posted to {account.platform}")
        except PermissionError:
            item.status = "Failed"
            item.log_message = "Session logged out — needs manual authentication"
            account.status = "Needs Auth"
            add_log("WARN", f"Account @{account.username} needs authentication")
        except Exception as exc:
            item.status = "Failed"
            item.log_message = f"Post error: {exc}"
            add_log("ERROR", f"Post failed for item #{item.id}: {exc}")

        db.commit()

        # Clean up staged processed media after some time
        # (skipped for brevity — can be a background cleanup task)

        return {"status": item.status, "item_id": item.id}

    except Exception as exc:
        add_log("ERROR", f"Queue processor error: {exc}")
        return {"status": "error", "message": str(exc)}
    finally:
        db.close()


# ─── Schedule the queue processor every N minutes ────────────────────────────

@scheduler.scheduled_job("interval", minutes=1, id="queue_processor", replace_existing=True)
async def scheduled_queue_processor():
    """Run every minute: process one queue item if any pending."""
    print("[Scheduler] Checking queue...")
    try:
        await process_next_queue_item()
    except Exception as exc:
        add_log("ERROR", f"Scheduled processor error: {exc}")


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("""
    ╔══════════════════════════════════════════╗
    ║         PostPilot  v1.0.0                ║
    ║  Social Media Content Automator          ║
    ╚══════════════════════════════════════════╝
    """)
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
