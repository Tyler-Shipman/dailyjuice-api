import glob
import os
import time
from datetime import datetime

import boto3
import cv2
import yt_dlp

# ==========================================================
# Configuration
# ==========================================================

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLfzUuO_R9acDwEZFY8icK2It16sanH5Hy"

VIDEO_NAME = "latest_video"

TEMPLATE_FILE = "template.png"

OUTPUT_FILE = "todays_bets.png"

# Only download the middle slice of the video where the infographic lives.
# This keeps proxy bandwidth tiny and the download fast.
SECTION_START_PERCENT = 0.40
SECTION_END_PERCENT = 0.70

# The downloaded clip already starts at SECTION_START_PERCENT, so we scan it
# from the beginning.
FRAME_INTERVAL = 1           # seconds between sampled frames

# The infographic is a full-screen slide, and template.png is a full frame of
# it. We resize each video frame to the template's size and correlate the whole
# frame, so matching is independent of the download resolution.
#
# MATCH_THRESHOLD is the loose floor for accepting the best frame: the static
# layout dominates, so the real slide scores far above talking-head frames
# (~-0.04) even as the date/bets text changes daily.
MATCH_THRESHOLD = 0.20
# EARLY_EXIT_THRESHOLD: once a frame scores this high we're confident it's the
# slide, so stop scanning immediately instead of finishing the clip. Today's
# exact-match frame scores ~0.998; future days (different text) score lower, so
# if this never triggers we fall back to the best frame over the whole clip.
EARLY_EXIT_THRESHOLD = 0.90

# Download retries within a single run (the hourly cron is the outer retry).
DOWNLOAD_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 15

# ==========================================================
# Environment
# ==========================================================

# Residential/mobile proxy endpoint, e.g. http://user:pass@host:port
# This is the key reliability lever: it moves YouTube traffic off the
# datacenter IP so no cookies are needed.
PROXY_URL = os.environ.get("YTDLP_PROXY")

# Cloudflare R2 (S3-compatible) credentials.
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.environ.get("R2_BUCKET")

# The single image kept in R2, overwritten each day.
R2_OUTPUT_KEY = "todays-bets.png"

# Local file that records the date we last uploaded, so the hourly cron stops
# re-downloading once today's image is done. Kept on the Pi (not in R2), so R2
# holds only the one image.
MARKER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_uploaded.txt")

# Set FORCE=1 to bypass the "already done today" / "not posted yet" gates
# (useful for local testing). A forced run does not write the marker.
FORCE = os.environ.get("FORCE") == "1"

R2_CONFIGURED = all(
    [R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET]
)

# Local date. On the Pi (set to America/Chicago) the morning posting window
# shares its calendar date with YouTube's UTC upload_date, so a strict match
# is reliable.
TODAY = datetime.now().strftime("%Y%m%d")


# ==========================================================
# Cloudflare R2 helpers
# ==========================================================

def r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def upload_results(client):
    client.upload_file(
        OUTPUT_FILE,
        R2_BUCKET,
        R2_OUTPUT_KEY,
        ExtraArgs={"ContentType": "image/png"},
    )
    print(f"Uploaded {R2_OUTPUT_KEY} to R2 bucket {R2_BUCKET}")


# ==========================================================
# Local "done for today" marker
# ==========================================================

def read_marker():
    """Return the YYYYMMDD date we last successfully uploaded, or None."""
    try:
        with open(MARKER_FILE) as fh:
            return fh.read().strip()
    except OSError:
        return None


def write_marker(date):
    with open(MARKER_FILE, "w") as fh:
        fh.write(date)


# ==========================================================
# yt-dlp helpers
# ==========================================================

def base_ydl_opts(**extra):
    opts = {
        "playlist_items": "1",
        "quiet": False,
        "ignoreerrors": False,
        # android_vr returns full formats cookieless on a residential IP,
        # with no DRM and no PO token required (the tv/ios/web clients now
        # need one or the other). Requires a JS runtime (Deno) for the
        # n-challenge. Verified against this channel.
        "extractor_args": {
            "youtube": {
                "player_client": ["android_vr"],
            }
        },
    }
    if PROXY_URL:
        opts["proxy"] = PROXY_URL
    opts.update(extra)
    return opts


def get_latest_metadata():
    """Return (upload_date, duration_seconds) for the newest playlist item."""
    with yt_dlp.YoutubeDL(base_ydl_opts(skip_download=True)) as ydl:
        info = ydl.extract_info(PLAYLIST_URL, download=False)

    entries = info.get("entries") or []
    if not entries or entries[0] is None:
        raise Exception("Could not read latest playlist item metadata.")

    entry = entries[0]
    return entry.get("upload_date"), entry.get("duration")


