import requests
import json
import os
from datetime import datetime, timedelta

WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
SEARCH_API_URL = "https://store.steampowered.com/api/storesearch/?tags=588&cc=tw&count=50"
ALSO_CHECK_SPECIALS = "https://store.steampowered.com/api/featuredcategories/?cc=tw&l=chinese"
ALSO_CHECK_FEATURED = "https://store.steampowered.com/api/featured/?cc=tw"
HISTORY_FILE = "free_history.json"


def get_app_details(appid):
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=tw&l=chinese"
    r = requests.get(url)
    r.raise_for_status()
    data = r.json().get(str(appid), {}).get("data")
    if not data:
        return None

    is_free = data.get("is_free", False)
    price = data.get("price_overview")

    # Allow games without price_overview if they're free-to-play
    if not price and not is_free:
        return None

    return {
        "appid": appid,
        "name": data.get("name"),
        "image": data.get("header_image"),
        "original": price.get("initial") / 100 if price else 0,
        "final": price.get("final") / 100 if price else 0,
        "discount": price.get("discount_percent") if price else (100 if is_free else 0),
        "is_free": is_free,
    }


def load_history():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def send_webhook(title, description):
    payload = {
        "embeds": [
            {"title": title, "description": description, "color": 0x1b2838}
        ]
    }
    r = requests.post(WEBHOOK_URL, json=payload)
    r.raise_for_status()


def format_price(price):
    try:
        return f"NT$ {price:,.0f}"
    except Exception:
        return "NT$ 0"


# Collect all game IDs to check from multiple sources
all_game_ids = set()

# 1. F2P tag search
try:
    resp = requests.get(SEARCH_API_URL)
    resp.raise_for_status()
    items = resp.json().get("items", [])
    for game in items:
        all_game_ids.add(game.get("id"))
except Exception:
    pass

# 2. Specials API
try:
    resp = requests.get(ALSO_CHECK_SPECIALS)
    resp.raise_for_status()
    items = resp.json().get("specials", {}).get("items", [])
    for game in items:
        all_game_ids.add(game.get("id"))
except Exception:
    pass

# 3. Featured API
try:
    resp = requests.get(ALSO_CHECK_FEATURED)
    resp.raise_for_status()
    data = resp.json()
    for key in ['featured_win', 'featured_mac', 'featured_linux']:
        for game in data.get(key, []):
            all_game_ids.add(game.get("id"))
except Exception:
    pass

history = load_history()
now = datetime.utcnow()
added = []

for appid in all_game_ids:
    try:
        details = get_app_details(appid)
    except Exception:
        continue
    if not details:
        continue
    # Only track non-permanently-free games that are now 100% off
    # Exclude is_free=True games (permanently free)
    if details.get("discount") == 100 and not details.get("is_free"):
        # check if already recorded (by appid)
        exists = any(h.get("appid") == appid for h in history)
        if not exists:
            record = {
                "appid": appid,
                "name": details.get("name"),
                "original": details.get("original"),
                "final": details.get("final"),
                "discount": details.get("discount"),
                "is_free": details.get("is_free"),
                "first_seen": now.isoformat(),
            }
            history.append(record)
            added.append(record)

# save history if new entries
if added:
    save_history(history)

# Determine period
period_start = now - timedelta(days=30)
period_end = now

# Filter history in period
filtered = [h for h in history if period_start <= datetime.fromisoformat(h["first_seen"]) <= period_end]

# Unique by appid, choose earliest first_seen in period
unique = {}
for h in filtered:
    a = h["appid"]
    if a not in unique or datetime.fromisoformat(h["first_seen"]) < datetime.fromisoformat(unique[a]["first_seen"]):
        unique[a] = h

if unique:
    lines = []
    for idx, (appid, h) in enumerate(sorted(unique.items(), key=lambda x: x[1]["first_seen"])):
        link = f"https://store.steampowered.com/app/{appid}"
        first = datetime.fromisoformat(h["first_seen"]).strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"{idx+1}. [{h['name']}]({link}) {format_price(h['original'])} → {format_price(h['final'])} (-{h['discount']}%) — 首次出現：{first}")
    title = f"期間免費遊戲清單 ({period_start.strftime('%Y-%m-%d')} → {period_end.strftime('%Y-%m-%d')})"
    description = "\n\n".join(lines)
    send_webhook(title, description)
else:
    send_webhook(
        f"期間免費遊戲清單 ({period_start.strftime('%Y-%m-%d')} → {period_end.strftime('%Y-%m-%d')})",
        "在此期間未找到任何 100% 折扣（免費）遊戲。",
    )
