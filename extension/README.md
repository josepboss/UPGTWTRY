# PostPilot Chrome Extension

Stealth DOM automation for X (Twitter), TikTok, and Instagram Reels.

## Architecture

This extension runs on your **local machine** across multiple Chrome profiles.
Each extension instance polls the VPS backend every 45–90 minutes for tasks and
executes them directly in the browser via DOM injection — no Playwright required.

## Setup

1. **Install the extension**
   - Open `chrome://extensions`
   - Enable **Developer mode** (top right)
   - Click **Load unpacked** and select the `extension/` folder

2. **Configure**
   - Click the PostPilot icon in the toolbar to open the popup
   - Set your VPS Base URL (e.g., `http://your-vps-ip:8000`)
   - Select Profile ID — each Chrome profile must use a unique ID (1, 2, or 3)
   - Select the platform you want this profile to handle
   - Click **Save**

3. **Repeat** for each Chrome profile on your machine (each gets its own profile ID)

## How It Works

| Step | Component | What Happens |
|------|-----------|--------------|
| 1 | **VPS Scraper** | Runs daily at 2 AM, downloads viral content, MD5-deduplicates, processes via FFmpeg, saves to `/static/videos/`, writes to `TaskQueue` |
| 2 | **background.js** | Polls `GET /api/next-task?profile_id=N&platform=X` every 45–90 min. Opens a tab when a task arrives |
| 3 | **content.js** | Injects video via `DataTransfer` + `File()` into the native file picker, inserts caption, clicks Post/Share |
| 4 | **Cleanup** | Content script signals completion → background.js calls `POST /api/cleanup-task/{id}` → VPS deletes the .mp4 |

## Task Types

- **publish** — Upload a video with caption via native file picker injection
- **interact** — Scroll the feed, like 1–2 posts randomly, idle 1–3 minutes

## Platform Target URLs

| Platform | URL Opened by Extension |
|----------|------------------------|
| X | `https://x.com/home` |
| TikTok | `https://www.tiktok.com/creator-center/upload` |
| Instagram | `https://www.instagram.com/` |