def download_section(duration_seconds):
    """Download only SECTION_START..SECTION_END of the latest video, with
    retries. Returns the path to the downloaded file."""
    for file in glob.glob(f"{VIDEO_NAME}.*"):
        try:
            os.remove(file)
        except OSError:
            pass

    start_s = duration_seconds * SECTION_START_PERCENT
    end_s = duration_seconds * SECTION_END_PERCENT

    opts = base_ydl_opts(
        # Video only (no audio needed for template matching), and prefer H.264
        # (avc1) so the Pi can stream-copy the slice and decode frames without a
        # slow AV1/VP9 software transcode.
        format="bestvideo[height<=720][vcodec^=avc1]/bestvideo[height<=720]/best[height<=720]/best",
        outtmpl=f"{VIDEO_NAME}.%(ext)s",
        download_ranges=yt_dlp.utils.download_range_func(None, [(start_s, end_s)]),
        # No force_keyframes_at_cuts: a keyframe-aligned stream copy is far
        # faster on a Pi, and precise cut boundaries don't matter since we scan
        # the whole downloaded clip.
    )

    last_error = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([PLAYLIST_URL])
            break
        except Exception as exc:  # noqa: BLE001 - retry any yt-dlp failure
            last_error = exc
            print(f"Download attempt {attempt} failed: {exc}")
            if attempt < DOWNLOAD_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS)
    else:
        raise Exception(
            f"Video download failed after {DOWNLOAD_ATTEMPTS} attempts: {last_error}"
        )

    for file in glob.glob(f"{VIDEO_NAME}.*"):
        if not file.endswith(".part"):
            return file

    raise Exception("Video download reported success but no file was found.")


# ==========================================================
# Infographic extraction
# ==========================================================

def extract_infographic(video_file):
    template = cv2.imread(TEMPLATE_FILE)
    if template is None:
        raise Exception(
            "Couldn't find template.png\n"
            "It should be a full frame of the Today's Bets slide."
        )
    template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    th, tw = template.shape[:2]

    cap = cv2.VideoCapture(video_file)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frame_skip = max(1, int(fps * FRAME_INTERVAL))

    print("\nSearching for Today's Bets graphic...\n")

    current_frame = 0
    best_score = -1.0
    best_frame = None
    best_ts = 0.0

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)
        success, frame = cap.read()
        if not success:
            break

        # Resize the frame to the template's size and correlate the whole
        # frame — scale-independent, since the slide fills the screen.
        small = cv2.resize(frame, (tw, th))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        score = float(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED).max())

        timestamp = current_frame / fps
        print(f"{timestamp:7.1f}s  score={score:.3f}")

        if score > best_score:
            best_score = score
            best_frame = frame.copy()
            best_ts = timestamp

        # Clearly the slide — stop scanning the rest of the clip.
        if score >= EARLY_EXIT_THRESHOLD:
            print(f"Strong match (score={score:.3f}) — stopping early.")
            break

        current_frame += frame_skip

    cap.release()

    print(f"\nBest match: score={best_score:.3f} at {best_ts:.1f}s")

    if best_frame is None or best_score < MATCH_THRESHOLD:
        raise Exception(
            f"Could not find Today's Bets graphic (best score {best_score:.3f})."
        )

    # Save the full-resolution frame — the whole infographic.
    cv2.imwrite(OUTPUT_FILE, best_frame)
    print(f"Saved {OUTPUT_FILE} (t={best_ts:.1f}s, score={best_score:.3f})")


# ==========================================================
# Main
# ==========================================================

def main():
    print(f"=== daily_bets run started {datetime.now():%Y-%m-%d %H:%M:%S} ===")
    client = r2_client() if R2_CONFIGURED else None
    if client is None:
        print("R2 not configured — running locally without the date gate or upload.")

    # 1. Skip if we already produced today's image (local marker).
    if not FORCE and read_marker() == TODAY:
        print(f"Already have today's image ({datetime.now():%Y-%m-%d %H:%M:%S}). Nothing to do.")
        return

    # 2. Skip if today's episode has not been posted yet (cron retries next hour).
    print(f"({TODAY}) Checking latest episode metadata...")
    upload_date, duration = get_latest_metadata()
    print(f"Latest upload_date={upload_date}, duration={duration}s")

    if not FORCE and upload_date != TODAY:
        print(f"Newest episode ({upload_date}) is not today's ({TODAY}). Exiting.")
        return

    if not duration:
        raise Exception("Could not determine video duration for section download.")

    # 3. Download the relevant section and extract the infographic.
    video_file = download_section(duration)
    print(f"\nUsing video: {video_file}")
    extract_infographic(video_file)

    # 4. Publish the single image, then record success so the cron stops for today.
    if client is not None:
        upload_results(client)
    else:
        print(f"Skipping upload (R2 not configured). Local image: {OUTPUT_FILE}")

    if FORCE:
        print("FORCE run: marker not written, so the scheduled run still runs today.")
    else:
        write_marker(TODAY)

    print(f"\nDone at {datetime.now():%Y-%m-%d %H:%M:%S}.")


if __name__ == "__main__":
    main()
