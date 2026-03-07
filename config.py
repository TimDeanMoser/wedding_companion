import os

from dotenv import load_dotenv

load_dotenv()

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "heic", "webp", "gif"}

GUEST_PASSWORD = os.environ.get("WEDDING_GUEST_PASSWORD", "")
ADMIN_PASSWORD = os.environ.get("WEDDING_ADMIN_PASSWORD", "")

WEDDING_DATE = "2026-04-25"

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
]
