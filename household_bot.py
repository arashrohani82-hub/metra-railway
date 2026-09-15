"""Button-only Telegram bot for household shopping and consumption tracking."""
from __future__ import annotations

import hmac
import json
import logging
import os
import statistics
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from flask import jsonify, request

logger = logging.getLogger(__name__)
BOT_TOKEN = os.environ.get("HOUSEHOLD_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.environ.get("HOUSEHOLD_WEBHOOK_SECRET", "").strip()
SETUP_SECRET = os.environ.get("HOUSEHOLD_SETUP_SECRET", os.environ.get("SETUP_SECRET", "")).strip()
PUBLIC_URL = os.environ.get("HOUSEHOLD_PUBLIC_URL", os.environ.get("PUBLIC_URL", os.environ.get("ODS_PUBLIC_URL", ""))).strip().rstrip("/")
if not PUBLIC_URL and os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    PUBLIC_URL = f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN'].strip()}"
ALLOWED_USERS = {int(v.strip()) for v in os.environ.get("HOUSEHOLD_ALLOWED_TELEGRAM_USER_IDS", os.environ.get("ALLOWED_TELEGRAM_USER_IDS", "")).split(",") if v.strip().isdigit()}
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_FILE = DATA_DIR / "household_purchases.json"

CATEGORIES = {
    "dairy": ("🥛 Dairy & Breakfast", ["Milk", "Yogurt", "Cheese", "Butter", "Eggs", "Bread", "Breakfast cereal"]),
    "produce": ("🍎 Fruit & Vegetables", ["Bananas", "Apples", "Oranges", "Strawberries", "Cucumbers", "Tomatoes", "Potatoes", "Onions", "Vegetables", "Salad"]),
    "protein": ("🍗 Meat & Protein", ["Chicken", "Beef", "Fish", "Tuna", "Legumes"]),
    "pantry": ("🧺 Pantry", ["Rice", "Pasta", "Cooking oil", "Flour", "Sugar", "Salt", "Coffee", "Tea", "Tomato paste", "Napkins"]),
    "drinks": ("🧃 Drinks", ["Bottled water", "Juice", "Soft drinks", "Sparkling water"]),
    "cleaning": ("🧽 Home Cleaning", ["Dish soap", "Dishwasher tablets", "Laundry detergent", "Fabric softener", "Hand soap", "Surface cleaner", "Garbage bags", "Paper towels", "Toilet paper"]),
    "personal": ("🧴 Personal Care", ["Shampoo", "Soap", "Toothpaste", "Toothbrushes", "Deodorant", "Razors"]),
    "arvin": ("🧒 Arvin", ["School snacks", "Arvin's juice", "Wet wipes", "School supplies"]),
}

def _item_id(category, index): return f"{category}-{index}"
CATALOG = {_item_id(c, i): {"name": n, "category": c} for c, (_, names) in CATEGORIES.items() for i, n in enumerate(names)}

UNIT_OPTIONS = {
    "Milk": ["L", "carton"], "Yogurt": ["pcs", "pack", "g"], "Cheese": ["g", "pack"], "Butter": ["g", "pack"],
    "Eggs": ["pcs", "dozen"], "Bread": ["loaf", "pack"], "Breakfast cereal": ["box", "g"],
    "Bananas": ["pcs", "kg"], "Apples": ["pcs", "kg"], "Oranges": ["pcs", "kg"], "Strawberries": ["pack", "g"],
    "Cucumbers": ["pcs", "kg"], "Tomatoes": ["pcs", "kg", "pack"], "Potatoes": ["kg", "bag"], "Onions": ["kg", "bag", "pcs"],
    "Vegetables": ["kg", "pack"], "Salad": ["pack", "pcs"], "Chicken": ["kg", "pack"], "Beef": ["kg", "pack"],
    "Fish": ["kg", "pack"], "Tuna": ["can", "pack"], "Legumes": ["can", "pack", "kg"], "Rice": ["kg", "bag"],
    "Pasta": ["pack", "g"], "Cooking oil": ["L", "bottle"], "Flour": ["kg", "bag"], "Sugar": ["kg", "bag"],
    "Salt": ["pack", "g"], "Coffee": ["g", "pack"], "Tea": ["box", "pack"], "Tomato paste": ["can", "jar"], "Napkins": ["pack"],
    "Bottled water": ["bottle", "pack", "L"], "Juice": ["L", "bottle", "carton"], "Soft drinks": ["can", "bottle", "pack"],
    "Sparkling water": ["bottle", "pack", "L"], "Dish soap": ["bottle", "mL"], "Dishwasher tablets": ["pcs", "pack"],
    "Laundry detergent": ["bottle", "L", "pack"], "Fabric softener": ["bottle", "L"], "Hand soap": ["bottle", "mL"],
    "Surface cleaner": ["bottle", "mL"], "Garbage bags": ["pcs", "box"], "Paper towels": ["roll", "pack"],
    "Toilet paper": ["roll", "pack"], "Shampoo": ["bottle", "mL"], "Soap": ["pcs", "pack"], "Toothpaste": ["tube", "pack"],
    "Toothbrushes": ["pcs", "pack"], "Deodorant": ["pcs", "pack"], "Razors": ["pcs", "pack"], "School snacks": ["pcs", "pack"],
    "Arvin's juice": ["box", "pack"], "Wet wipes": ["pack"], "School supplies": ["pcs", "pack"],
}

def units_for(item_id):
    return UNIT_OPTIONS.get(CATALOG.get(item_id, {}).get("name"), ["pcs"])

def default_unit(item_id): return units_for(item_id)[0]

def _now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _parse_day(value):
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError): return None

