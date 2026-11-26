"""Posts to the Telegram channel/group with plain HTTPS calls (HTML formatting)."""
import os
import time
from html import escape as _esc

import requests

MAX_LEN = 4000


def esc(x):
    return _esc(str(x), quote=False)


def _chunks(text):
    part = ""
    for line in text.split("\n"):
        if len(part) + len(line) + 1 > MAX_LEN:
            yield part
            part = ""
        part += line + "\n"
    if part.strip():
        yield part


def send(text, dry_run=False):
    if dry_run:
        print("\n" + "=" * 20 + " POST " + "=" * 20 + "\n" + text)
        return True
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHANNEL_ID", "")
    if not token or not chat:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL_ID missing – not sent:\n" + text)
        return False
    ok = True
    for part in _chunks(text):
        for attempt in range(3):
            try:
                r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
                                  json={"chat_id": chat, "text": part, "parse_mode": "HTML",
                                        "disable_web_page_preview": True})
                if r.status_code == 200:
                    break
                print(f"Telegram error {r.status_code}: {r.text[:300]}")
            except requests.RequestException as e:
                print(f"Telegram network error: {type(e).__name__}")
            time.sleep(3 * (attempt + 1))
        else:
            ok = False
    return ok
