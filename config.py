import os

from dotenv import load_dotenv

load_dotenv()

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "heic", "webp", "gif"}

GUEST_PASSWORD = os.environ.get("GUEST_PASSWORD", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

WEDDING_DATE = "2026-04-25"

# ---------------------------------------------------------------------------
# Timeline events — edit these to match your actual wedding schedule
# ---------------------------------------------------------------------------
ABLAUF_EVENTS = [
    {"date": "2026-04-25", "time": "11:00", "label": "Empfang der Gäste"},
    {"date": "2026-04-25", "time": "12:00", "label": "Brunch"},
    {"date": "2026-04-25", "time": "14:15", "label": "Übergang Trauung"},
    {"date": "2026-04-25", "time": "14:30", "label": "Trauung"},
    {"date": "2026-04-25", "time": "15:30", "label": "Fotos und kurze Pause"},
    {"date": "2026-04-25", "time": "16:00", "label": "Dessert & Kaffee"},
    {"date": "2026-04-25", "time": "18:00", "label": "Verabschiedung Steinmaur"},
    {"date": "2026-04-25", "time": "22:30", "label": "Empfang Albani"},
    {"date": "2026-04-25", "time": "23:00", "label": "Party Time"},
    {"date": "2026-04-26", "time": "04:00", "label": "Letzte Runde"},
]
