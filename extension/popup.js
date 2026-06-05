document.addEventListener("DOMContentLoaded", async () => {
  const vpsUrl = document.getElementById("vpsUrl");
  const profileId = document.getElementById("profileId");
  const platform = document.getElementById("platform");
  const saveBtn = document.getElementById("saveBtn");
  const statusText = document.getElementById("statusText");
  const statusDot = document.getElementById("statusDot");

  // Load saved config
  const stored = await chrome.storage.local.get([
    "vpsConfig",
    "profileId",
    "platform",
    "activeTask",
  ]);

  const cfg = stored.vpsConfig || {};
  vpsUrl.value = cfg.vps_base_url || "http://localhost:8000";
  profileId.value = String(stored.profileId || cfg.profile_id || 1);
  platform.value = stored.platform || cfg.platform || "x";

  // Show current status
  if (stored.activeTask) {
    statusText.textContent = `Processing task #${stored.activeTask.id} (${stored.activeTask.task_type})`;
    statusDot.className = "dot";
  } else {
    statusText.textContent = "Idle — waiting for tasks";
    statusDot.className = "dot idle";
  }

  // Save handler
  saveBtn.addEventListener("click", async () => {
    const config = {
      vps_base_url: vpsUrl.value.trim(),
      profile_id: parseInt(profileId.value, 10),
      platform: platform.value,
    };

    // Save to both vpsConfig and individual keys for background.js
    await chrome.storage.local.set({
      vpsConfig: config,
      profileId: config.profile_id,
      platform: config.platform,
    });

    statusText.textContent = "Saved! Restarting poll...";
    statusDot.className = "dot";

    // Reload background service worker to pick up new config
    chrome.runtime.reload();

    setTimeout(() => {
      statusText.textContent = "Config saved ✓";
    }, 1500);
  });
});