def _day_iso(day): return datetime(day.year, day.month, day.day, 12, 0, tzinfo=timezone.utc).isoformat(timespec="seconds")

class HouseholdStore:
    def __init__(self, path=DATA_FILE): self.path, self.lock = Path(path), threading.RLock()
    @staticmethod
    def blank(): return {"shopping": {}, "purchases": [], "sessions": {}}
    def load(self):
        with self.lock:
            try: payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError): payload = self.blank()
            if not isinstance(payload, dict): payload = self.blank()
            payload.setdefault("shopping", {}); payload.setdefault("purchases", []); payload.setdefault("sessions", {})
            return payload
    def save(self, payload):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"); tmp.replace(self.path)
    def add_to_list(self, item_id, quantity=1):
        with self.lock:
            p = self.load(); row = dict(p["shopping"].get(item_id) or {})
            row["quantity"] = int(row.get("quantity") or 0) + int(quantity); row["unit"] = row.get("unit") or default_unit(item_id); row["added_at"] = row.get("added_at") or _now_iso()
            p["shopping"][item_id] = row; self.save(p); return row
    def remove_from_list(self, item_id):
        with self.lock:
            p = self.load(); p["shopping"].pop(item_id, None); self.save(p)
    def record_purchase(self, item_id, quantity=1, unit=None, purchased_at=None):
        with self.lock:
            p = self.load(); item = CATALOG[item_id]
            p["purchases"].append({"item_id": item_id, "name": item["name"], "quantity": int(quantity), "unit": unit or default_unit(item_id), "purchased_at": purchased_at or _now_iso()})
            p["purchases"] = p["purchases"][-3000:]; p["shopping"].pop(item_id, None); self.save(p)
    def set_session(self, chat_id, **values):
        with self.lock:
            p = self.load(); s = dict(p["sessions"].get(str(chat_id)) or {}); s.update(values); p["sessions"][str(chat_id)] = s; self.save(p)
    def session(self, chat_id): return dict(self.load()["sessions"].get(str(chat_id)) or {})
    def clear_session(self, chat_id):
        with self.lock:
            p = self.load(); p["sessions"].pop(str(chat_id), None); self.save(p)

STORE = HouseholdStore()

def consumption_stats(payload, today=None):
    today = today or date.today(); grouped = {}
    for row in payload.get("purchases", []):
        item_id, purchased = row.get("item_id"), _parse_day(row.get("purchased_at"))
        if item_id in CATALOG and purchased: grouped.setdefault(item_id, []).append(purchased)
    result = {}
    for item_id, days in grouped.items():
        unique = sorted(set(days)); intervals = [(b-a).days for a,b in zip(unique, unique[1:]) if (b-a).days > 0]
        avg = int(round(statistics.median(intervals))) if intervals else None; nxt = unique[-1] + timedelta(days=avg) if avg else None
        result[item_id] = {"purchases": len(days), "average_days": avg, "last_date": unique[-1], "next_date": nxt, "due": bool(nxt and nxt <= today + timedelta(days=3))}
    return result

