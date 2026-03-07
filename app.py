import base64
import io
import os
import secrets
import time
import urllib.parse
import zipfile
from datetime import datetime

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    session as flask_session,
    url_for,
)
from werkzeug.utils import secure_filename

from config import ADMIN_PASSWORD, GUEST_PASSWORD, WEDDING_DATE
from database import (
    add_song,
    add_upload,
    count_songs_last_hour,
    create_session,
    delete_all_songs,
    delete_all_uploads,
    delete_session,
    delete_song,
    delete_spotify_auth,
    delete_upload,
    get_like_counts,
    get_liked_by_session,
    get_session,
    get_spotify_auth,
    get_upload_meta,
    init_db,
    list_sessions,
    load_songs,
    load_timeline,
    save_spotify_auth,
    save_timeline,
    song_exists,
    toggle_like,
)
from helpers import PICTURES_DIR, allowed_file, get_spotify_token, get_user_spotify_token

load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30 MB

init_db()

COOKIE_NAME = "wc_session"

_spotify_pending_states: set[str] = set()

# Routes that don't require a session
_PUBLIC_PREFIXES = ("/welcome", "/static/", "/public/", "/api/", "/admin/spotify/callback")


# ---------------------------------------------------------------------------
# Session middleware
# ---------------------------------------------------------------------------

@app.before_request
def load_session():
    path = request.path
    if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        g.session_id = None
        g.session_name = None
        g.is_admin = False
        return

    session_id = request.cookies.get(COOKIE_NAME)
    row = get_session(session_id) if session_id else None

    if row is None:
        next_url = request.path
        return redirect(url_for("welcome", next=next_url))

    g.session_id = row["id"]
    g.session_name = row["name"]
    g.is_admin = bool(row["is_admin"])


def _require_admin():
    """Return error response if not admin, else None."""
    session_id = request.cookies.get(COOKIE_NAME)
    if not session_id:
        return jsonify({"ok": False, "error": "Nicht angemeldet."}), 401
    row = get_session(session_id)
    if not row or not row["is_admin"]:
        return jsonify({"ok": False, "error": "Keine Berechtigung."}), 403
    return None


# ---------------------------------------------------------------------------
# Welcome / name + password entry
# ---------------------------------------------------------------------------

@app.route("/welcome", methods=["GET", "POST"])
def welcome():
    if request.method == "POST":
        pw = request.form.get("pw", "").strip()
        if pw not in (GUEST_PASSWORD, ADMIN_PASSWORD):
            next_url = request.form.get("next", "/")
            return render_template("welcome.html", error="Falsches Passwort.", next=next_url, pw="", pw_prefilled=False)

        name = request.form.get("name", "").strip()[:30]
        if not name:
            next_url = request.form.get("next", "/")
            return render_template("welcome.html", error="Bitte gib deinen Namen ein.", next=next_url, pw=pw, pw_prefilled=False)

        is_admin = (pw == ADMIN_PASSWORD)
        session_id = create_session(name, is_admin=is_admin)
        next_url = request.form.get("next") or "/"
        if not next_url.startswith("/"):
            next_url = "/"
        resp = make_response(redirect(next_url))
        resp.set_cookie(
            COOKIE_NAME,
            session_id,
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            samesite="Lax",
        )
        return resp

    next_url = request.args.get("next", "/")
    pw = request.args.get("pw", "")
    pw_valid = pw in (GUEST_PASSWORD, ADMIN_PASSWORD)
    return render_template("welcome.html", next=next_url, pw=pw if pw_valid else "", pw_prefilled=pw_valid)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.context_processor
def inject_guest_url():
    if not getattr(g, "session_id", None):
        return {"guest_url": ""}
    guest_url = request.host_url.rstrip("/") + url_for("welcome") + "?pw=" + GUEST_PASSWORD
    return {"guest_url": guest_url}


@app.route("/")
def index():
    return render_template("index.html", session_name=g.session_name, is_admin=g.is_admin)


@app.route("/ablauf")
def ablauf():
    events = sorted(load_timeline(), key=lambda e: e["time"])
    return render_template("ablauf.html", events=events, wedding_date=WEDDING_DATE, is_admin=g.is_admin)


@app.route("/fotos")
def fotos():
    return render_template("fotos.html", is_admin=g.is_admin)


@app.route("/galerie")
def galerie():
    return render_template("galerie.html", session_id=g.session_id, is_admin=g.is_admin)


@app.route("/liederwunsch")
def liederwunsch():
    spotify_ready = get_user_spotify_token() is not None
    return render_template("liederwunsch.html", is_admin=g.is_admin, spotify_ready=spotify_ready)


@app.route("/zustupf")
def zustupf():
    iban = os.environ.get("WEDDING_IBAN", "")
    phone = os.environ.get("WEDDING_PHONE", "")
    twint_url = os.environ.get("WEDDING_TWINT_URL", "")
    return render_template("zustupf.html", iban=iban, phone=phone, twint_url=twint_url)


