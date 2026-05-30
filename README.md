# PostPilot — Social Media Content Automator

A self-hosted, multi-account content automation engine for **X (Twitter)** and **TikTok**. Uses **Playwright** with stealth techniques to bypass API fees, with a clean web dashboard for management.

> ⚠️ **Self-Hosted Desktop Application** — Requires Python 3.10+ running on your local machine. This is not a web-deployable app.

---

## Quick Start

### 1. Prerequisites

- **Python 3.10+** — [Download](https://python.org/downloads)
- **FFmpeg** — `brew install ffmpeg` (macOS) or `apt install ffmpeg` (Linux)
- **Chromium** — Installed automatically via Playwright

### 2. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Run the dashboard

```bash
python main.py
```

Then open **http://127.0.0.1:8000** in your browser.

---

## First-Time Account Setup

1. **Add an account** via the dashboard Accounts tab
2. **Log in manually** — PostPilot launches a persistent browser profile. Navigate to x.com or tiktok.com and log in *once*. The session (cookies, local storage) is saved permanently in the `profiles/` folder
3. **Activate** the account in the dashboard
4. **Queue content** and let the scheduler post automatically

---

## Features

| Feature | Description |
|---------|-------------|
| **Multi-Account** | Manage unlimited X/TikTok accounts with isolated browser profiles |
| **Persistent Sessions** | Login once — cookies survive forever via `launch_persistent_context` |
| **Proxy Support** | Assign individual HTTP proxies per account |
| **Media Processing** | FFmpeg strips metadata and alters fingerprints to bypass duplicate detection |
| **Stealth Automation** | Disables automation flags, randomizes viewports, human-like Gaussian delays |
| **Content Queue** | Schedule posts with captions and media, auto-processed sequentially |
| **Safe Mode** | Configurable daily limits and min delays between posts |
| **Live Logs** | Real-time streaming of system events on the dashboard |

---

## Project Structure

```
├── main.py              # FastAPI app (routes, scheduler, API)
├── models.py            # SQLite database schema
├── editor.py            # FFmpeg media processing engine
├── automation.py        # Playwright automation (X + TikTok)
├── templates/
│   └── dashboard.html   # Admin dashboard (Tailwind CSS)
├── profiles/            # Browser profiles (one folder per account)
├── staged/              # Processed media staging area
└── static/              # Static assets (images)
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | Main dashboard |
| POST | `/api/accounts/add` | Add account |
| POST | `/api/accounts/{id}/toggle` | Toggle Active/Paused |
| POST | `/api/accounts/{id}/delete` | Remove account |
| POST | `/api/queue/add` | Queue content |
| POST | `/api/queue/{id}/retry` | Retry failed item |
| POST | `/api/queue/{id}/delete` | Delete queue item |
| POST | `/api/settings/update` | Update settings |
| GET | `/api/logs` | Get recent logs |
| POST | `/api/system/process-queue` | Process next item |