def _main_menu():
    return {"keyboard": [[{"text":"🛒 Shopping List"},{"text":"➕ Add Items"}],[{"text":"✅ Record Purchase"},{"text":"⚠️ Running Low"}],[{"text":"📊 Consumption Trends"},{"text":"📜 Purchase History"}],[{"text":"🏠 Main Menu"}]], "resize_keyboard":True,"is_persistent":True,"input_field_placeholder":"Choose a button…"}
def _inline(rows): return {"inline_keyboard": rows}
def _category_keyboard(action="category"):
    items=list(CATEGORIES.items()); rows=[]
    for i in range(0,len(items),2): rows.append([{"text":label,"callback_data":f"{action}:{key}"} for key,(label,_) in items[i:i+2]])
    rows.append([{"text":"⬅️ Back","callback_data":"home"}]); return _inline(rows)
def _telegram(method, **payload):
    if not BOT_TOKEN: return {"ok":False,"description":"HOUSEHOLD_BOT_TOKEN is missing"}
    r=requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",json=payload,timeout=20)
    try:return r.json()
    except ValueError:return {"ok":False,"description":r.text[:200]}
def _send(chat_id,text,reply_markup=None):
    p={"chat_id":chat_id,"text":text};
    if reply_markup:p["reply_markup"]=reply_markup
    return _telegram("sendMessage",**p)
def _answer_callback(callback_id,text=""): return _telegram("answerCallbackQuery",callback_query_id=callback_id,text=text)
def _authorized(actor_id): return bool(ALLOWED_USERS) and int(actor_id) in ALLOWED_USERS

def _show_home(chat_id):
    p=STORE.load(); stats=consumption_stats(p); due=sum(1 for i,r in stats.items() if r["due"] and i not in p["shopping"])
    _send(chat_id,f"🏠 Home Shopping Manager\n\n🛒 {len(p['shopping'])} item(s) on the shopping list\n⚠️ {due} item(s) may be running low\n\nChoose an option:",_main_menu())
def _show_categories(chat_id): _send(chat_id,"Choose a category:",_category_keyboard())
def _show_catalog(chat_id,category):
    info=CATEGORIES.get(category)
    if not info:return _show_categories(chat_id)
    p=STORE.load(); rows=[]
    for item_id,item in CATALOG.items():
        if item["category"]==category:
            q=int((p["shopping"].get(item_id) or {}).get("quantity") or 0); prefix=f"✅ {q} {default_unit(item_id)} " if q else "➕ "
            rows.append([{"text":prefix+item["name"],"callback_data":f"add:{item_id}"}])
    rows.append([{"text":"⬅️ Categories","callback_data":"categories"}]); _send(chat_id,f"{info[0]}\nTap an item to add it:",_inline(rows))
def _show_shopping(chat_id,purchasing=False):
    p=STORE.load(); shopping=p["shopping"]
    if not shopping:return _send(chat_id,"🛒 Your shopping list is empty.",_category_keyboard())
    lines=["✅ Select the items you purchased:" if purchasing else "🛒 Home shopping list:"]; rows=[]
    for item_id,row in shopping.items():
        item=CATALOG.get(item_id)
        if not item:continue
        q=int(row.get("quantity") or 1); unit=row.get("unit") or default_unit(item_id); lines.append(f"• {item['name']} — {q} {unit}")
        rows.append([{"text":f"✅ {item['name']}","callback_data":f"buy:{item_id}"}]) if purchasing else rows.append([{"text":f"➕ {item['name']}","callback_data":f"add:{item_id}"},{"text":"🗑","callback_data":f"remove:{item_id}"}])
    rows += [[{"text":"➕ Add Items","callback_data":"categories"}],[{"text":"⬅️ Back","callback_data":"home"}]]; _send(chat_id,"\n".join(lines),_inline(rows))
def _show_quantity(chat_id,item_id):
    item=CATALOG.get(item_id)
    if not item:return _show_shopping(chat_id,True)
    rows=[[{"text":str(q),"callback_data":f"qty:{item_id}:{q}"} for q in (1,2,3,4,6,10)],[{"text":"⬅️ Back","callback_data":"purchase-list"}]]
    _send(chat_id,f"How much “{item['name']}” did you buy?",_inline(rows))