@app.route("/admin")
def admin():
    if not g.is_admin:
        return redirect(url_for("index"))
    users = list_sessions()
    songs = load_songs()
    photos = [f.name for f in PICTURES_DIR.glob("*") if f.is_file() and not f.name.startswith(".")]
    spotify_connected = get_spotify_auth() is not None
    events = load_timeline()
    guest_url = request.host_url.rstrip("/") + url_for("welcome") + f"?pw={GUEST_PASSWORD}"
    admin_url = request.host_url.rstrip("/") + url_for("welcome") + f"?pw={ADMIN_PASSWORD}"
    return render_template(
        "admin.html",
        is_admin=True,
        users=users,
        songs=songs,
        photo_count=len(photos),
        spotify_connected=spotify_connected,
        events=events,
        guest_url=guest_url,
        admin_url=admin_url,
        current_session_id=g.session_id,
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@app.route("/fotos/upload", methods=["POST"])
def fotos_upload():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Keine Datei ausgewählt."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "Keine Datei ausgewählt."}), 400

    if not allowed_file(file.filename):
        return jsonify({"ok": False, "error": "Dateityp nicht erlaubt. Erlaubt: JPG, PNG, HEIC, WEBP, GIF."}), 400

    ext = file.filename.rsplit(".", 1)[1].lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = secure_filename(f"{timestamp}.{ext}")
    save_path = PICTURES_DIR / filename
    file.save(str(save_path))

    session_id = request.cookies.get(COOKIE_NAME)
    if session_id and get_session(session_id):
        add_upload(filename, session_id)

    return jsonify({"ok": True, "filename": filename})


# ---------------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------------

@app.route("/api/gallery")
def api_gallery():
    session_id = request.cookies.get(COOKIE_NAME)
    like_counts = get_like_counts()
    liked_set = get_liked_by_session(session_id) if session_id else set()

    files = [f for f in PICTURES_DIR.glob("*") if f.is_file() and not f.name.startswith(".")]

    images = []
    for f in files:
        meta = get_upload_meta(f.name)
        likes = like_counts.get(f.name, 0)
        uploaded_at_str = meta["uploaded_at"] if meta else None
        # For sorting: use uploaded_at string (ISO, sorts lexicographically) or mtime
        sort_time = uploaded_at_str or ""
        images.append({
            "url": url_for("serve_picture", filename=f.name),
            "name": f.name,
            "uploader": meta["session_name"] if meta else None,
            "uploaded_at": uploaded_at_str,
            "likes": likes,
            "liked": f.name in liked_set,
            "_likes": likes,
            "_sort_time": sort_time,
        })

    images.sort(key=lambda x: (x.pop("_likes"), x.pop("_sort_time")), reverse=True)
    return jsonify(images)


@app.route("/public/pictures/<filename>")
def serve_picture(filename: str):
    safe = secure_filename(filename)
    path = PICTURES_DIR / safe
    if not path.exists():
        return "Not found", 404
    return send_file(str(path))


@app.route("/api/gallery/like", methods=["POST"])
def api_gallery_like():
    session_id = request.cookies.get(COOKIE_NAME)
    if not session_id or not get_session(session_id):
        return jsonify({"ok": False, "error": "Keine Session."}), 401
    data = request.get_json(force=True, silent=True) or {}
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"ok": False, "error": "Kein Dateiname."}), 400
    result = toggle_like(filename, session_id)
    return jsonify({"ok": True, **result})


# ---------------------------------------------------------------------------
# Songs
# ---------------------------------------------------------------------------

@app.route("/api/songs", methods=["GET"])
def api_songs_get():
    return jsonify(load_songs())


@app.route("/api/songs", methods=["POST"])
def api_songs_post():
    session_id = request.cookies.get(COOKIE_NAME)
    if not session_id or not get_session(session_id):
        return jsonify({"ok": False, "error": "Keine Session."}), 401

    data = request.get_json(force=True, silent=True) or {}
    required = {"id", "name", "artist"}
    if not required.issubset(data.keys()):
        return jsonify({"ok": False, "error": "Ungültige Songdaten."}), 400

    if song_exists(data["id"]):
        return jsonify({"ok": True, "duplicate": True})

    if count_songs_last_hour(session_id) >= 3:
        return jsonify({
            "ok": False,
            "rate_limited": True,
            "error": "Du hast in der letzten Stunde bereits 3 Songs gewünscht – warte noch ein bisschen! 🎶",
        }), 429

    add_song(data, session_id)

    # Add to Spotify queue if admin token available
    user_token = get_user_spotify_token()
    queue_skipped = True
    if user_token:
        try:
            qresp = requests.post(
                "https://api.spotify.com/v1/me/player/queue",
                headers={"Authorization": f"Bearer {user_token}"},
                params={"uri": f"spotify:track:{data['id']}"},
                timeout=10,
            )
            queue_skipped = qresp.status_code not in (200, 204)
        except Exception:
            queue_skipped = True

    return jsonify({"ok": True, "queue_skipped": queue_skipped})


