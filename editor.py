"""
PostPilot - Media Processing Engine
Strips metadata and applies microscopic transformations via FFmpeg
to bypass platform duplicate-detection heuristics.
"""

import os
import subprocess
import uuid
import shutil

STAGING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "staged")
os.makedirs(STAGING_DIR, exist_ok=True)


def _ffmpeg_available() -> bool:
    """Check whether ffmpeg is on the system PATH."""
    return shutil.which("ffmpeg") is not None


def process_media(source_path: str, output_dir: str = None) -> str:
    """
    Process a media file through FFmpeg to strip metadata and alter its
    fingerprint subtly:
        - Strip all metadata (-map_metadata -1)
        - Scale up by 1.5% (minimal, visually imperceptible)
        - Mirror horizontally
        - Remove global headers and timestamps

    Returns the path to the processed file in the staging directory.
    Raises RuntimeError if ffmpeg is unavailable or the command fails.
    """
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"Source file not found: {source_path}")

    if not _ffmpeg_available():
        raise RuntimeError(
            "FFmpeg is not installed or not found on PATH. "
            "Install it via 'brew install ffmpeg' (macOS), "
            "'apt install ffmpeg' (Debian/Ubuntu), or download from ffmpeg.org."
        )

    output_dir = output_dir or STAGING_DIR
    os.makedirs(output_dir, exist_ok=True)

    ext = os.path.splitext(source_path)[1] or ".mp4"
    output_name = f"pp_{uuid.uuid4().hex[:12]}{ext}"
    output_path = os.path.join(output_dir, output_name)

    # Determine if it's a video or image
    is_video = ext.lower() in (".mp4", ".mov", ".avi", ".mkv", ".webm")

    cmd = [
        "ffmpeg", "-y",
        "-i", source_path,
        "-map_metadata", "-1",           # strip all metadata
        "-metadata", "title=",
        "-metadata", "comment=",
        "-metadata", "description=",
    ]

    if is_video:
        cmd.extend([
            "-vf", "scale=iw*1.015:ih*1.015,hflip",   # 1.5% scale-up + horizontal mirror
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-map_metadata", "-1",
            "-fflags", "+bitexact",
            "-flags:v", "+bitexact",
            "-flags:a", "+bitexact",
        ])
    else:
        # Image processing
        cmd.extend([
            "-vf", "scale=iw*1.015:ih*1.015,hflip",
            "-q:v", "2",
        ])

    cmd.append(output_path)

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg processing failed:\n{result.stderr}")

    print(f"[Editor] Processed: {os.path.basename(source_path)} -> {os.path.basename(output_path)}")
    return output_path
