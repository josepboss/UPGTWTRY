/**
 * PostPilot Extension — Background Service Worker
 *
 * Uses a recursive setTimeout loop (not setInterval) to poll the VPS backend
 * for tasks.  After each poll cycle it randomises the next check between
 * 45–90 minutes to avoid predictable patterns.
 *
 * Each Chrome profile running this extension uses a unique PROFILE_ID.
 */

// ═══════════════════════════════════════════════════════════════════════════════
//  USER CONFIGURATION — update these values for your setup
// ═══════════════════════════════════════════════════════════════════════════════

const CONFIG = {
  VPS_BASE_URL: "http://localhost:8000",
  PROFILE_ID: 1,                  // 1, 2, or 3 — must be unique per Chrome profile
  PLATFORM: "x",                  // "x", "tiktok", or "instagram"
  POLL_MIN_MS: 45 * 60 * 1000,    // 45 minutes
  POLL_MAX_MS: 90 * 60 * 1000,    // 90 minutes
};

// ═══════════════════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════════════════

let activeTaskId = null;
let isProcessingTask = false;

// ═══════════════════════════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════════════════════════

function randomWait() {
  const ms =
    Math.floor(Math.random() * (CONFIG.POLL_MAX_MS - CONFIG.POLL_MIN_MS + 1)) +
    CONFIG.POLL_MIN_MS;
  console.log(`[PostPilot] Next poll in ${Math.round(ms / 60000)} minutes`);
  return ms;
}

async function apiGet(path) {
  const url = `${CONFIG.VPS_BASE_URL}${path}`;
  console.log(`[PostPilot] GET ${url}`);
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function apiPost(path) {
  const url = `${CONFIG.VPS_BASE_URL}${path}`;
  console.log(`[PostPilot] POST ${url}`);
  const resp = await fetch(url, { method: "POST" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

// ═══════════════════════════════════════════════════════════════════════════════
//  POLL LOOP
// ═══════════════════════════════════════════════════════════════════════════════

async function pollLoop() {
  try {
    // Fetch config from VPS on first run
    const stored = await chrome.storage.local.get(["vpsConfig"]);
    if (!stored.vpsConfig) {
      try {
        const cfg = await apiGet("/api/extension/config");
        await chrome.storage.local.set({ vpsConfig: cfg });
        CONFIG.VPS_BASE_URL = cfg.vps_base_url || CONFIG.VPS_BASE_URL;
      } catch (e) {
        console.warn("[PostPilot] Could not fetch config, using defaults:", e);
      }
    } else {
      CONFIG.VPS_BASE_URL =
        stored.vpsConfig.vps_base_url || CONFIG.VPS_BASE_URL;
    }

    const data = await apiGet(
      `/api/next-task?profile_id=${CONFIG.PROFILE_ID}&platform=${CONFIG.PLATFORM}`
    );

    if (data.status === "ok" && data.task) {
      const task = data.task;
      console.log(
        `[PostPilot] Received task #${task.id}: ${task.task_type} on ${task.platform}`
      );

      isProcessingTask = true;
      activeTaskId = task.id;

      // Store the task so content.js can read it
      await chrome.storage.local.set({ activeTask: task });

      // Open the appropriate platform URL
      let targetUrl;
      switch (task.platform) {
        case "x":
          targetUrl = "https://x.com/home";
          break;
        case "tiktok":
          targetUrl = "https://www.tiktok.com/creator-center/upload";
          break;
        case "instagram":
          targetUrl = "https://www.instagram.com/";
          break;
        default:
          targetUrl = "https://x.com/home";
      }

      const tab = await chrome.tabs.create({ url: targetUrl, active: true });
      console.log(`[PostPilot] Opened tab ${tab.id} for ${task.platform}`);

      // Wait for content script to complete before resuming poll loop.
      // The content script signals completion via storage change.
    } else {
      console.log(`[PostPilot] No tasks — waiting...`);
      isProcessingTask = false;
      activeTaskId = null;
      scheduleNext();
    }
  } catch (err) {
    console.error(`[PostPilot] Poll error:`, err);
    isProcessingTask = false;
    activeTaskId = null;
    scheduleNext();
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  LISTEN FOR CONTENT SCRIPT COMPLETION
// ═══════════════════════════════════════════════════════════════════════════════

chrome.storage.onChanged.addListener(async (changes, area) => {
  if (area === "local" && changes.taskResult) {
    const result = changes.taskResult.newValue;
    console.log(`[PostPilot] Task result:`, result);

    // Cleanup on VPS
    try {
      if (result.taskId) {
        await apiPost(`/api/cleanup-task/${result.taskId}`);
        console.log(`[PostPilot] Cleanup done for task #${result.taskId}`);
      }
    } catch (e) {
      console.error(`[PostPilot] Cleanup failed:`, e);
    }

    // Clear active task
    await chrome.storage.local.remove(["activeTask", "taskResult"]);

    isProcessingTask = false;
    activeTaskId = null;

    // Schedule next poll
    scheduleNext();
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
//  SCHEDULER
// ═══════════════════════════════════════════════════════════════════════════════

let timeoutId = null;

function scheduleNext() {
  if (timeoutId) clearTimeout(timeoutId);
  timeoutId = setTimeout(() => {
    if (!isProcessingTask) {
      pollLoop();
    }
  }, randomWait());
}

// ═══════════════════════════════════════════════════════════════════════════════
//  BOOT
// ═══════════════════════════════════════════════════════════════════════════════

// Start the first poll after a short delay (gives extension time to load)
chrome.runtime.onInstalled.addListener(() => {
  console.log(`[PostPilot] Installed — profile ${CONFIG.PROFILE_ID}`);
  setTimeout(pollLoop, 5000);
});

chrome.runtime.onStartup.addListener(() => {
  console.log(`[PostPilot] Started — profile ${CONFIG.PROFILE_ID}`);
  setTimeout(pollLoop, 5000);
});

// Also start immediately if the service worker wakes up
setTimeout(pollLoop, 5000);

console.log(
  `[PostPilot] Background initialized (profile=${CONFIG.PROFILE_ID}, platform=${CONFIG.PLATFORM})`
);
