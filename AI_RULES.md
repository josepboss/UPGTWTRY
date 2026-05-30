# PostPilot — Social Media Content Automator

## Tech Stack

- **Backend:** Python FastAPI
- **Database:** SQLite + SQLAlchemy ORM
- **Task Queue:** APScheduler (async)
- **Automation:** Playwright (async API with stealth features)
- **Frontend:** Jinja2 Templates + Tailwind CSS (CDN)

## Project Structure

```
├── main.py              # FastAPI app entry point (routes, scheduler, API)
├── models.py            # SQLAlchemy database models
├── editor.py            # FFmpeg media processing engine
├── automation.py        # Playwright automation for X & TikTok
├── templates/
│   └── dashboard.html   # Main admin dashboard
├── profiles/            # Browser persistent profiles (one per account)
├── staged/              # Temporary processed media files
├── static/              # Static assets (images, etc.)
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
