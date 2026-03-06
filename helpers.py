import base64
import os
import time
from pathlib import Path

import requests

from config import ALLOWED_EXTENSIONS

# ---------------------------------------------------------------------------
# Paths (created on import)
# ---------------------------------------------------------------------------
PICTURES_DIR = Path("public/pictures")
PICTURES_DIR.mkdir(parents=True, exist_ok=True)

Path("data").mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Spotify token cache
# ---------------------------------------------------------------------------
_spotify_token: dict = {"access_token": None, "expires_at": 0}


def get_spotify_token() -> str | None:
    global _spotify_token
    if _spotify_token["access_token"] and time.time() < _spotify_token["expires_at"] - 30:
        return _spotify_token["access_token"]

    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None

    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=10,
    )
    if resp.status_code != 200:
        return None

    data = resp.json()
    _spotify_token["access_token"] = data["access_token"]
    _spotify_token["expires_at"] = time.time() + data["expires_in"]
    return _spotify_token["access_token"]


# ---------------------------------------------------------------------------
# User (admin) Spotify token — OAuth2 Authorization Code flow
# ---------------------------------------------------------------------------

def get_user_spotify_token() -> str | None:
    from database import get_spotify_auth, save_spotify_auth
    row = get_spotify_auth()
    if row is None:
        return None

    if time.time() < row["expires_at"] - 30:
        return row["access_token"]

    # Refresh
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "refresh_token", "refresh_token": row["refresh_token"]},
        headers={"Authorization": f"Basic {credentials}"},
        timeout=10,
    )
    if resp.status_code != 200:
        return None

    data = resp.json()
    new_access = data["access_token"]
    new_refresh = data.get("refresh_token", row["refresh_token"])
    new_expires = time.time() + data["expires_in"]
    save_spotify_auth(new_access, new_refresh, new_expires)
    return new_access


# ---------------------------------------------------------------------------
# File upload helper
# ---------------------------------------------------------------------------
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
