# Saving Full Bot

Telegram bot for downloading video or MP3 from links and searching music on YouTube.

## Features

- YouTube/TikTok/Instagram link detection
- Video download: 360p, 720p, 1080p
- MP3 download
- YouTube music search by song name
- Paginated search results
- Persistent language and callback state
- Telegram `file_id` cache and duplicate-download locking
- Uzbek, Russian, English language menu
- Admin statistics
- Docker and Procfile deployment files

## Local Run

1. Install Python 3.11+, Node.js 22+ and Git.
2. Run the setup script. It installs Python dependencies and builds the
   cookie-free YouTube PO-token provider:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_youtube.ps1
```

3. Create `.env` from `.env.example` and set your token:

```bash
BOT_TOKEN=123456:YOUR_TELEGRAM_BOT_TOKEN
ADMIN_CHAT_ID=5151373754
```

4. Start the bot:

```bash
python bot.py
```

## Docker

```bash
docker compose up -d --build
docker compose logs -f bot
```

The Compose deployment includes Node.js 24, the local-only PO-token provider,
automatic restart and a persistent Docker volume for stats, media cache and
the admin audit database.

## Super Admin

Set `ADMIN_CHAT_ID` in `.env`, then use these commands from that Telegram
account:

```text
/admin
/panel
/history USER_ID
```

The panel shows statistics, recent incoming/outgoing events, users, individual
dialog history, runtime status and a live audit toggle. Audit data is stored in
`audit.db` under `DATA_DIR`.

## Notes

- YouTube downloads use EJS, Node.js and a local PO-token provider; browser
  cookies are not required for public media.
- FFmpeg is bundled through `imageio-ffmpeg` for MP3 conversion and video merging.
- `stats.json` is created automatically.
- Temporary files are stored in `tmp/` and deleted after sending.

## Large videos

The public Telegram Bot API accepts new uploads up to 50 MB. Cached files sent
by `file_id` are effectively instant, but a video that this bot has never seen
must first be downloaded and uploaded.

To send new files up to 2000 MB, run Telegram's official local Bot API server
with `--local` and configure:

```env
BOT_API_BASE_URL=http://telegram-bot-api:8081/bot
BOT_API_BASE_FILE_URL=http://telegram-bot-api:8081/file/bot
BOT_API_LOCAL_MODE=1
TELEGRAM_UPLOAD_LIMIT_MB=2000
```

The local server requires a Telegram `api_id` and `api_hash`. Before moving a
bot from the public API, call `logOut` as required by Telegram's local Bot API
server documentation. Only one polling instance of this bot may run at a time.

## Reliability and privacy

- Callback state and language preferences are stored in `state.db`.
- Audit events are removed after `AUDIT_RETENTION_DAYS` (90 by default).
- Only YouTube, TikTok, and Instagram URLs are accepted.
- `DOWNLOAD_TIMEOUT` applies to both Telegram uploads and yt-dlp progress.
