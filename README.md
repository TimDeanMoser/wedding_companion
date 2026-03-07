# Wedding Companion

A private web app for wedding guests. Features include a photo gallery, song wishlist with Spotify integration, wedding schedule (Ablauf), gift/Zustupf info, and an admin panel.

## Features

- **Welcome gate** — guests enter their name + a shared password to access the app
- **Ablauf** — wedding schedule / timeline, editable by admin
- **Fotos** — guests can upload photos (JPG, PNG, HEIC, WEBP, GIF, max 30 MB each)
- **Galerie** — shared photo gallery with likes
- **Liederwunsch** — song wishlist with Spotify search; optionally queues songs directly to a Spotify player
- **Zustupf** — gift info (IBAN, phone, Twint QR)
- **Admin panel** — manage guests, songs, photos, timeline, Spotify connection

## Tech Stack

- Python 3.11+ / Flask
- SQLite (via `data/wedding.db`)
- Photos stored in `public/pictures/`
- [uv](https://github.com/astral-sh/uv) for dependency management
- Gunicorn for production serving

## Local Development

```bash
# Install dependencies
uv sync

# Copy and fill in the env file
cp .env.example .env
# Edit .env with your actual values

# Run the dev server (port 8080)
uv run python app.py
```

Open [http://localhost:8080/welcome](http://localhost:8080/welcome).

## Configuration

All secrets live in `.env` (never committed). See `.env.example` for all required variables:

| Variable | Description |
|---|---|
| `FLASK_SECRET_KEY` | Random secret for Flask sessions (use `openssl rand -hex 32`) |
| `WEDDING_GUEST_PASSWORD` | Password guests use to log in |
| `WEDDING_ADMIN_PASSWORD` | Password for admin access |
| `SPOTIFY_CLIENT_ID` | Spotify app client ID (optional) |
| `SPOTIFY_CLIENT_SECRET` | Spotify app client secret (optional) |
| `SPOTIFY_REDIRECT_URI` | OAuth callback URL (must match Spotify app settings) |
| `WEDDING_IBAN` | IBAN shown on Zustupf page |
| `WEDDING_PHONE` | Phone number shown on Zustupf page |
| `WEDDING_TWINT_URL` | Twint deeplink URL |

### Spotify Setup (optional)

1. Create an app at [developer.spotify.com](https://developer.spotify.com/dashboard)
2. Add your redirect URI (e.g. `https://your-domain.com/admin/spotify/callback`) in the app settings
3. Fill in `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI` in `.env`
4. As admin, go to the admin panel and click "Spotify verbinden"

### Wedding Schedule

Edit `ABLAUF_EVENTS` in [config.py](config.py) before first run, or use the admin panel to edit the timeline after launch.

## Production Deployment

Run with Gunicorn:

```bash
gunicorn app:app --bind 0.0.0.0:8080 --workers 2 --timeout 120
```

Or use the `Procfile` which is already configured for this.

**Environment variables to set on the server** (do not use `.env` file in production — use the platform's secret/env mechanism):

- All variables from `.env.example`
- `PORT` — the port to listen on (default: 8080)

**Persistent data** — two paths must survive deploys / container restarts:

| Path | Contents |
|---|---|
| `data/wedding.db` | SQLite database (sessions, songs, likes, timeline) |
| `public/pictures/` | Uploaded guest photos |

Mount these as persistent volumes or use a VPS with a local disk and keep them out of git (already gitignored).

## Data & Privacy

- Guest names and uploaded photos are stored locally on the server
- No data is sent to third parties except Spotify (when Spotify integration is used)
- The app has no public sign-up — access requires the shared guest password
