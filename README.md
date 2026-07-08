# Daily Juice bets infographic

Extracts the daily "TODAY'S BETS" infographic from the Daily Juice YouTube
podcast and publishes it as a static image for an iOS Shortcut to fetch.

## How it works

Generation and serving are decoupled so the fragile part never touches your
phone:

```
GitHub Actions cron (hourly, morning window)
        │
        ├─ yt-dlp ── residential/mobile proxy ──► YouTube   (no cookies)
        │      └─ bgutil PO-token provider (auto-mints bot tokens, no account)
        │
        ├─ OpenCV template match (template.png) ──► todays_bets.png
        │
        └─ upload to Cloudflare R2  (key: todays-bets.png)

iOS Shortcut ──► GET https://<r2-public-url>/todays-bets.png ──► Quick Look
```

The workflow runs hourly during the posting window. `daily_bets.py` exits
cheaply until the new episode is up (it checks the newest playlist item's
`upload_date`), then produces the image once and self-gates for the rest of the
day via the `latest.json` marker in R2.

**Why this is reliable:** the old setup downloaded from a datacenter IP, which
YouTube flags aggressively — so the `cookies.txt` had to be re-exported by hand
every so often. Routing yt-dlp through a residential/mobile proxy moves traffic
off that IP, so **no cookies are needed and nothing has to be refreshed
manually**. The PO-token provider covers the residual bot-check prompts
automatically.

## One-time setup

### 1. Cloudflare R2

1. Create an R2 bucket.
2. Enable public access (r2.dev dev URL) or attach a custom domain. Note the
   public base URL — the image lives at `<base-url>/todays-bets.png`.
3. Create an R2 API token with **Object Read & Write** on the bucket. Note the
   Account ID, Access Key ID, and Secret Access Key.

### 2. Residential / mobile proxy

Sign up for a residential or (ideally) mobile proxy and get a **sticky** session
endpoint of the form `http://user:pass@host:port`. Data use is ~a few MB/day
(only the 40–70% slice of one video is downloaded), so the cheapest tier is
plenty.

### 3. GitHub repository secrets

Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
| --- | --- |
| `YTDLP_PROXY` | `http://user:pass@host:port` |
| `R2_ACCOUNT_ID` | Cloudflare account ID |
| `R2_ACCESS_KEY_ID` | R2 access key |
| `R2_SECRET_ACCESS_KEY` | R2 secret key |
| `R2_BUCKET` | bucket name |

### 4. iOS Shortcut

1. **Get Contents of URL** → `https://<r2-public-url>/todays-bets.png`
2. **Quick Look** (and/or **Save to Photos** / **Set Wallpaper**)

Instant, no auth, no YouTube dependency, no timeout.

## Running locally

```bash
pip install -r requirements.txt

# Optional: run the PO-token provider (Docker) if YouTube demands tokens.
docker run -d -p 4416:4416 brainicism/bgutil-ytdlp-pot-provider

export YTDLP_PROXY="http://user:pass@host:port"   # optional locally
export FORCE=1                                     # bypass date/idempotency gates

# Without R2_* vars set, it just writes todays_bets.png locally and skips upload.
python daily_bets.py
```

Set the `R2_*` variables too to exercise the full upload path.

## Tuning

- **Posting window** — edit the `cron` in `.github/workflows/daily-bets.yml`
  (times are UTC).
- **Download slice** — `SECTION_START_PERCENT` / `SECTION_END_PERCENT` in
  `daily_bets.py`.
- **Match sensitivity / crop** — `MATCH_THRESHOLD`, `OUTPUT_WIDTH/HEIGHT`,
  padding in `daily_bets.py`. Re-crop `template.png` if the show's header
  changes.

## Notes / fallbacks

- GitHub scheduled workflows auto-disable after 60 days of no repo activity and
  cron timing is best-effort (may lag a few minutes) — both are fine here.
- If GitHub cron timing/keepalive ever matters, run the same `daily_bets.py` as
  a **Render Cron Job** instead (needs a Dockerfile that installs `ffmpeg`).
- If cookieless ever trips a bot check for a specific episode, add cookies back
  via a `cookiefile` option — but sourced through the residential proxy session
  so they last far longer.