def _show_units(chat_id,item_id):
    s=STORE.session(chat_id); q=s.get("quantity",1); opts=units_for(item_id); rows=[]
    for i in range(0,len(opts),3): rows.append([{"text":u,"callback_data":f"unit:{item_id}:{u}"} for u in opts[i:i+3]])
    rows.append([{"text":"⬅️ Back","callback_data":f"buy:{item_id}"}]); _send(chat_id,f"Quantity: {q}\nSelect the unit for {CATALOG[item_id]['name']}:",_inline(rows))
def _show_purchase_date(chat_id,item_id):
    today=date.today(); choices=[("Today",0),("Yesterday",1),("2 days ago",2),("3 days ago",3),("7 days ago",7)]
    rows=[[{"text":f"📅 {label}","callback_data":f"pdate:{item_id}:{days}"}] for label,days in choices]
    rows.append([{"text":"⬅️ Back","callback_data":f"units:{item_id}"}]); _send(chat_id,f"Purchase date for {CATALOG[item_id]['name']}:\nToday is {today.strftime('%b %d, %Y')}",_inline(rows))
def _show_history(chat_id):
    purchases=STORE.load()["purchases"][-50:]
    if not purchases:return _send(chat_id,"📜 No purchases have been recorded yet.",_main_menu())
    lines=["📜 Recent purchases:"]
    for row in reversed(purchases):
        d=_parse_day(row.get("purchased_at")); when=d.strftime("%b %d, %Y") if d else "—"; unit=row.get("unit") or default_unit(row.get("item_id"))
        lines.append(f"• {row.get('name','Item')} — {row.get('quantity',1)} {unit} — {when}")
    _send(chat_id,"\n".join(lines),_main_menu())
def _show_due(chat_id):
    p=STORE.load(); stats=consumption_stats(p); rows=[]; lines=["⚠️ Items that may be running low based on past purchases:"]
    for item_id,row in sorted(stats.items(),key=lambda e:e[1]["next_date"] or date.max):
        if row["due"] and item_id not in p["shopping"]:
            lines.append(f"• {CATALOG[item_id]['name']} — about every {row['average_days']} days"); rows.append([{"text":f"➕ {CATALOG[item_id]['name']}","callback_data":f"add:{item_id}"}])
    if not rows:return _send(chat_id,"✅ No items are currently predicted to be running low.\nPredictions improve as purchases are recorded.",_main_menu())
    rows.append([{"text":"⬅️ Back","callback_data":"home"}]); _send(chat_id,"\n".join(lines),_inline(rows))
def _show_trends(chat_id):
    stats=consumption_stats(STORE.load()); learned=[(i,r) for i,r in stats.items() if r["average_days"]]; learned.sort(key=lambda e:e[1]["average_days"])
    if not learned:return _send(chat_id,"📊 Record at least two purchases of an item to calculate its consumption trend.",_main_menu())
    lines=["📊 Household consumption trends:"]+[f"• {CATALOG[i]['name']}: every {r['average_days']} days | last {r['last_date'].strftime('%b %d, %Y')}" for i,r in learned[:20]]; _send(chat_id,"\n".join(lines),_main_menu())

