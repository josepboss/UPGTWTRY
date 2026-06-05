# PostPilot — Social Media Content Automator

## Tech Stack

- **Backend:** Python FastAPI
- **Database:** SQLite + SQLAlchemy ORM
- **Task Queue:** APScheduler (async)
- **Automation:** Chrome Extension (stealth DOM) on local machine
- **Content Scraper:** yt-dlp + Reddit JSON API + MD5 dedup (VideoCache)
- **Frontend:** Jinja2 Templates + Tailwind CSS (CDN)

## Project Structure

```
├── main.py              # FastAPI app entry point (routes, scheduler, API)
├── models.py            # SQLAlchemy database models
├── editor.py            # FFmpeg media processing engine
├── automation.py        # Playwright automation for X & TikTok (legacy)
├── scraper.py           # Content ingestion engine (Reddit, TikTok, YouTube)
├── extension/           # Chrome Extension for stealth DOM automation
│   ├── manifest.json
│   ├── background.js
│   ├── content.js
│   ├── popup.html
│   └── popup.js
├── templates/
│   └── dashboard.html   # Main admin dashboard
├── profiles/            # Browser persistent profiles (one per account)
├── staged/              # Temporary processed media files
├── static/              # Static assets + /videos/ for extension consumption
├── requirements.txt     # Python dependencies
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | Render the dashboard |
| POST | `/api/accounts/add` | Add a new account |
| POST | `/api/accounts/{id}/toggle` | Toggle Active/Paused |
| POST/DELETE | `/api/accounts/{id}/delete` | Remove account |
| POST | `/api/queue/add` | Queue new content |
| POST | `/api/queue/{id}/retry` | Retry failed item |
| POST/DELETE | `/api/queue/{id}/delete` | Delete queue item |
| POST | `/api/settings/update` | Update global settings |
| GET | `/api/logs` | Fetch recent system logs |
| POST | `/api/system/process-queue` | Process next pending item |
| POST | `/api/scraper/run` | Trigger manual scrape cycle |
| POST | `/api/scraper/sources/add` | Add scraper source |
| POST | `/api/scraper/sources/{id}/toggle` | Toggle source active/paused |
| POST/DELETE | `/api/scraper/sources/{id}/delete` | Remove source |
| POST | `/api/scraper/settings/update` | Update scraper config |
| GET | `/api/scraper/logs` | Fetch scrape logs |
| GET | `/api/next-task?profile_id={id}&platform={s}` | Fetch next extension task |
| POST | `/api/cleanup-task/{id}` | Mark task complete & delete .mp4 |
| GET | `/api/extension/config` | Return VPS URL for extension config |
| POST | `/api/settings/update-vps` | Update VPS URL + profile ID |

## Running

```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

## First-Time Setup

1. Add an account via the dashboard
2. Launch the app, log in to the platform in the persistent browser session
3. The session is saved — subsequent posts are automated
