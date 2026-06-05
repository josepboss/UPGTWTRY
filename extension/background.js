/**
 * PostPilot Extension — Background Service Worker
 *
 * Uses a recursive setTimeout loop (not setInterval) to poll the VPS backend
 * for tasks.  After each poll cycle it randomises the next check between
 * 45-90 minutes to avoid predictable patterns.
 *
 * Each Chrome profile running this extension uses a unique PROFILE_ID set in
 * the extension popup.  The PLATFORM is also configurable via popup storage.
 *
 * Interact tasks open the platform's feed page; publish tasks open the
 * specific upload/compose page.
 */

// ═══════════════════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════════════════

let activeTaskId = null;
let activeTabId = null;
let isProcessingTask = false;

// ═══════════════════════════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════════════════════════

function randomBetween(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randomWait() {
  const ms = randomBetween(45 * 60 * 1000, 90 * 60 * 1000);
  console.log(`[PostPilot] Next poll in ~${Math.round(ms / 60000)} minutes`);
  return ms;
}

async function apiGet(path) {
  const base = await getVpsBaseUrl();
  const url = `${base}${path}`;
  console.log(`[PostPilot] GET ${url}`);
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function apiPost(path) {
  const base = await getVpsBaseUrl();
  const url = `${base}${path}`;
  console.log(`[PostPilot] POST ${url}`);
  const resp = await fetch(url, { method: "POST" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function getVpsBaseUrl() {
  const stored = await chrome.storage.local.get(["vpsConfig"]);
  return (stored.vpsConfig && stored.vpsConfig.vps_base_url) || "http://localhost:8000";
}

async function getConfigFromStorage() {
  const stored = await chrome.storage.local.get(["vpsConfig", "profileId", "platform"]);
  return {
    vps_base_url: (stored.vpsConfig && stored.vpsConfig.vps_base_url) || "http://localhost:8000",
    profile_id: parseInt(stored.profileId || (stored.vpsConfig && stored.vpsConfig.profile_id) || 1, 10),
    platform: stored.platform || (stored.vpsConfig && stored.vpsConfig.platform) || "x",
  };
}

function getTargetUrl(task) {
  const { platform, task_type } = task;

  if (task_type === "interact") {
    switch (platform) {
      case "x":         return "https://x.com/home";
      case "tiktok":    return "https://www.tiktok.com/foryou";
      case "instagram": return "https://www.instagram.com/";
      default:          return "https://x.com/home";
    }
  }

  switch (platform) {
    case "x":         return "https://x.com/compose/post";
    case "tiktok":    return "https://www.tiktok.com/creator-center/upload";
    case "instagram": return "https://www.instagram.com/";
    default:          return "https://x.com/compose/post";
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  POLL LOOP
// ═══════════════════════════════════════════════════════════════════════════════

async function pollLoop() {
  try {
    const config = await getConfigFromStorage();

    const data = await apiGet(
      `/api/next-task?profile_id=${config.profile_id}&platform=${config.platform}`
    );

    if (data.status === "ok" && data.task) {
      const task = data.task;
      console.log(
        `[PostPilot] Received task #${task.id}: ${task.task_type} on ${task.platform}`
      );

      isProcessingTask = true;
      activeTaskId = task.id;

      await chrome.storage.local.set({ activeTask: task });

      const targetUrl = getTargetUrl(task);
      const tab = await chrome.tabs.create({ url: targetUrl, active: true });
      activeTabId = tab.id;
      console.log(`[PostPilot] Opened tab ${tab.id}: ${targetUrl}`);
    } else {
      console.log(`[PostPilot] No tasks — waiting...`);
      isProcessingTask = false;
      activeTaskId = null;
      activeTabId = null;
      scheduleNext();
    }
  } catch (err) {
    console.error(`[PostPilot] Poll error:`, err);
    isProcessingTask = false;
    activeTaskId = null;
    activeTabId = null;
    scheduleNext();
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  LISTEN FOR CONTENT SCRIPT COMPLETION
// ═══════════════════════════════════════════════════════════════════════════════

chrome.storage.onChanged.addListener(async (changes, area) => {
  if (area !== "local" || !changes.taskResult) return;

  const result = changes.taskResult.newValue;
  console.log(`[PostPilot] Task result:`, result);

  try {
    if (result.taskId) {
      await apiPost(`/api/cleanup-task/${result.taskId}`);
      console.log(`[PostPilot] Cleanup done for task #${result.taskId}`);
    }
  } catch (e) {
    console.error(`[PostPilot] Cleanup failed:`, e);
  }

  if (activeTabId) {
    try {
      await chrome.tabs.remove(activeTabId);
      console.log(`[PostPilot] Closed tab ${activeTabId}`);
    } catch (_) { /* tab may already be closed */ }
    activeTabId = null;
  }

  await chrome.storage.local.remove(["activeTask", "taskResult"]);
  isProcessingTask = false;
  activeTaskId = null;
  scheduleNext();
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

chrome.runtime.onInstalled.addListener(() => {
  console.log(`[PostPilot] Installed — starting...`);
  setTimeout(pollLoop, 5000);
});

chrome.runtime.onStartup.addListener(() => {
  console.log(`[PostPilot] Started — starting...`);
  setTimeout(pollLoop, 5000);
});

setTimeout(pollLoop, 5000);

console.log(`[PostPilot] Background initialized`);