def handle_update(data):
    cb=data.get("callback_query") or {}; msg=data.get("message") or {}; actor=(cb.get("from") or msg.get("from") or {}).get("id"); source=cb.get("message") or msg; chat_id=(source.get("chat") or {}).get("id")
    if not actor or not chat_id:return
    if not _authorized(actor):return _send(chat_id,"⛔ This bot is private.")
    if cb:
        cid=cb.get("id"); action=str(cb.get("data") or "")
        if action=="home": _answer_callback(cid); _show_home(chat_id)
        elif action=="categories": _answer_callback(cid); _show_categories(chat_id)
        elif action.startswith("category:"): _answer_callback(cid); _show_catalog(chat_id,action.split(":",1)[1])
        elif action.startswith("add:"):
            item_id=action.split(":",1)[1]
            if item_id in CATALOG: STORE.add_to_list(item_id); _answer_callback(cid,f"{CATALOG[item_id]['name']} added"); _show_catalog(chat_id,CATALOG[item_id]["category"])
        elif action.startswith("remove:"): _answer_callback(cid,"Removed"); STORE.remove_from_list(action.split(":",1)[1]); _show_shopping(chat_id)
        elif action=="purchase-list": _answer_callback(cid); _show_shopping(chat_id,True)
        elif action.startswith("buy:"): _answer_callback(cid); _show_quantity(chat_id,action.split(":",1)[1])
        elif action.startswith("qty:"):
            _,item_id,q=action.split(":",2)
            if item_id in CATALOG and q.isdigit(): STORE.set_session(chat_id,item_id=item_id,quantity=int(q)); _answer_callback(cid); _show_units(chat_id,item_id)
        elif action.startswith("units:"): _answer_callback(cid); _show_units(chat_id,action.split(":",1)[1])
        elif action.startswith("unit:"):
            _,item_id,unit=action.split(":",2)
            if item_id in CATALOG and unit in units_for(item_id): STORE.set_session(chat_id,unit=unit); _answer_callback(cid); _show_purchase_date(chat_id,item_id)
        elif action.startswith("pdate:"):
            _,item_id,days=action.split(":",2); s=STORE.session(chat_id)
            if item_id in CATALOG and days.isdigit():
                d=date.today()-timedelta(days=int(days)); q=int(s.get("quantity") or 1); unit=s.get("unit") or default_unit(item_id); STORE.record_purchase(item_id,q,unit,_day_iso(d)); STORE.clear_session(chat_id); _answer_callback(cid,"Purchase recorded"); _send(chat_id,f"✅ Purchase recorded!\n{CATALOG[item_id]['name']} — {q} {unit}\n📅 {d.strftime('%b %d, %Y')}",_main_menu())
        else:_answer_callback(cid)
        return
    text=str(msg.get("text") or "").strip()
    if text in ("/start","/menu","🏠 Main Menu"): _show_home(chat_id)
    elif text=="🛒 Shopping List": _show_shopping(chat_id)
    elif text=="➕ Add Items": _show_categories(chat_id)
    elif text=="✅ Record Purchase": _show_shopping(chat_id,True)
    elif text=="⚠️ Running Low": _show_due(chat_id)
    elif text=="📊 Consumption Trends": _show_trends(chat_id)
    elif text=="📜 Purchase History": _show_history(chat_id)
    else:_send(chat_id,"Please choose one of the buttons.",_main_menu())

def _configure_telegram():
    if not BOT_TOKEN or not PUBLIC_URL:return {"ok":False,"description":"token_or_public_url_missing"}
    webhook={"url":f"{PUBLIC_URL}/webhook/household","allowed_updates":["message","callback_query"],"drop_pending_updates":False}
    if WEBHOOK_SECRET:webhook["secret_token"]=WEBHOOK_SECRET
    wr=_telegram("setWebhook",**webhook); cr=_telegram("setMyCommands",commands=[{"command":"start","description":"Open the home manager"},{"command":"menu","description":"Show the main menu"}]); return {"ok":bool(wr.get("ok") and cr.get("ok")),"webhook":wr,"commands":cr}
def init_household_bot(app):
    if app.config.get("HOUSEHOLD_BOT_REGISTERED") or not BOT_TOKEN:return False
    app.config["HOUSEHOLD_BOT_REGISTERED"]=True
    @app.post("/webhook/household")
    def household_webhook():
        if WEBHOOK_SECRET and not hmac.compare_digest(request.headers.get("X-Telegram-Bot-Api-Secret-Token",""),WEBHOOK_SECRET):return "forbidden",403
        data=request.get_json(force=True,silent=True)
        if data:threading.Thread(target=handle_update,args=(data,),daemon=True).start()
        return "ok",200
    @app.get("/setup/household")
    def household_setup():
        if not SETUP_SECRET or not hmac.compare_digest(request.args.get("key",""),SETUP_SECRET):return "forbidden",403
        return jsonify(_configure_telegram())
    @app.get("/status/household")
    def household_status():
        if not SETUP_SECRET or not hmac.compare_digest(request.args.get("key",""),SETUP_SECRET):return "forbidden",403
        p=STORE.load(); return jsonify({"status":"ok","shopping_items":len(p["shopping"]),"purchase_records":len(p["purchases"])})
    threading.Thread(target=_configure_telegram,daemon=True).start(); logger.info("HOUSEHOLD BOT routes registered"); return True
