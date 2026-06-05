/**
 * PostPilot Extension — Content Script
 *
 * Injected into X, TikTok, and Instagram pages.  Reads the current task from
 * chrome.storage.local and executes either:
 *
 *   MODULE A — "interact" : Human mimicry scrolling + random likes
 *   MODULE B — "publish"  : Native file-picker injection + caption + post
 *
 * Every selector is wrapped in try/catch for clear console logging if a
 * platform changes its UI classes.
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

/**
 * Safe querySelector wrapper — logs a warning and returns null instead of
 * throwing if the element isn't found.
 */
function qs(selector, ctx) {
  const root = ctx || document;
  try {
    return root.querySelector(selector);
  } catch (e) {
    console.warn(`[PostPilot] Invalid selector "${selector}":`, e);
    return null;
  }
}

function qsa(selector, ctx) {
  const root = ctx || document;
  try {
    return root.querySelectorAll(selector);
  } catch (e) {
    console.warn(`[PostPilot] Invalid selector "${selector}":`, e);
    return [];
  }
}

/**
 * Locate a button whose trimmed lowercase text exactly matches the given string.
 */
function findButtonByText(text) {
  const lower = text.toLowerCase();
  const all = document.querySelectorAll("button, div[role='button'], a[role='button']");
  for (const el of all) {
    try {
      if (el.textContent.trim().toLowerCase() === lower) return el;
    } catch (_) { /* skip */ }
  }
  return null;
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MODULE A — INTERACT (Human Mimicry)
// ═══════════════════════════════════════════════════════════════════════════════

async function handleInteract(platform) {
  console.log(`[PostPilot] Interacting on ${platform}...`);

  const likeSelectors = {
    x: `div[data-testid="like"]`,
    tiktok: `span[data-e2e="like-icon"], svg[class*="Like"]`,
    instagram: `svg[aria-label="Like"]`,
  };

  const sessionDuration = randomBetween(90, 240); // seconds
  const sessionStart = Date.now();
  const sessionEnd = sessionStart + sessionDuration * 1000;

  console.log(`[PostPilot] Session: ${sessionDuration}s (until ${new Date(sessionEnd).toLocaleTimeString()})`);

  // Human scroll loop — runs until session time expires
  let iteration = 0;
  while (Date.now() < sessionEnd) {
    iteration++;

    // Randomised scroll with human-like up/down micro-adjustments
    const scrollDown = randomBetween(300, 700);
    const scrollUp = randomBetween(30, 120);
    window.scrollBy({ top: scrollDown, behavior: "smooth" });
    await sleep(randomBetween(1500, 3500));
    window.scrollBy({ top: -scrollUp, behavior: "smooth" });
    await sleep(randomBetween(500, 1200));
    window.scrollBy({ top: randomBetween(200, 500), behavior: "smooth" });

    // Pause and "read" the content
    const pause = randomBetween(3000, 7000);
    await sleep(pause);

    // 20% chance: find a visible Like button and click it
    if (Math.random() < 0.20) {
      const selector = likeSelectors[platform] || likeSelectors.x;
      const likeButtons = qsa(selector);
      const visible = Array.from(likeButtons).filter((btn) => {
        try {
          const rect = btn.getBoundingClientRect();
          return rect.top >= 0 && rect.bottom <= window.innerHeight;
        } catch (_) {
          return false;
        }
      });

      if (visible.length > 0) {
        const target = visible[randomBetween(0, visible.length - 1)];
        try {
          // For Instagram, click the parent button, not the SVG itself
          let clickEl = target;
          if (platform === "instagram" && target.tagName === "svg") {
            clickEl = target.closest("button") || target.parentElement || target;
          }
          clickEl.scrollIntoView({ behavior: "smooth", block: "center" });
          await sleep(randomBetween(400, 1200));
          clickEl.click();
          console.log(`[PostPilot] ❤️ Liked a post (iter ${iteration})`);

          // Wait extra after liking to seem human
          await sleep(randomBetween(4000, 10000));
        } catch (e) {
          console.warn(`[PostPilot] Like click failed:`, e);
        }
      } else {
        console.log(`[PostPilot] No visible like buttons (iter ${iteration})`);
      }
    }

    // Time check
    const remaining = Math.round((sessionEnd - Date.now()) / 1000);
    if (remaining > 0) {
      console.log(`[PostPilot] ${remaining}s remaining in session...`);
    }
  }

  console.log(`[PostPilot] Interact session complete (${sessionDuration}s)`);
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MODULE B — PUBLISH (Native Upload Injection)
// ═══════════════════════════════════════════════════════════════════════════════

async function handlePublish(task) {
  const platform = task.platform;
  const videoUrl = `${window.CONFIG_VPS_BASE_URL}${task.video_url}`;
  const caption = task.caption || "";

  console.log(`[PostPilot] Publishing to ${platform}: ${videoUrl}`);

  // Fetch video as Blob
  let blob;
  try {
    const resp = await fetch(videoUrl);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    blob = await resp.blob();
    console.log(`[PostPilot] Downloaded video (${blob.size} bytes)`);
  } catch (e) {
    console.error(`[PostPilot] Video fetch failed:`, e);
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

// ─── File Injection Utility ──────────────────────────────────────────────────

async function injectFile(inputElement, file) {
  try {
    const dt = new DataTransfer();
    dt.items.add(file);
    Object.defineProperty(inputElement, "files", {
      value: dt.files,
      writable: false,
    });
    inputElement.dispatchEvent(new Event("change", { bubbles: true }));
    console.log(`[PostPilot] Injected file: ${file.name}`);
  } catch (e) {
    console.error(`[PostPilot] File injection failed:`, e);
    throw e;
  }
}

// ─── X (Twitter) ─────────────────────────────────────────────────────────────

async function publishToX(file, caption) {
  console.log("[PostPilot] Publishing to X...");

  try {
    // 1. Inject file
    const fileInput = qs(`input[data-testid="fileInput"]`);
    if (!fileInput) throw new Error("X fileInput not found");
    await injectFile(fileInput, file);

    // Wait for upload
    console.log("[PostPilot] Waiting for X upload...");
    await sleep(5000);

    // 2. Insert caption
    if (caption) {
      const textArea = qs(`div[data-testid="tweetTextarea_0"]`);
      if (textArea) {
        textArea.focus();
        document.execCommand("insertText", false, caption);
        await sleep(1000);
      } else {
        console.warn("[PostPilot] X textarea not found");
      }
    }

    // 3. Click Post
    const postBtn = qs(`div[data-testid="tweetButtonInline"]`);
    if (postBtn) {
      await sleep(1000);
      postBtn.click();
      console.log("[PostPilot] X post submitted ✅");
    } else {
      console.warn("[PostPilot] X Post button not found");
    }

    await sleep(10000);
  } catch (e) {
    console.error(`[PostPilot] X publish error:`, e);
    throw e;
  }
}

// ─── TikTok ──────────────────────────────────────────────────────────────────

async function publishToTikTok(file, caption) {
  console.log("[PostPilot] Publishing to TikTok...");

  try {
    // 1. Inject file
    const fileInput = qs(`input[type="file"]`);
    if (!fileInput) throw new Error("TikTok file input not found");
    await injectFile(fileInput, file);

    // Wait for upload + video parsing
    console.log("[PostPilot] Waiting for TikTok upload processing...");
    await sleep(15000);

    // 2. Insert caption
    if (caption) {
      const captionDiv = qs(
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
    const postBtn = findButtonByText("Post");
    if (postBtn) {
      await sleep(2000);
      postBtn.click();
      console.log("[PostPilot] TikTok post submitted ✅");
    } else {
      console.warn("[PostPilot] TikTok 'Post' button not found");
    }

    await sleep(10000);
  } catch (e) {
    console.error(`[PostPilot] TikTok publish error:`, e);
    throw e;
  }
}

// ─── Instagram Reels ─────────────────────────────────────────────────────────

async function publishToInstagram(file, caption) {
  console.log("[PostPilot] Publishing to Instagram...");

  try {
    // 1. Click "New Post" icon to open the creation modal
    const newPostSvg = qs(`svg[aria-label="New post"]`);
    if (newPostSvg) {
      const createBtn = newPostSvg.closest("button") || newPostSvg.parentElement;
      if (createBtn) {
        createBtn.click();
        console.log("[PostPilot] Clicked 'New Post' icon");
        await sleep(3000);
      } else {
        throw new Error("Instagram New Post button parent not found");
      }
    } else {
      throw new Error("Instagram New Post icon not found");
    }

    // 2. Inject file into modal file input
    const fileInput = qs(`input[type="file"]`);
    if (!fileInput) throw new Error("Instagram file input not found");
    await injectFile(fileInput, file);

    // Wait for video processing
    console.log("[PostPilot] Waiting for Instagram video parse...");
    await sleep(4000);

    // 3. Click "Next" (first time — crop/edit screen)
    let nextBtn = findButtonByText("Next");
    if (nextBtn) {
      nextBtn.click();
      console.log("[PostPilot] Clicked Next (1/2)");
      await sleep(5000);
    } else {
      console.warn("[PostPilot] Instagram Next button (1) not found");
    }

    // 4. Click "Next" (second time — details screen)
    nextBtn = findButtonByText("Next");
    if (nextBtn) {
      nextBtn.click();
      console.log("[PostPilot] Clicked Next (2/2)");
      await sleep(3000);
    } else {
      console.warn("[PostPilot] Instagram Next button (2) not found");
    }

    // 5. Insert caption
    if (caption) {
      const captionArea = qs(`textarea[aria-label="Write a caption..."]`);
      if (captionArea) {
        captionArea.focus();
        document.execCommand("insertText", false, caption);
        await sleep(2000);
      } else {
        console.warn("[PostPilot] Instagram caption area not found");
      }
    }

    // 6. Click final "Share" button
    const shareBtn = findButtonByText("Share");
    if (shareBtn) {
      await sleep(1500);
      shareBtn.click();
      console.log("[PostPilot] Instagram post submitted ✅");
    } else {
      console.warn("[PostPilot] Instagram 'Share' button not found");
    }

    await sleep(10000);
  } catch (e) {
    console.error(`[PostPilot] Instagram publish error:`, e);
    throw e;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MAIN EXECUTION
// ═══════════════════════════════════════════════════════════════════════════════

(async function main() {
  try {
    const stored = await chrome.storage.local.get(["vpsConfig"]);
    window.CONFIG_VPS_BASE_URL =
      (stored.vpsConfig && stored.vpsConfig.vps_base_url) ||
      "http://localhost:8000";

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