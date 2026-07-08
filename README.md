# Daily Juice bets infographic

Extracts the daily "TODAY'S BETS" infographic from the Daily Juice YouTube
podcast and publishes it as a static image for an iOS Shortcut to fetch.

## How it works

A **Raspberry Pi** on a home (residential) internet connection runs the scraper
on a schedule and pushes the result to **Cloudflare R2**. The iOS Shortcut just
fetches a static image URL.

```
Raspberry Pi (residential IP — no cookies, no proxy)
        │  cron, hourly in a morning window
        ├─ yt-dlp (tv_embedded client + Deno for the n-challenge)
        │     downloads only the 40–70% slice of the latest episode
        ├─ OpenCV template match (template.png) ──► todays_bets.png
        └─ upload to Cloudflare R2  (key: todays-bets.png)

iOS Shortcut ──► GET https://<r2-public-url>/todays-bets.png ──► Quick Look
```

`daily_bets.py` exits cheaply until the newest playlist item's `upload_date` is
today, then produces the image once and records the date in a local
`last_uploaded.txt` file so the hourly cron stops for the rest of the day.
**R2 holds exactly one object** — `todays-bets.png`, overwritten each day.

**Why the Pi:** the original Render setup downloaded from a datacenter IP, which
YouTube flags aggressively — forcing a `cookies.txt` that had to be re-exported
by hand. The Pi's residential IP is not flagged, so downloads work **cookieless**
with **no proxy and no manual refresh**. The Pi is never exposed to the internet
(outbound only); R2 serves the image and stays up even when the Pi is offline.

## One-time setup

### 1. Cloudflare R2

1. Create an R2 bucket (e.g. `dailyjuice`).
2. Enable the **Public Development URL** in the bucket's Settings — note the
   `https://pub-xxxx.r2.dev` base URL. The image lives at
   `<base-url>/todays-bets.png`.
3. Create an R2 API token with **Object Read & Write**. Note the Account ID,
   Access Key ID, and Secret Access Key.

### 2. Raspberry Pi (64-bit Raspberry Pi OS Lite)

```bash
# Match the show's timezone so "today" and the 7am schedule line up.
sudo timedatectl set-timezone America/Chicago

sudo apt update
# OpenCV from apt (prebuilt — avoids a multi-hour source build on a Pi 3B).
sudo apt install -y python3-venv python3-pip ffmpeg git unzip python3-opencv

# Deno: JS runtime yt-dlp needs to solve YouTube's n-challenge (nsig).
curl -fsSL https://deno.land/install.sh | sh   # installs to ~/.deno/bin

git clone https://github.com/Tyler-Shipman/dailyjuice-api.git
cd dailyjuice-api

# --system-site-packages lets the venv import the apt-installed cv2.
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -U pip
# yt-dlp[default] bundles the yt-dlp-ejs n-challenge solver scripts.
.venv/bin/pip install -U "yt-dlp[default]" boto3 curl-cffi
```

Create `~/dailyjuice-api/env.sh` (chmod 600) with your R2 credentials **and** the
Deno path (cron needs Deno on PATH):

```bash
export R2_ACCOUNT_ID="..."
export R2_ACCESS_KEY_ID="..."
export R2_SECRET_ACCESS_KEY="..."
export R2_BUCKET="dailyjuice"
export PATH="$HOME/.deno/bin:$PATH"
```

Test it end-to-end (force a real download regardless of date; does not write the
daily marker):

```bash
cd ~/dailyjuice-api
source env.sh
FORCE=1 .venv/bin/python daily_bets.py
```

Then schedule it with cron (`crontab -e`). Runs hourly 7am–noon CT — the script
no-ops until today's episode is up, then runs once and the local marker stops it
for the rest of the day:

```cron
0 7-12 * * * cd /home/pi/dailyjuice-api && source env.sh && .venv/bin/python daily_bets.py >> /home/pi/dailyjuice-api/cron.log 2>&1
```

(Widen the hour range if the show ever posts later than noon.)

### 3. iOS Shortcut

1. **Get Contents of URL** → `https://<r2-public-url>/todays-bets.png`
2. **Quick Look** (and/or **Save to Photos** / **Set Wallpaper**)

Instant, no auth, no YouTube dependency, no timeout.

## Tuning

- **Posting window** — the cron hour range (local time).
- **Download slice** — `SECTION_START_PERCENT` / `SECTION_END_PERCENT`.
- **Match sensitivity / crop** — `MATCH_THRESHOLD`, `OUTPUT_WIDTH/HEIGHT`,
  padding. Re-crop `template.png` if the show's header changes.

## Notes / fallbacks

- Without the `R2_*` variables set, the script just writes `todays_bets.png`
  locally and skips the upload — handy for local testing.
- `YTDLP_PROXY` is still supported: set it to `http://user:pass@host:port` to
  route through a residential proxy if you ever run this off-residential (e.g.
  back on a cloud host).
- If a rare bot-check appears on the Pi, export a browser `cookies.txt` and add a
  `cookiefile` option — on a residential IP these last far longer than on a
  datacenter host.
