/**
 * PostPilot Extension — Content Script
 *
 * Injected into X, TikTok, and Instagram pages.  Reads the current task from
 * chrome.storage.local, executes the DOM automation, and writes the result
 * back so background.js can clean up.
 */

console.log("[PostPilot] Content script loaded");

// ═══════════════════════════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════════════════════════

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function randomBetween(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

// ═══════════════════════════════════════════════════════════════════════════════
//  TYPE A — INTERACT (Human Mimicry)
// ═══════════════════════════════════════════════════════════════════════════════

async function handleInteract(platform) {
  console.log(`[PostPilot] Interacting on ${platform}...`);

  // Smooth scroll down with human-like pauses
  const scrollSteps = randomBetween(3, 6);
  for (let i = 0; i < scrollSteps; i++) {
    const px = randomBetween(300, 800);
    window.scrollBy({ top: px, behavior: "smooth" });
    await sleep(randomBetween(2000, 5000));
  }

  // Pick 1–2 posts and click Like button
  const likeSelectors = {
    x: `div[data-testid="like"]`,
    tiktok: `button[data-e2e="like-icon"]`,
    instagram: `svg[aria-label="Like"]`,
  };

  const selector = likeSelectors[platform] || likeSelectors.x;
  const buttons = document.querySelectorAll(selector);
  console.log(`[PostPilot] Found ${buttons.length} like buttons`);

  const toClick = Math.min(randomBetween(1, 2), buttons.length);
  for (let i = 0; i < toClick; i++) {
    try {
      const idx = randomBetween(0, buttons.length - 1);
      // Scroll button into view
      buttons[idx].scrollIntoView({ behavior: "smooth", block: "center" });
      await sleep(randomBetween(500, 1500));
      buttons[idx].click();
      console.log(`[PostPilot] Clicked like #${idx + 1}`);
      await sleep(randomBetween(3000, 8000));
    } catch (e) {
      console.warn(`[PostPilot] Like click error:`, e);
    }
  }

  // Spend 1–3 minutes idling (watching content)
  const idleMs = randomBetween(60 * 1000, 180 * 1000);
  console.log(`[PostPilot] Idling for ${Math.round(idleMs / 1000)}s...`);
  await sleep(idleMs);
}

// ═══════════════════════════════════════════════════════════════════════════════
//  TYPE B — PUBLISH (Native Upload Injection)
// ═══════════════════════════════════════════════════════════════════════════════

async function handlePublish(task) {
  const platform = task.platform;
  const videoUrl = `${CONFIG_VPS_BASE_URL}${task.video_url}`;
  const caption = task.caption || "";

  console.log(`[PostPilot] Publishing to ${platform}: ${videoUrl}`);

  // Fetch the video as a Blob
  let blob;
  try {
    const resp = await fetch(videoUrl);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    blob = await resp.blob();
    console.log(`[PostPilot] Downloaded video blob (${blob.size} bytes)`);
  } catch (e) {
    console.error(`[PostPilot] Failed to fetch video:`, e);
    return { error: `Video fetch failed: ${e.message}` };
  }

  const file = new File([blob], "post.mp4", { type: blob.type || "video/mp4" });

  switch (platform) {
    case "x":
      await publishToX(file, caption);
      break;
    case "tiktok":
      await publishToTikTok(file, caption);
      break;
    case "instagram":
      await publishToInstagram(file, caption);
      break;
    default:
      console.error(`[PostPilot] Unknown platform: ${platform}`);
  }
}

// ─── X (Twitter) ─────────────────────────────────────────────────────────────

async function publishToX(file, caption) {
  console.log("[PostPilot] Publishing to X...");

  // 1. Inject file into the hidden file input
  const fileInput = document.querySelector(`input[data-testid="fileInput"]`);
  if (!fileInput) throw new Error("X file input not found");
  await injectFile(fileInput, file);

  // Wait for upload to process
  console.log("[PostPilot] Waiting for X upload processing...");
  await sleep(5000);

  // 2. Insert caption text
  if (caption) {
    const textArea = document.querySelector(
      `div[data-testid="tweetTextarea_0"]`
    );
    if (textArea) {
      textArea.focus();
      document.execCommand("insertText", false, caption);
      await sleep(1000);
    }
  }

  // 3. Click Post button
  const postBtn = document.querySelector(`div[data-testid="tweetButtonInline"]`);
  if (postBtn) {
    await sleep(1000);
    postBtn.click();
    console.log("[PostPilot] X post submitted");
  }

  // Wait for confirmation or fail
  await sleep(10000);
}

// ─── TikTok ──────────────────────────────────────────────────────────────────

async function publishToTikTok(file, caption) {
  console.log("[PostPilot] Publishing to TikTok...");

  // 1. Inject file
  const fileInput = document.querySelector(`input[type="file"]`);
  if (!fileInput) throw new Error("TikTok file input not found");
  await injectFile(fileInput, file);

  // Wait for upload & processing
  console.log("[PostPilot] Waiting for TikTok upload processing...");
  await sleep(15000);

  // 2. Insert caption
  if (caption) {
    const captionDiv = document.querySelector(
      `div[contenteditable="true"], div[class*="public-DraftEditor-content"]`
    );
    if (captionDiv) {
      captionDiv.focus();
      document.execCommand("insertText", false, caption);
      await sleep(2000);
    } else {
      console.warn("[PostPilot] TikTok caption area not found");
    }
  }

  // 3. Click Post button
  // TikTok's Post button contains "Post" text — look for the button
  const allButtons = document.querySelectorAll("button");
  let postBtn = null;
  for (const btn of allButtons) {
    if (btn.textContent.trim().toLowerCase() === "post") {
      postBtn = btn;
      break;
    }
  }
  if (postBtn) {
    await sleep(2000);
    postBtn.click();
    console.log("[PostPilot] TikTok post submitted");
  } else {
    console.warn("[PostPilot] TikTok Post button not found");
  }

  await sleep(10000);
}

// ─── Instagram Reels ─────────────────────────────────────────────────────────

async function publishToInstagram(file, caption) {
  console.log("[PostPilot] Publishing to Instagram...");

  // 1. Click "New Post" button to open the modal
  const newPostIcon = document.querySelector(`svg[aria-label="New post"]`);
  if (newPostIcon) {
    const createBtn = newPostIcon.closest("button") || newPostIcon.parentElement;
    if (createBtn) {
      createBtn.click();
      await sleep(3000);
    }
  }

  // 2. Inject file into modal's file input
  const fileInput = document.querySelector(`input[type="file"]`);
  if (!fileInput) throw new Error("Instagram file input not found");
  await injectFile(fileInput, file);

  // Wait for video parse
  console.log("[PostPilot] Waiting for Instagram video parse...");
  await sleep(8000);

  // 3. Click "Next"
  const nextButtons = document.querySelectorAll(
    `button:not([disabled])`
  );
  let nextBtn = null;
  for (const btn of nextButtons) {
    if (btn.textContent.trim().toLowerCase() === "next") {
      nextBtn = btn;
      break;
    }
  }
  if (nextBtn) {
    nextBtn.click();
    await sleep(5000);
  }

  // 4. Insert caption
  if (caption) {
    const captionArea = document.querySelector(
      `textarea[aria-label="Write a caption..."]`
    );
    if (captionArea) {
      captionArea.focus();
      captionArea.value = caption;
      captionArea.dispatchEvent(new Event("input", { bubbles: true }));
      await sleep(2000);
    }
  }

  // 5. Click final "Share" button
  const shareBtn = findButtonByText("Share");
  if (shareBtn) {
    await sleep(1500);
    shareBtn.click();
    console.log("[PostPilot] Instagram post submitted");
  } else {
    console.warn("[PostPilot] Instagram Share button not found");
  }

  await sleep(10000);
}

// ─── File Injection Utility ──────────────────────────────────────────────────

async function injectFile(inputElement, file) {
  const dt = new DataTransfer();
  dt.items.add(file);
  Object.defineProperty(inputElement, "files", {
    value: dt.files,
    writable: false,
  });
  inputElement.dispatchEvent(new Event("change", { bubbles: true }));
  console.log(`[PostPilot] Injected file: ${file.name}`);
}

function findButtonByText(text) {
  const lower = text.toLowerCase();
  const allButtons = document.querySelectorAll("button, div[role='button']");
  for (const el of allButtons) {
    if (el.textContent.trim().toLowerCase() === lower) return el;
  }
  return null;
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MAIN EXECUTION
// ═══════════════════════════════════════════════════════════════════════════════

(async function main() {
  try {
    // Retrieve VPS base URL from storage (set by background.js config fetch)
    const stored = await chrome.storage.local.get(["vpsConfig"]);
    window.CONFIG_VPS_BASE_URL =
      (stored.vpsConfig && stored.vpsConfig.vps_base_url) ||
      "http://localhost:8000";

    // Read the active task
    const { activeTask } = await chrome.storage.local.get(["activeTask"]);
    if (!activeTask) {
      console.log("[PostPilot] No active task — content script idle");
      return;
    }

    console.log(`[PostPilot] Executing task #${activeTask.id}:`, activeTask);

    if (activeTask.task_type === "interact") {
      await handleInteract(activeTask.platform);
    } else if (activeTask.task_type === "publish") {
      await handlePublish(activeTask);
    } else {
      console.warn(`[PostPilot] Unknown task type: ${activeTask.task_type}`);
    }

    // Signal completion
    await chrome.storage.local.set({
      taskResult: {
        taskId: activeTask.id,
        status: "completed",
        platform: activeTask.platform,
      },
    });

    console.log(`[PostPilot] Task #${activeTask.id} completed ✅`);
  } catch (err) {
    console.error(`[PostPilot] Content script error:`, err);

    // Try to signal failure
    try {
      const { activeTask } = await chrome.storage.local.get(["activeTask"]);
      if (activeTask) {
        await chrome.storage.local.set({
          taskResult: {
            taskId: activeTask.id,
            status: "error",
            error: err.message,
          },
        });
      }
    } catch (e) {
      console.error("[PostPilot] Could not signal error:", e);
    }
  }
})();