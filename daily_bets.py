import glob
import os
import shutil
from datetime import datetime, timedelta

import cv2
import yt_dlp

# ==========================================================
# Configuration
# ==========================================================

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLfzUuO_R9acDwEZFY8icK2It16sanH5Hy"

VIDEO_NAME = "latest_video"

TEMPLATE_FILE = "template.png"

OUTPUT_FILE = "todays_bets.png"

START_AT_PERCENT = 0.40      # Skip first 40% of video
FRAME_INTERVAL = 1           # seconds between frames
MATCH_THRESHOLD = 0.92

# Crop around the detected template
LEFT_PADDING = 40
TOP_PADDING = 40
OUTPUT_WIDTH = 900
OUTPUT_HEIGHT = 550

# Cache settings
CACHE_DAYS_TO_KEEP = 7


# ==========================================================
# Cache cleanup
# ==========================================================

def cleanup_old_caches():
    cutoff = datetime.now() - timedelta(days=CACHE_DAYS_TO_KEEP)

    for file in glob.glob("cache_*.png"):

        try:
            modified_time = datetime.fromtimestamp(
                os.path.getmtime(file)
            )

            if modified_time < cutoff:
                os.remove(file)
                print(f"Removed old cache: {file}")

        except OSError:
            pass


# ==========================================================
# Check daily cache
# ==========================================================

today = datetime.now().strftime("%Y-%m-%d")
CACHE_FILE = f"cache_{today}.png"

cleanup_old_caches()

if os.path.exists(CACHE_FILE):

    print(f"Using cached image: {CACHE_FILE}")

    if CACHE_FILE != OUTPUT_FILE:
        shutil.copy(CACHE_FILE, OUTPUT_FILE)

    print("Done.")
    exit(0)


print("No cache found. Generating today's bets image...")


# ==========================================================
# Remove old download
# ==========================================================

for file in glob.glob(f"{VIDEO_NAME}.*"):
    try:
        os.remove(file)
    except OSError:
        pass


# ==========================================================
# Download latest video only
# ==========================================================

print("Downloading latest Daily Juice episode...")

ydl_opts = {
    "playlist_items": "1",
    "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
    "outtmpl": f"{VIDEO_NAME}.%(ext)s",
    "quiet": False,
    "ignoreerrors": True,
    "cookiefile": "/etc/secrets/cookies.txt",
    "no_cookie_jar": True,
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    ydl.download([PLAYLIST_URL])


# ==========================================================
# Locate downloaded file
# ==========================================================

video_file = None

for file in glob.glob(f"{VIDEO_NAME}.*"):
    if not file.endswith(".part"):
        video_file = file
        break

if video_file is None:
    raise Exception("Video download failed.")


print(f"\nUsing video: {video_file}")


# ==========================================================
# Load template
# ==========================================================

template = cv2.imread(TEMPLATE_FILE)

if template is None:
    raise Exception(
        "Couldn't find template.png\n"
        "Create a crop of the orange TODAY'S BETS header."
    )

template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)


# ==========================================================
# Open video
# ==========================================================

cap = cv2.VideoCapture(video_file)

fps = cap.get(cv2.CAP_PROP_FPS)
frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

start_frame = int(frame_count * START_AT_PERCENT)

cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

frame_skip = int(fps * FRAME_INTERVAL)

current_frame = start_frame

print("\nSearching for Today's Bets graphic...\n")


# ==========================================================
# Search
# ==========================================================

found = False

while True:

    cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)

    success, frame = cap.read()

    if not success:
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    result = cv2.matchTemplate(
        gray,
        template,
        cv2.TM_CCOEFF_NORMED
    )

    _, score, _, location = cv2.minMaxLoc(result)

    timestamp = current_frame / fps

    print(f"{timestamp:7.1f}s  score={score:.3f}")

    if score >= MATCH_THRESHOLD:

        print("\nFOUND!\n")

        x, y = location

        x = max(0, x - LEFT_PADDING)
        y = max(0, y - TOP_PADDING)

        crop = frame[
            y:y + OUTPUT_HEIGHT,
            x:x + OUTPUT_WIDTH
        ]

        # Save main output
        cv2.imwrite(OUTPUT_FILE, crop)

        # Save daily cache
        cv2.imwrite(CACHE_FILE, crop)

        print(f"Saved {OUTPUT_FILE}")
        print(f"Saved cache {CACHE_FILE}")
        print(f"Timestamp: {timestamp:.1f} seconds")
        print(f"Template score: {score:.3f}")

        found = True
        break

    current_frame += frame_skip


cap.release()


if not found:
    raise Exception("Could not find Today's Bets graphic.")


print("\nDone.")
