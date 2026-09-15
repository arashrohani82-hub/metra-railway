"""Button-only Telegram bot for household shopping and consumption tracking.

The bot shares the existing Railway web process, but uses its own Telegram
token, webhook, allow-list, and persistent data file.  Nothing is registered
unless HOUSEHOLD_BOT_TOKEN is configured.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import statistics
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from flask import jsonify, request


logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("HOUSEHOLD_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.environ.get("HOUSEHOLD_WEBHOOK_SECRET", "").strip()
SETUP_SECRET = os.environ.get(
    "HOUSEHOLD_SETUP_SECRET", os.environ.get("SETUP_SECRET", "")
).strip()
PUBLIC_URL = os.environ.get(
    "HOUSEHOLD_PUBLIC_URL",
    os.environ.get("PUBLIC_URL", os.environ.get("ODS_PUBLIC_URL", "")),
).strip().rstrip("/")
if not PUBLIC_URL and os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    PUBLIC_URL = f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN'].strip()}"

ALLOWED_USERS = {
    int(value.strip())
    for value in os.environ.get(
        "HOUSEHOLD_ALLOWED_TELEGRAM_USER_IDS",
        os.environ.get("ALLOWED_TELEGRAM_USER_IDS", ""),
    ).split(",")
    if value.strip().isdigit()
}

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_FILE = DATA_DIR / "household_purchases.json"


CATEGORIES = {
    "dairy": ("🥛 Dairy & Breakfast", [
        "Milk", "Yogurt", "Cheese", "Butter", "Eggs", "Bread", "Breakfast cereal",
    ]),
    "produce": ("🍎 Fruit & Vegetables", [
        "Bananas", "Apples", "Oranges", "Strawberries", "Cucumbers", "Tomatoes", "Potatoes",
        "Onions", "Vegetables", "Salad",
    ]),
    "protein": ("🍗 Meat & Protein", [
        "Chicken", "Beef", "Fish", "Tuna", "Legumes",
    ]),
    "pantry": ("🧺 Pantry", [
        "Rice", "Pasta", "Cooking oil", "Flour", "Sugar", "Salt", "Coffee", "Tea",
        "Tomato paste", "Napkins",
    ]),
    "drinks": ("🧃 Drinks", [
        "Bottled water", "Juice", "Soft drinks", "Sparkling water",
    ]),
    "cleaning": ("🧽 Home Cleaning", [
        "Dish soap", "Dishwasher tablets", "Laundry detergent", "Fabric softener",
        "Hand soap", "Surface cleaner", "Garbage bags", "Paper towels",
        "Toilet paper",
    ]),
    "personal": ("🧴 Personal Care", [
        "Shampoo", "Soap", "Toothpaste", "Toothbrushes", "Deodorant", "Razors",
    ]),
    "arvin": ("🧒 Arvin", [
        "School snacks", "Arvin's juice", "Wet wipes", "School supplies",
    ]),
}


def _item_id(category: str, index: int) -> str:
    return f"{category}-{index}"


CATALOG = {
    _item_id(category, index): {"name": name, "category": category}
    for category, (_, names) in CATEGORIES.items()
    for index, name in enumerate(names)
}


class HouseholdStore:
    def __init__(self, path: Path = DATA_FILE):
        self.path = Path(path)
        self.lock = threading.RLock()

    @staticmethod
    def blank():
        return {"shopping": {}, "purchases": [], "sessions": {}}

    def load(self):
        with self.lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                payload = self.blank()
            if not isinstance(payload, dict):
                payload = self.blank()
            payload.setdefault("shopping", {})
            payload.setdefault("purchases", [])
            payload.setdefault("sessions", {})
            return payload

    def save(self, payload):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.path)

    def add_to_list(self, item_id, quantity=1):
        with self.lock:
            payload = self.load()
            row = dict(payload["shopping"].get(item_id) or {})
            row["quantity"] = int(row.get("quantity") or 0) + int(quantity)
            row["added_at"] = row.get("added_at") or _now_iso()
            payload["shopping"][item_id] = row
            self.save(payload)
            return row

    def remove_from_list(self, item_id):
        with self.lock:
            payload = self.load()
            payload["shopping"].pop(item_id, None)
            self.save(payload)

    def record_purchase(self, item_id, quantity=1):
        with self.lock:
            payload = self.load()
            item = CATALOG[item_id]
            payload["purchases"].append({
                "item_id": item_id,
                "name": item["name"],
                "quantity": int(quantity),
                "purchased_at": _now_iso(),
            })
            payload["purchases"] = payload["purchases"][-3000:]
            payload["shopping"].pop(item_id, None)
            self.save(payload)


STORE = HouseholdStore()


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_day(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def consumption_stats(payload, today=None):
    """Return learned median purchase interval and next expected date per item."""
    today = today or date.today()
    grouped = {}
    for row in payload.get("purchases", []):
        item_id = row.get("item_id")
        purchased = _parse_day(row.get("purchased_at"))
        if item_id in CATALOG and purchased:
            grouped.setdefault(item_id, []).append(purchased)

    result = {}
    for item_id, days in grouped.items():
        unique_days = sorted(set(days))
        intervals = [
            (current - previous).days
            for previous, current in zip(unique_days, unique_days[1:])
            if (current - previous).days > 0
        ]
        average_days = int(round(statistics.median(intervals))) if intervals else None
        next_date = unique_days[-1] + timedelta(days=average_days) if average_days else None
        result[item_id] = {
            "purchases": len(days),
            "average_days": average_days,
            "last_date": unique_days[-1],
            "next_date": next_date,
            "due": bool(next_date and next_date <= today + timedelta(days=3)),
        }
    return result


def _main_menu():
    return {
        "keyboard": [
            [{"text": "🛒 Shopping List"}, {"text": "➕ Add Items"}],
            [{"text": "✅ Record Purchase"}, {"text": "⚠️ Running Low"}],
            [{"text": "📊 Consumption Trends"}, {"text": "📜 Purchase History"}],
            [{"text": "🏠 Main Menu"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "Choose a button…",
    }


def _inline(rows):
    return {"inline_keyboard": rows}


def _category_keyboard(action="category"):
    rows = []
    items = list(CATEGORIES.items())
    for index in range(0, len(items), 2):
        row = []
        for key, (label, _) in items[index:index + 2]:
            row.append({"text": label, "callback_data": f"{action}:{key}"})
        rows.append(row)
    rows.append([{"text": "⬅️ Back", "callback_data": "home"}])
    return _inline(rows)


def _telegram(method, **payload):
    if not BOT_TOKEN:
        return {"ok": False, "description": "HOUSEHOLD_BOT_TOKEN is missing"}
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=20
    )
    try:
        return response.json()
    except ValueError:
        return {"ok": False, "description": response.text[:200]}


def _send(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _telegram("sendMessage", **payload)


def _answer_callback(callback_id, text=""):
    return _telegram("answerCallbackQuery", callback_query_id=callback_id, text=text)


def _authorized(actor_id):
    # Fail closed: a private household bot must never become public because an
    # allow-list variable was accidentally omitted.
    return bool(ALLOWED_USERS) and int(actor_id) in ALLOWED_USERS


def _show_home(chat_id):
    payload = STORE.load()
    count = len(payload["shopping"])
    stats = consumption_stats(payload)
    due = sum(1 for item_id, row in stats.items() if row["due"] and item_id not in payload["shopping"])
    _send(
        chat_id,
        "🏠 Home Shopping Manager\n\n"
        f"🛒 {count} item(s) on the shopping list\n"
        f"⚠️ {due} item(s) may be running low\n\n"
        "Choose an option:",
        _main_menu(),
    )


def _show_categories(chat_id):
    _send(chat_id, "Choose a category:", _category_keyboard())


def _show_catalog(chat_id, category):
    category_info = CATEGORIES.get(category)
    if not category_info:
        _show_categories(chat_id)
        return
    payload = STORE.load()
    rows = []
    for item_id, item in CATALOG.items():
        if item["category"] != category:
            continue
        quantity = int((payload["shopping"].get(item_id) or {}).get("quantity") or 0)
        prefix = f"✅ {quantity}× " if quantity else "➕ "
        rows.append([{
            "text": prefix + item["name"],
            "callback_data": f"add:{item_id}",
        }])
    rows.append([{"text": "⬅️ Categories", "callback_data": "categories"}])
    _send(chat_id, f"{category_info[0]}\nTap an item to add it:", _inline(rows))


def _show_shopping(chat_id, purchasing=False):
    payload = STORE.load()
    shopping = payload["shopping"]
    if not shopping:
        _send(chat_id, "🛒 Your shopping list is empty.", _category_keyboard())
        return
    lines = ["✅ Select the items you purchased:" if purchasing else "🛒 Home shopping list:"]
    rows = []
    for item_id, row in shopping.items():
        item = CATALOG.get(item_id)
        if not item:
            continue
        quantity = int(row.get("quantity") or 1)
        lines.append(f"• {item['name']} — Qty. {quantity}")
        if purchasing:
            rows.append([{
                "text": f"✅ {item['name']}",
                "callback_data": f"buy:{item_id}",
            }])
        else:
            rows.append([
                {"text": f"➕ {item['name']}", "callback_data": f"add:{item_id}"},
                {"text": "🗑", "callback_data": f"remove:{item_id}"},
            ])
    rows.append([{"text": "➕ Add Items", "callback_data": "categories"}])
    rows.append([{"text": "⬅️ Back", "callback_data": "home"}])
    _send(chat_id, "\n".join(lines), _inline(rows))


def _show_quantity(chat_id, item_id):
    item = CATALOG.get(item_id)
    if not item:
        _show_shopping(chat_id, purchasing=True)
        return
    rows = [[
        {"text": str(quantity), "callback_data": f"qty:{item_id}:{quantity}"}
        for quantity in (1, 2, 3, 4)
    ], [{"text": "⬅️ Back", "callback_data": "purchase-list"}]]
    _send(chat_id, f"How many units of “{item['name']}” did you buy?", _inline(rows))


def _show_due(chat_id):
    payload = STORE.load()
    stats = consumption_stats(payload)
    rows = []
    lines = ["⚠️ Items that may be running low based on past purchases:"]
    for item_id, row in sorted(stats.items(), key=lambda entry: entry[1]["next_date"] or date.max):
        if not row["due"] or item_id in payload["shopping"]:
            continue
        item = CATALOG[item_id]
        lines.append(f"• {item['name']} — about every {row['average_days']} days")
        rows.append([{
            "text": f"➕ {item['name']}",
            "callback_data": f"add:{item_id}",
        }])
    if not rows:
        _send(chat_id, "✅ No items are currently predicted to be running low.\nPredictions improve as purchases are recorded.", _main_menu())
        return
    rows.append([{"text": "⬅️ Back", "callback_data": "home"}])
    _send(chat_id, "\n".join(lines), _inline(rows))


def _show_trends(chat_id):
    payload = STORE.load()
    stats = consumption_stats(payload)
    learned = [
        (item_id, row) for item_id, row in stats.items() if row["average_days"]
    ]
    learned.sort(key=lambda entry: entry[1]["average_days"])
    if not learned:
        _send(
            chat_id,
            "📊 Record at least two purchases of an item to calculate its consumption trend.",
            _main_menu(),
        )
        return
    lines = ["📊 Household consumption trends:"]
    for item_id, row in learned[:20]:
        next_text = row["next_date"].strftime("%Y-%m-%d") if row["next_date"] else "—"
        lines.append(
            f"• {CATALOG[item_id]['name']}: every {row['average_days']} days | next purchase around {next_text}"
        )
    _send(chat_id, "\n".join(lines), _main_menu())


def _show_history(chat_id):
    rows = STORE.load()["purchases"][-20:]
    if not rows:
        _send(chat_id, "📜 No purchases have been recorded yet.", _main_menu())
        return
    lines = ["📜 Recent purchases:"]
    for row in reversed(rows):
        purchased = _parse_day(row.get("purchased_at"))
        when = purchased.strftime("%Y-%m-%d") if purchased else "—"
        lines.append(f"• {row.get('name', 'Item')} — Qty. {row.get('quantity', 1)} — {when}")
    _send(chat_id, "\n".join(lines), _main_menu())


def handle_update(data):
    callback = data.get("callback_query") or {}
    message = data.get("message") or {}
    actor = (callback.get("from") or message.get("from") or {}).get("id")
    source_message = callback.get("message") or message
    chat_id = (source_message.get("chat") or {}).get("id")
    if not actor or not chat_id:
        return
    if not _authorized(actor):
        _send(chat_id, "⛔ This bot is private.")
        return

    if callback:
        callback_id = callback.get("id")
        action = str(callback.get("data") or "")
        if action == "home":
            _answer_callback(callback_id)
            _show_home(chat_id)
        elif action == "categories":
            _answer_callback(callback_id)
            _show_categories(chat_id)
        elif action.startswith("category:"):
            _answer_callback(callback_id)
            _show_catalog(chat_id, action.split(":", 1)[1])
        elif action.startswith("add:"):
            item_id = action.split(":", 1)[1]
            if item_id in CATALOG:
                STORE.add_to_list(item_id)
                _answer_callback(callback_id, f"{CATALOG[item_id]['name']} added")
                _show_catalog(chat_id, CATALOG[item_id]["category"])
        elif action.startswith("remove:"):
            _answer_callback(callback_id, "Removed from the list")
            STORE.remove_from_list(action.split(":", 1)[1])
            _show_shopping(chat_id)
        elif action == "purchase-list":
            _answer_callback(callback_id)
            _show_shopping(chat_id, purchasing=True)
        elif action.startswith("buy:"):
            _answer_callback(callback_id)
            _show_quantity(chat_id, action.split(":", 1)[1])
        elif action.startswith("qty:"):
            _, item_id, quantity = action.split(":", 2)
            if item_id in CATALOG and quantity.isdigit():
                name = CATALOG[item_id]["name"]
                STORE.record_purchase(item_id, int(quantity))
                _answer_callback(callback_id, f"Purchase recorded: {name}")
                _show_shopping(chat_id, purchasing=True)
        else:
            _answer_callback(callback_id)
        return

    text = str(message.get("text") or "").strip()
    if text in ("/start", "/menu", "🏠 Main Menu"):
        _show_home(chat_id)
    elif text == "🛒 Shopping List":
        _show_shopping(chat_id)
    elif text == "➕ Add Items":
        _show_categories(chat_id)
    elif text == "✅ Record Purchase":
        _show_shopping(chat_id, purchasing=True)
    elif text == "⚠️ Running Low":
        _show_due(chat_id)
    elif text == "📊 Consumption Trends":
        _show_trends(chat_id)
    elif text == "📜 Purchase History":
        _show_history(chat_id)
    else:
        _send(chat_id, "Please choose one of the buttons.", _main_menu())


def _configure_telegram():
    if not BOT_TOKEN or not PUBLIC_URL:
        return {"ok": False, "description": "token_or_public_url_missing"}
    webhook = {
        "url": f"{PUBLIC_URL}/webhook/household",
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": False,
    }
    if WEBHOOK_SECRET:
        webhook["secret_token"] = WEBHOOK_SECRET
    webhook_result = _telegram("setWebhook", **webhook)
    commands_result = _telegram(
        "setMyCommands",
        commands=[
            {"command": "start", "description": "Open the home manager"},
            {"command": "menu", "description": "Show the main menu"},
        ],
    )
    logger.info("HOUSEHOLD BOT SETUP webhook=%s commands=%s", webhook_result.get("ok"), commands_result.get("ok"))
    return {"ok": bool(webhook_result.get("ok") and commands_result.get("ok")), "webhook": webhook_result, "commands": commands_result}


def init_household_bot(app):
    """Register routes once; safely do nothing when the token is absent."""
    if app.config.get("HOUSEHOLD_BOT_REGISTERED") or not BOT_TOKEN:
        if not BOT_TOKEN:
            logger.info("HOUSEHOLD BOT inactive: HOUSEHOLD_BOT_TOKEN not configured")
        return False
    app.config["HOUSEHOLD_BOT_REGISTERED"] = True

    @app.post("/webhook/household")
    def household_webhook():
        if WEBHOOK_SECRET:
            supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not hmac.compare_digest(supplied, WEBHOOK_SECRET):
                return "forbidden", 403
        data = request.get_json(force=True, silent=True)
        if data:
            threading.Thread(target=handle_update, args=(data,), daemon=True).start()
        return "ok", 200

    @app.get("/setup/household")
    def household_setup():
        if not SETUP_SECRET or not hmac.compare_digest(request.args.get("key", ""), SETUP_SECRET):
            return "forbidden", 403
        return jsonify(_configure_telegram())

    @app.get("/status/household")
    def household_status():
        if not SETUP_SECRET or not hmac.compare_digest(request.args.get("key", ""), SETUP_SECRET):
            return "forbidden", 403
        payload = STORE.load()
        return jsonify({
            "status": "ok",
            "shopping_items": len(payload["shopping"]),
            "purchase_records": len(payload["purchases"]),
        })

    # A fresh token or URL activates itself on the next Railway deployment.
    threading.Thread(target=_configure_telegram, daemon=True).start()
    logger.info("HOUSEHOLD BOT routes registered")
    return True
