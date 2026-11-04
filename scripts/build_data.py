"""Télécharge les calendriers ICS des locaux ECAM et écrit data/all.json.

La liste des locaux est lue dans index.html (DEFAULT_ROOMS), pour n'avoir
qu'une seule source. On ne garde que les cours proches de la date du jour
et les champs utiles, pour que le fichier reste léger.

Usage : python scripts/build_data.py
"""
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICS_BASE = "https://calendar.ecam.be/ics/"
KEEP = ("DTSTART", "DTEND", "SUMMARY", "DESCRIPTION", "RRULE", "EXDATE")
PAST_DAYS, FUTURE_DAYS = 120, 180  # 120 j en arrière pour les cours récurrents


def rooms_from_index():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    block = re.search(r"DEFAULT_ROOMS\s*=\s*\[(.*?)\]", html, re.S).group(1)
    return re.findall(r"'([^']+)'", block)


def fetch(room):
    req = urllib.request.Request(ICS_BASE + room, headers={"User-Agent": "locaux-libres/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def trim(text, lo, hi):
    if "BEGIN:VCALENDAR" not in text:
        return None  # local introuvable
    text = re.sub(r"\r?\n[ \t]", "", text)  # dépliage des lignes
    out = []
    for block in re.findall(r"BEGIN:VEVENT\r?\n(.*?)END:VEVENT", text, re.S):
        lines = [l for l in block.splitlines() if l.split(":", 1)[0].split(";", 1)[0] in KEEP]
        start = next((l for l in lines if l.startswith("DTSTART")), "")
        m = re.search(r":(\d{8})", start)
        if not m or not (lo <= m.group(1) <= hi):
            continue
        out.append("BEGIN:VEVENT\n" + "\n".join(lines) + "\nEND:VEVENT")
    return "BEGIN:VCALENDAR\n" + "\n".join(out) + "\nEND:VCALENDAR\n"


def main():
    now = datetime.now(timezone.utc)
    lo = (now - timedelta(days=PAST_DAYS)).strftime("%Y%m%d")
    hi = (now + timedelta(days=FUTURE_DAYS)).strftime("%Y%m%d")
    rooms = rooms_from_index()

    def job(room):
        try:
            return room, trim(fetch(room), lo, hi)
        except Exception as e:  # on garde la donnée précédente si un local échoue
            print(f"! {room}: {e}")
            return room, "__error__"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(pool.map(job, rooms))

    path = ROOT / "data" / "all.json"
    previous = {}
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8")).get("rooms", {})
    failed = [r for r, v in results.items() if v == "__error__"]
    for r in failed:
        results[r] = previous.get(r)
    if len(failed) == len(rooms):
        raise SystemExit("Aucun calendrier récupéré, on ne touche à rien.")

    new_rooms = dict(sorted(results.items()))
    if new_rooms == previous:
        print("Aucun changement.")
        return
    path.parent.mkdir(exist_ok=True)
    data = {"generated": now.isoformat(timespec="seconds"), "rooms": new_rooms}
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(rooms) - len(failed)}/{len(rooms)} locaux, {path.stat().st_size // 1024} Ko")


if __name__ == "__main__":
    main()