# ---------------------------------------------------------------------------
# Spotify search (client credentials)
# ---------------------------------------------------------------------------

@app.route("/api/spotify/search")
def api_spotify_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Kein Suchbegriff."}), 400

    token = get_spotify_token()
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


# ---------------------------------------------------------------------------
# Spotify OAuth2 (admin)
# ---------------------------------------------------------------------------

@app.route("/admin/spotify/authorize")
def admin_spotify_authorize():
    if not g.is_admin:
        return redirect(url_for("index"))
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    redirect_uri = os.environ.get("SPOTIFY_REDIRECT_URI", "")
    if not client_id or not redirect_uri:
        return "Spotify nicht konfiguriert (CLIENT_ID oder REDIRECT_URI fehlt).", 503
    state = secrets.token_urlsafe(16)
    _spotify_pending_states.add(state)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": "user-modify-playback-state",
        "state": state,
    }
    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)
    return redirect(auth_url)


@app.route("/admin/spotify/callback")
def admin_spotify_callback():
    state = request.args.get("state", "")
    if state not in _spotify_pending_states:
        return "Ungültiger State.", 400
    _spotify_pending_states.discard(state)

    code = request.args.get("code", "")
    if not code:
        return "Autorisierung fehlgeschlagen.", 400

    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    redirect_uri = os.environ.get("SPOTIFY_REDIRECT_URI", "")
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Authorization": f"Basic {credentials}"},
        timeout=10,
    )
    if resp.status_code != 200:
        return f"Token-Austausch fehlgeschlagen: {resp.text}", 502

    token_data = resp.json()
    save_spotify_auth(
        token_data["access_token"],
        token_data["refresh_token"],
        time.time() + token_data["expires_in"],
    )
    return redirect(url_for("admin"))


# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------

@app.route("/api/admin/spotify", methods=["DELETE"])
def api_admin_spotify_disconnect():
    err = _require_admin()
    if err:
        return err
    delete_spotify_auth()
    return jsonify({"ok": True})


@app.route("/api/admin/songs", methods=["DELETE"])
def api_admin_songs_delete_all():
    err = _require_admin()
    if err:
        return err
    delete_all_songs()
    return jsonify({"ok": True})


@app.route("/api/admin/songs/<song_id>", methods=["DELETE"])
def api_admin_songs_delete_one(song_id: str):
    err = _require_admin()
    if err:
        return err
    delete_song(song_id)
    return jsonify({"ok": True})


@app.route("/api/admin/photos", methods=["DELETE"])
def api_admin_photos_delete_all():
    err = _require_admin()
    if err:
        return err
    for f in PICTURES_DIR.glob("*"):
        if f.is_file() and not f.name.startswith("."):
            f.unlink()
    delete_all_uploads()
    return jsonify({"ok": True})


@app.route("/api/admin/photos/<filename>", methods=["DELETE"])
def api_admin_photos_delete_one(filename: str):
    err = _require_admin()
    if err:
        return err
    safe = secure_filename(filename)
    path = PICTURES_DIR / safe
    if path.exists():
        path.unlink()
    delete_upload(safe)
    return jsonify({"ok": True})


@app.route("/admin/photos/download")
def admin_photos_download():
    if not g.is_admin:
        return redirect(url_for("index"))
    buf = io.BytesIO()
    files = [f for f in PICTURES_DIR.glob("*") if f.is_file() and not f.name.startswith(".")]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.name)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name="fotos.zip")


@app.route("/api/admin/timeline", methods=["POST"])
def api_admin_timeline():
    err = _require_admin()
    if err:
        return err
    events = request.get_json(force=True, silent=True) or []
    if not isinstance(events, list):
        return jsonify({"ok": False, "error": "Ungültige Daten."}), 400
    cleaned = sorted(
        [
            {"time": str(e.get("time", "")).strip(), "label": str(e.get("label", "")).strip()}
            for e in events
            if e.get("time") and e.get("label")
        ],
        key=lambda e: e["time"],
    )
    save_timeline(cleaned)
    return jsonify({"ok": True})


@app.route("/api/admin/users")
def api_admin_users():
    err = _require_admin()
    if err:
        return err
    return jsonify(list_sessions())


@app.route("/api/admin/users/<session_id>", methods=["DELETE"])
def api_admin_users_delete(session_id: str):
    err = _require_admin()
    if err:
        return err
    # Prevent self-deletion
    if session_id == request.cookies.get(COOKIE_NAME):
        return jsonify({"ok": False, "error": "Du kannst dich nicht selbst löschen."}), 400
    delete_session(session_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def too_large(_):
    return jsonify({"ok": False, "error": "Datei zu gross. Maximum: 30 MB."}), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)
