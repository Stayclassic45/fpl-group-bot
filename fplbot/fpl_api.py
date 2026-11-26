"""Public Fantasy Premier League endpoints (no key). They are unofficial and can
change, so every failure says exactly which endpoint broke."""
import time
import requests

BASE = "https://fantasy.premierleague.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; fpl-helper)"}


class FplError(Exception):
    pass


def _get(path):
    last = None
    for attempt in range(3):
        if attempt:
            time.sleep(3 * attempt)
        try:
            r = requests.get(f"{BASE}/{path}", headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
            if r.status_code == 404:
                break
        except (requests.RequestException, ValueError) as e:
            last = type(e).__name__
    raise FplError(f"The FPL endpoint '{path}' stopped working ({last}). "
                   "FPL may have changed it, or the game may be updating.")


def bootstrap():
    return _get("bootstrap-static/")


def fixtures():
    return _get("fixtures/")


def history(team_id):
    return _get(f"entry/{team_id}/history/")


def picks(team_id, gw):
    return _get(f"entry/{team_id}/event/{gw}/picks/")


def live(gw):
    return _get(f"event/{gw}/live/")
