"""
PostPilot - Playwright Automation Engine
Async worker that posts content to X (Twitter) and TikTok via persistent
browser contexts, using stealth techniques to avoid detection.
"""

import os
import random
import asyncio

from playwright.async_api import async_playwright, BrowserContext, Page

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _gaussian_delay(mean: float = 2.5, stddev: float = 1.0) -> float:
    """
    Return a random delay sampled from a Gaussian distribution,
    clamped to a positive value.  Used instead of static sleeps.
    """
    delay = random.gauss(mean, stddev)
    return max(0.3, delay)


def _stealth_args() -> list:
    """Browser arguments that reduce automation fingerprinting."""
    return [
        "--disable-blink-features=AutomationControlled",
        "--disable-automation",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-component-update",
        "--disable-sync",
        "--disable-default-apps",
        "--disable-background-networking",
        f"--window-size={random.randint(1280, 1400)},{random.randint(720, 900)}",
    ]


def _viewport() -> dict:
    """Return a randomised but realistic viewport."""
    return {
        "width": random.randint(1280, 1400),
        "height": random.randint(720, 900),
    }


async def _human_type(page: Page, selector: str, text: str, delay_mean: float = 0.08):
    """Type text into an element with human-like per-character delays."""
    await page.click(selector)
    await asyncio.sleep(_gaussian_delay(0.3, 0.1))
    for char in text:
        await page.keyboard.type(char, delay=random.gauss(delay_mean, 0.03))


async def _random_scroll(page: Page):
    """Simulate a human-like small scroll."""
    delta = random.randint(-200, 200)
    await page.evaluate(f"window.scrollBy(0, {delta})")
    await asyncio.sleep(_gaussian_delay(0.5, 0.2))


# ─── Context Factory ─────────────────────────────────────────────────────────

