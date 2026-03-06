import io
import json
import os
import time
import zipfile
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB

PICTURES_DIR = Path("public/pictures")
PICTURES_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
SONGS_FILE = DATA_DIR / "songs.json"

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "heic", "webp", "gif"}

# ---------------------------------------------------------------------------
# Timeline events — edit these to match your actual wedding schedule
# ---------------------------------------------------------------------------
ABLAUF_EVENTS = [
    {"time": "13:00", "label": "Empfang der Gäste"},
    {"time": "14:00", "label": "Standesamtliche Trauung"},
    {"time": "15:00", "label": "Sektempfang & Fotos"},
    {"time": "16:30", "label": "Aperitif im Garten"},
    {"time": "18:00", "label": "Einzug ins Festzelt"},
    {"time": "18:30", "label": "Abendessen"},
    {"time": "20:00", "label": "Reden & Überraschungen"},
    {"time": "21:00", "label": "Hochzeitstorte"},
    {"time": "21:30", "label": "Eröffnungstanz"},
    {"time": "22:00", "label": "Party & Tanzfläche"},
    {"time": "02:00", "label": "Nachtessen & Ausklang"},
]

# ---------------------------------------------------------------------------
# Spotify token cache
# ---------------------------------------------------------------------------
_spotify_token: dict = {"access_token": None, "expires_at": 0}


def _get_spotify_token() -> str | None:
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
# Song queue helpers
# ---------------------------------------------------------------------------
def _load_songs() -> list:
    if SONGS_FILE.exists():
        try:
            return json.loads(SONGS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save_songs(songs: list) -> None:
    SONGS_FILE.write_text(json.dumps(songs, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# File upload helper
# ---------------------------------------------------------------------------
def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/ablauf")
def ablauf():
    return render_template("ablauf.html", events=ABLAUF_EVENTS)


@app.route("/fotos")
def fotos():
    return render_template("fotos.html")


@app.route("/fotos/upload", methods=["POST"])
def fotos_upload():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Keine Datei ausgewählt."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "Keine Datei ausgewählt."}), 400

    if not _allowed_file(file.filename):
        return jsonify({"ok": False, "error": "Dateityp nicht erlaubt. Erlaubt: JPG, PNG, HEIC, WEBP, GIF."}), 400

    ext = file.filename.rsplit(".", 1)[1].lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = secure_filename(f"{timestamp}.{ext}")
    save_path = PICTURES_DIR / filename
    file.save(str(save_path))

    return jsonify({"ok": True, "filename": filename})


@app.route("/galerie")
def galerie():
    return render_template("galerie.html")


@app.route("/api/gallery")
def api_gallery():
    files = sorted(PICTURES_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    images = [
        {"url": url_for("serve_picture", filename=f.name), "name": f.name}
        for f in files
        if f.is_file() and not f.name.startswith(".")
    ]
    return jsonify(images)


@app.route("/public/pictures/<filename>")
def serve_picture(filename: str):
    safe = secure_filename(filename)
    path = PICTURES_DIR / safe
    if not path.exists():
        return "Not found", 404
    return send_file(str(path))


@app.route("/galerie/download")
def galerie_download():
    files = [f for f in PICTURES_DIR.iterdir() if f.is_file() and not f.name.startswith(".")]
    if not files:
        return "Keine Bilder vorhanden.", 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(str(f), f.name)
    buf.seek(0)

    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="hochzeitsfotos.zip",
    )


@app.route("/liederwunsch")
def liederwunsch():
    return render_template("liederwunsch.html")


@app.route("/api/spotify/search")
def api_spotify_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Kein Suchbegriff."}), 400

    token = _get_spotify_token()
    if not token:
        return jsonify({"error": "Spotify nicht konfiguriert."}), 503

    resp = requests.get(
        "https://api.spotify.com/v1/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": q, "type": "track", "limit": 5, "market": "CH"},
        timeout=10,
    )
    if resp.status_code != 200:
        return jsonify({"error": "Spotify-Fehler."}), 502

    items = resp.json().get("tracks", {}).get("items", [])
    tracks = [
        {
            "id": t["id"],
            "name": t["name"],
            "artist": ", ".join(a["name"] for a in t["artists"]),
            "cover": t["album"]["images"][0]["url"] if t["album"]["images"] else None,
            "album": t["album"]["name"],
        }
        for t in items
    ]
    return jsonify(tracks)


@app.route("/api/songs", methods=["GET"])
def api_songs_get():
    return jsonify(_load_songs())


@app.route("/api/songs", methods=["POST"])
def api_songs_post():
    data = request.get_json(force=True, silent=True) or {}
    required = {"id", "name", "artist"}
    if not required.issubset(data.keys()):
        return jsonify({"ok": False, "error": "Ungültige Songdaten."}), 400

    songs = _load_songs()
    if any(s["id"] == data["id"] for s in songs):
        return jsonify({"ok": True, "duplicate": True})

    songs.append({
        "id": data["id"],
        "name": data["name"],
        "artist": data["artist"],
        "cover": data.get("cover"),
        "album": data.get("album", ""),
        "added_at": datetime.now().isoformat(),
    })
    _save_songs(songs)
    return jsonify({"ok": True})


@app.route("/zustupf")
def zustupf():
    iban = os.environ.get("WEDDING_IBAN", "")
    return render_template("zustupf.html", iban=iban)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def too_large(_):
    return jsonify({"ok": False, "error": "Datei zu gross. Maximum: 20 MB."}), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)
