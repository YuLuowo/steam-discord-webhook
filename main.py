import requests
import json
import os
from datetime import datetime

WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
API_URL = "https://store.steampowered.com/api/featuredcategories/?cc=tw&l=chinese"
THRESHOLD_DISCOUNT = 80
MAX_ITEMS = 5


def get_app_details(appid):
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=tw&l=chinese"
    response = requests.get(url)
    response.raise_for_status()
    data = response.json().get(str(appid), {}).get("data")
    if not data:
        return None

    price = data.get("price_overview")
    if not price:
        return None

    return {
        "name": data["name"],
        "image": data.get("header_image"),
        "original": price["initial"] / 100,
        "final": price["final"] / 100,
        "currency": price.get("currency", "TWD"),
        "discount": price["discount_percent"],
        "reviews": data.get("recommendations", {}).get("total", 0),
        "appid": appid,
    }


def format_price(price):
    return f"NT$ {price:,.0f}"


def build_game_line(index, game):
    return (
        f"{index}. [{game['name']}](https://store.steampowered.com/app/{game['appid']}) "
        f"{format_price(game['original'])} → {format_price(game['final'])} (-{game['discount']}%)"
    )


def build_description(games):
    return "\n\n".join(
        build_game_line(index + 1, game)
        for index, game in enumerate(games)
    )


def send_webhook(title, description):
    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": 0x1b2838,
            }
        ]
    }
    response = requests.post(WEBHOOK_URL, json=payload)
    response.raise_for_status()


try:
    response = requests.get(API_URL)
    response.raise_for_status()
    data = response.json()
    items = data.get("specials", {}).get("items", [])
except Exception as ex:
    payload = {
        "content": "Steam 特價資料取得失敗，請檢查程式或網路連線。",
        "embeds": [
            {
                "title": "Steam 折扣通知失敗",
                "description": str(ex),
                "color": 0xff0000,
            }
        ],
    }
    requests.post(WEBHOOK_URL, json=payload)
    raise

all_games = []
for game in items:
    appid = game["id"]
    details = get_app_details(appid)
    if not details:
        continue
    all_games.append(details)

today_str = datetime.now().strftime("%Y-%m-%d %H:%M")

if not all_games:
    send_webhook(
        f"Steam 特價通知 - {today_str}",
        "今日未取得任何 Steam 特價遊戲資料。"
    )
    top_games = []
else:
    high_discount_games = [
        game for game in all_games if game["discount"] >= THRESHOLD_DISCOUNT
    ]
    top_games = sorted(
        all_games,
        key=lambda x: (x["discount"], -x["final"]),
        reverse=True,
    )[:MAX_ITEMS]

    if high_discount_games:
        high_discount_games = sorted(
            high_discount_games,
            key=lambda x: (x["discount"], -x["final"]),
            reverse=True,
        )[:MAX_ITEMS]
        for g in high_discount_games:
            payload = {
                "embeds": [
                    {
                        "title": "Steam 精選折扣",
                        "description": (
                            f"**{g['name']}**\n\n"
                            f"{format_price(g['original'])} → {format_price(g['final'])} (-{g['discount']}%)\n"
                            f"評論數：{g['reviews']:,}\n\n"
                            f"[查看遊戲](https://store.steampowered.com/app/{g['appid']})"
                        ),
                        "color": 0x1b2838,
                        "image": {"url": g.get("image")},
                    }
                ]
            }
            requests.post(WEBHOOK_URL, json=payload)
    else:
        description = (
            "今天沒有折扣 80% 以上的遊戲。\n\n"
            "以下列出前 5 個熱門折扣遊戲：\n\n"
            + build_description(top_games)
        )
        send_webhook(
            f"Steam 今日熱門折扣 - {today_str}",
            description,
        )

with open("seen.json", "w", encoding="utf-8") as f:
    json.dump(
        {
            "last_run_count": len(top_games),
            "threshold": THRESHOLD_DISCOUNT,
            "top_games": [game["appid"] for game in top_games],
        },
        f,
        ensure_ascii=False,
        indent=2,
    )