async def create_context(playwright, profile_dir: str, proxy_string: str = "") -> BrowserContext:
    """
    Launch a persistent browser context with a stored profile directory.
    If *proxy_string* is non-empty (format: http://user:pass@ip:port),
    the context will route through that proxy.
    """
    proxy_settings = None
    if proxy_string:
        # Parse "http://user:pass@ip:port" into Playwright's proxy format
        try:
            from urllib.parse import urlparse
            parsed = urlparse(proxy_string)
            auth = parsed.netloc.split("@")[0] if "@" in parsed.netloc else ""
            host_port = parsed.netloc.split("@")[-1] if "@" in parsed.netloc else parsed.netloc
            user, pwd = auth.split(":", 1) if ":" in auth else ("", "")
            proxy_settings = {
                "server": f"{parsed.scheme}://{host_port}",
                "username": user,
                "password": pwd,
            }
        except Exception as exc:
            print(f"[Automation] Failed to parse proxy '{proxy_string}': {exc}")

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=False,  # headless is more detectable; we run visible
        args=_stealth_args(),
        viewport=_viewport(),
        proxy=proxy_settings,
        ignore_https_errors=True,
        locale="en-US",
        timezone_id="America/New_York",
    )
    # Inject stealth JS that overrides navigator.webdriver
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        window.chrome = { runtime: {} };
    """)
    return context


# ─── X (Twitter) Poster ──────────────────────────────────────────────────────

async def post_to_x(context: BrowserContext, caption: str, media_path: str = "") -> str:
    """
    Post content to X.com using the given persistent context.
    Returns the post URL/id on success, or raises an exception.
    """
    page = await context.new_page()
    post_id = ""
    try:
        # Navigate to compose
        await page.goto("https://x.com/compose/post", wait_until="networkidle")
        await asyncio.sleep(_gaussian_delay(2.0, 0.5))

        # Check if we're logged in
        page_url = page.url
        if "login" in page_url.lower() or "i/flow" in page_url:
            raise PermissionError("Session appears logged out — needs authentication")

        # Click on the tweet compose area
        await _random_scroll(page)
        await asyncio.sleep(_gaussian_delay(0.5, 0.2))

        # Type the caption
        if caption:
            # X uses contenteditable div with aria-label "Post text"
            editor_sel = '[data-testid="tweetTextarea_0"]'
            await page.wait_for_selector(editor_sel, timeout=15000)
            await _human_type(page, editor_sel, caption)

        # Upload media if provided
        if media_path and os.path.isfile(media_path):
            await asyncio.sleep(_gaussian_delay(0.8, 0.3))
            # File input for media on X
            file_input_sel = 'input[data-testid="fileInput"]'
            await page.wait_for_selector(file_input_sel, timeout=10000)
            await page.set_input_files(file_input_sel, media_path)
            print(f"[X] Media attached: {os.path.basename(media_path)}")
            # Wait for upload preview to appear
            await asyncio.sleep(_gaussian_delay(3.0, 1.0))

        # Click the Post button
        await asyncio.sleep(_gaussian_delay(0.5, 0.2))
        post_btn = '[data-testid="tweetButton"]'
        await page.wait_for_selector(post_btn, timeout=10000)

        # Human-like hover before clicking
        box = await page.locator(post_btn).bounding_box()
        if box:
            x_off = random.uniform(5, box["width"] - 5)
            y_off = random.uniform(5, box["height"] - 5)
            await page.mouse.move(box["x"] + x_off, box["y"] + y_off)
            await asyncio.sleep(_gaussian_delay(0.3, 0.1))

        await page.click(post_btn)

        # Wait for post to succeed (URL changes away from /compose/post)
        try:
            await page.wait_for_url(lambda u: "/compose/post" not in u, timeout=30000)
        except Exception:
            # If still on compose, maybe the post failed silently
            pass

        post_id = page.url.split("/")[-1] if page.url else "unknown"
        print(f"[X] Posted successfully: {page.url}")
        return post_id

    except PermissionError:
        raise
    except Exception as exc:
        print(f"[X] Post failed: {exc}")
        # Take a screenshot for debugging
        try:
            screenshot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug")
            os.makedirs(screenshot_dir, exist_ok=True)
            await page.screenshot(path=os.path.join(screenshot_dir, "x_failure.png"))
        except Exception:
            pass
        raise
    finally:
        await page.close()


# ─── TikTok Poster ───────────────────────────────────────────────────────────

async def post_to_tiktok(context: BrowserContext, caption: str, media_path: str = "") -> str:
    """
    Post a video to TikTok Creator Center using the given persistent context.
    Returns a status string on success, or raises an exception.
    """
    page = await context.new_page()
    result = ""
    try:
        # Navigate to Creator Center upload
        await page.goto("https://www.tiktok.com/upload/", wait_until="networkidle")
        await asyncio.sleep(_gaussian_delay(2.5, 0.5))

        # Check login
        if "login" in page.url.lower():
            raise PermissionError("Session appears logged out — needs authentication")

        # Upload video file via file input
        if media_path and os.path.isfile(media_path):
            file_input_sel = 'input[type="file"]'
            await page.wait_for_selector(file_input_sel, timeout=15000)
            await page.set_input_files(file_input_sel, media_path)
            print(f"[TikTok] Video attached: {os.path.basename(media_path)}")

            # Wait for upload progress bar to complete
            # TikTok shows a progress bar inside the upload container
            await asyncio.sleep(_gaussian_delay(3.0, 1.0))
            try:
                # Wait for progress bar to disappear (upload complete)
                progress_sel = '[class*="progress"]'
                await page.wait_for_function(
                    f"!document.querySelector('{progress_sel}') || "
                    f"document.querySelector('{progress_sel}').style.width === '100%'",
                    timeout=120000,
                )
            except Exception:
                print("[TikTok] Progress bar timeout — continuing anyway")
        else:
            print("[TikTok] No media path provided — TikTok requires a video")

        # Enter caption
        if caption:
            await _random_scroll(page)
            await asyncio.sleep(_gaussian_delay(0.5, 0.2))
            # TikTok caption textarea
            caption_sel = 'div[contenteditable="true"]'
            try:
                await page.wait_for_selector(caption_sel, timeout=10000)
                await _human_type(page, caption_sel, caption)
            except Exception:
                print("[TikTok] Caption input not found — skipping")

        # Click Post button
        await asyncio.sleep(_gaussian_delay(1.0, 0.3))
        post_btn = 'button:has-text("Post")'
        try:
            await page.wait_for_selector(post_btn, timeout=15000)
            await page.click(post_btn)
            print("[TikTok] Post button clicked")
        except Exception as exc:
            raise RuntimeError(f"Could not find TikTok Post button: {exc}")

        # Wait a moment for post to go through
        await asyncio.sleep(_gaussian_delay(3.0, 1.0))
        result = "posted"
        print("[TikTok] Video posted successfully")
        return result

    except PermissionError:
        raise
    except Exception as exc:
        print(f"[TikTok] Post failed: {exc}")
        try:
            screenshot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug")
            os.makedirs(screenshot_dir, exist_ok=True)
            await page.screenshot(path=os.path.join(screenshot_dir, "tiktok_failure.png"))
        except Exception:
            pass
        raise
    finally:
        await page.close()


# ─── Master Dispatch ──────────────────────────────────────────────────────────

async def post_to_platform(
    platform: str,
    profile_dir: str,
    proxy_string: str,
    caption: str,
    media_path: str = "",
) -> str:
    """
    High-level dispatcher: launches a persistent context, posts to
    *platform*, and returns the post result.
    """
    async with async_playwright() as pw:
        ctx = await create_context(pw, profile_dir, proxy_string)
        try:
            if platform.upper() == "X":
                return await post_to_x(ctx, caption, media_path)
            elif platform.upper() == "TIKTOK":
                return await post_to_tiktok(ctx, caption, media_path)
            else:
                raise ValueError(f"Unsupported platform: {platform}")
        finally:
            await ctx.close()
