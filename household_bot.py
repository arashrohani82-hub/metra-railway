"""Button-first Telegram bot for household shopping and consumption tracking."""
from __future__ import annotations
import hmac,json,logging,os,statistics,threading
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import requests
from flask import jsonify,request
logger=logging.getLogger(__name__)
BOT_TOKEN=os.environ.get("HOUSEHOLD_BOT_TOKEN","").strip(); WEBHOOK_SECRET=os.environ.get("HOUSEHOLD_WEBHOOK_SECRET","").strip(); SETUP_SECRET=os.environ.get("HOUSEHOLD_SETUP_SECRET",os.environ.get("SETUP_SECRET","")).strip()
PUBLIC_URL=os.environ.get("HOUSEHOLD_PUBLIC_URL",os.environ.get("PUBLIC_URL",os.environ.get("ODS_PUBLIC_URL",""))).strip().rstrip("/")
if not PUBLIC_URL and os.environ.get("RAILWAY_PUBLIC_DOMAIN"): PUBLIC_URL=f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN'].strip()}"
ALLOWED_USERS={int(v.strip()) for v in os.environ.get("HOUSEHOLD_ALLOWED_TELEGRAM_USER_IDS",os.environ.get("ALLOWED_TELEGRAM_USER_IDS","")).split(",") if v.strip().isdigit()}
DATA_FILE=Path(os.environ.get("DATA_DIR","/data"))/"household_purchases.json"
CATEGORIES={
"dairy":("🥛 Dairy & Breakfast",["Milk","Yogurt","Cheese","Butter","Eggs","Bread","Breakfast cereal"]),
"produce":("🍎 Fruit & Vegetables",["Bananas","Apples","Oranges","Strawberries","Cucumbers","Tomatoes","Potatoes","Onions","Vegetables","Salad"]),
"protein":("🍗 Meat & Protein",["Chicken","Beef","Fish","Tuna","Legumes"]),
"pantry":("🧺 Pantry",["Rice","Pasta","Cooking oil","Flour","Sugar","Salt","Coffee","Tea","Tomato paste","Napkins"]),
"drinks":("🧃 Drinks",["Bottled water","Juice","Soft drinks","Sparkling water"]),
"cleaning":("🧽 Home Cleaning",["Dish soap","Dishwasher tablets","Laundry detergent","Fabric softener","Hand soap","Surface cleaner","Garbage bags","Paper towels","Toilet paper"]),
"personal":("🧴 Personal Care",["Shampoo","Soap","Toothpaste","Toothbrushes","Deodorant","Razors"]),
"arvin":("🧒 Arvin",["School snacks","Arvin's juice","Wet wipes","School supplies"])}
def _item_id(c,i):return f"{c}-{i}"
CATALOG={_item_id(c,i):{"name":n,"category":c} for c,(_,names) in CATEGORIES.items() for i,n in enumerate(names)}
DEFAULT_UNITS={"Milk":"L","Yogurt":"pack","Cheese":"g","Butter":"g","Eggs":"pcs","Bread":"loaf","Breakfast cereal":"box","Bananas":"kg","Apples":"kg","Oranges":"kg","Strawberries":"pack","Cucumbers":"pcs","Tomatoes":"kg","Potatoes":"kg","Onions":"kg","Vegetables":"kg","Salad":"pack","Chicken":"kg","Beef":"kg","Fish":"kg","Tuna":"can","Legumes":"can","Rice":"kg","Pasta":"pack","Cooking oil":"L","Flour":"kg","Sugar":"kg","Salt":"pack","Coffee":"g","Tea":"box","Tomato paste":"can","Napkins":"pack","Bottled water":"pack","Juice":"L","Soft drinks":"pack","Sparkling water":"pack","Dish soap":"bottle","Dishwasher tablets":"pcs","Laundry detergent":"L","Fabric softener":"L","Hand soap":"bottle","Surface cleaner":"bottle","Garbage bags":"pcs","Paper towels":"roll","Toilet paper":"roll","Shampoo":"bottle","Soap":"pcs","Toothpaste":"tube","Toothbrushes":"pcs","Deodorant":"pcs","Razors":"pcs","School snacks":"pack","Arvin's juice":"pack","Wet wipes":"pack","School supplies":"pcs"}
def default_unit(i):return DEFAULT_UNITS.get(CATALOG.get(i,{}).get("name"),"pcs")
def _now_iso():return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _parse_day(v):
 try:return datetime.fromisoformat(str(v).replace("Z","+00:00")).date()
 except (TypeError,ValueError):return None
def _day_iso(d):return datetime(d.year,d.month,d.day,12,0,tzinfo=timezone.utc).isoformat(timespec="seconds")
def _num(v):
 n=float(v);return int(n) if n.is_integer() else n
def _fmt(v):
 try:
  n=float(v);return str(int(n)) if n.is_integer() else f"{n:g}"
 except (TypeError,ValueError):return str(v)
class HouseholdStore:
 def __init__(self,path=DATA_FILE):self.path,self.lock=Path(path),threading.RLock()
 @staticmethod
 def blank():return {"shopping":{},"purchases":[],"sessions":{}}
 def load(self):
  with self.lock:
   try:p=json.loads(self.path.read_text(encoding="utf-8"))
   except (FileNotFoundError,json.JSONDecodeError,OSError):p=self.blank()
   if not isinstance(p,dict):p=self.blank()
   p.setdefault("shopping",{});p.setdefault("purchases",[]);p.setdefault("sessions",{});return p
 def save(self,p):
  with self.lock:
   self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_suffix(".tmp");tmp.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding="utf-8");tmp.replace(self.path)
 def add_to_list(self,i):
  with self.lock:
   p=self.load();r=dict(p["shopping"].get(i) or {});r["quantity"]=r.get("quantity") or 1;r["unit"]=default_unit(i);r["added_at"]=r.get("added_at") or _now_iso();p["shopping"][i]=r;self.save(p)
 def remove_from_list(self,i):
  with self.lock:p=self.load();p["shopping"].pop(i,None);self.save(p)
 def record_purchase(self,i,q,purchased_at=None):
  with self.lock:
   p=self.load();item=CATALOG[i];p["purchases"].append({"item_id":i,"name":item["name"],"quantity":_num(q),"unit":default_unit(i),"purchased_at":purchased_at or _now_iso()});p["purchases"]=p["purchases"][-3000:];p["shopping"].pop(i,None);self.save(p)
 def set_session(self,c,**v):
  with self.lock:p=self.load();s=dict(p["sessions"].get(str(c)) or {});s.update(v);p["sessions"][str(c)]=s;self.save(p)
 def session(self,c):return dict(self.load()["sessions"].get(str(c)) or {})
 def clear_session(self,c):
  with self.lock:p=self.load();p["sessions"].pop(str(c),None);self.save(p)
STORE=HouseholdStore()
def consumption_stats(p,today=None):
 today=today or date.today();g={}
 for r in p.get("purchases",[]):
  i,d=r.get("item_id"),_parse_day(r.get("purchased_at"))
  if i in CATALOG and d:g.setdefault(i,[]).append(d)
 out={}
 for i,days in g.items():
  u=sorted(set(days));ints=[(b-a).days for a,b in zip(u,u[1:]) if (b-a).days>0];avg=int(round(statistics.median(ints))) if ints else None;nxt=u[-1]+timedelta(days=avg) if avg else None;out[i]={"average_days":avg,"last_date":u[-1],"next_date":nxt,"due":bool(nxt and nxt<=today+timedelta(days=3))}
 return out
def _main_menu():return {"keyboard":[[{"text":"🛒 Shopping List"},{"text":"➕ Add Items"}],[{"text":"✅ Record Purchase"},{"text":"⚠️ Running Low"}],[{"text":"📊 Consumption Trends"},{"text":"📜 Purchase History"}],[{"text":"🏠 Main Menu"}]],"resize_keyboard":True,"is_persistent":True,"input_field_placeholder":"Choose a button…"}
def _inline(rows):return {"inline_keyboard":rows}
def _category_keyboard():
 items=list(CATEGORIES.items());rows=[]
 for x in range(0,len(items),2):rows.append([{"text":label,"callback_data":f"category:{key}"} for key,(label,_) in items[x:x+2]])
 rows.append([{"text":"⬅️ Back","callback_data":"home"}]);return _inline(rows)
def _telegram(method,**payload):
 if not BOT_TOKEN:return {"ok":False}
 r=requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",json=payload,timeout=20)
 try:return r.json()
 except ValueError:return {"ok":False}
def _send(c,t,reply_markup=None):
 p={"chat_id":c,"text":t}
 if reply_markup:p["reply_markup"]=reply_markup
 return _telegram("sendMessage",**p)
def _answer(cid,text=""):return _telegram("answerCallbackQuery",callback_query_id=cid,text=text)
def _authorized(a):return bool(ALLOWED_USERS) and int(a) in ALLOWED_USERS
def _home(c):
 p=STORE.load();due=sum(1 for i,r in consumption_stats(p).items() if r["due"] and i not in p["shopping"]);_send(c,f"🏠 Home Shopping Manager\n\n🛒 {len(p['shopping'])} item(s) on the shopping list\n⚠️ {due} item(s) may be running low\n\nChoose an option:",_main_menu())
def _categories(c):_send(c,"Choose a category:",_category_keyboard())
def _catalog(c,cat):
 if cat not in CATEGORIES:return _categories(c)
 p=STORE.load();rows=[]
 for i,item in CATALOG.items():
  if item["category"]==cat:
   mark="✅ " if i in p["shopping"] else "➕ ";rows.append([{"text":f"{mark}{item['name']} ({default_unit(i)})","callback_data":f"add:{i}"}])
 rows.append([{"text":"⬅️ Categories","callback_data":"categories"}]);_send(c,CATEGORIES[cat][0],_inline(rows))
def _shopping(c,purchasing=False):
 p=STORE.load()
 if not p["shopping"]:return _send(c,"🛒 Your shopping list is empty.",_category_keyboard())
 lines=["✅ Select the item you purchased:" if purchasing else "🛒 Home shopping list:"];rows=[]
 for i,r in p["shopping"].items():
  if i not in CATALOG:continue
  name=CATALOG[i]["name"];u=default_unit(i);lines.append(f"• {name} ({u})")
  if purchasing:rows.append([{"text":f"✅ {name} ({u})","callback_data":f"buy:{i}"}])
  else:rows.append([{"text":f"{name} ({u})","callback_data":f"setqty:{i}"},{"text":"🗑","callback_data":f"remove:{i}"}])
 rows += [[{"text":"➕ Add Items","callback_data":"categories"}],[{"text":"⬅️ Back","callback_data":"home"}]];_send(c,"\n".join(lines),_inline(rows))
def _ask_quantity(c,i,mode="purchase"):
 u=default_unit(i);STORE.set_session(c,item_id=i,stage="quantity",mode=mode)
 _send(c,f"✏️ {CATALOG[i]['name']} ({u})\n\nEnter the amount in {u}:\nExample: 20 or 2.5",_inline([[{"text":"⬅️ Back","callback_data":"purchase-list" if mode=="purchase" else "shopping-list"}]]))
def _purchase_date(c,i):
 s=STORE.session(c);q=s.get("quantity");rows=[[{"text":"📅 Today","callback_data":f"pdate:{i}:0"}],[{"text":"📅 Yesterday","callback_data":f"pdate:{i}:1"}],[{"text":"📅 2 days ago","callback_data":f"pdate:{i}:2"}],[{"text":"⬅️ Change amount","callback_data":f"buy:{i}"}]];_send(c,f"{CATALOG[i]['name']} — {_fmt(q)} {default_unit(i)}\nSelect purchase date:",_inline(rows))
def _history(c):
 rows=STORE.load()["purchases"][-50:]
 if not rows:return _send(c,"📜 No purchases have been recorded yet.",_main_menu())
 lines=["📜 Recent purchases:"]
 for r in reversed(rows):
  d=_parse_day(r.get("purchased_at"));lines.append(f"• {r.get('name','Item')} — {_fmt(r.get('quantity',1))} {r.get('unit') or default_unit(r.get('item_id'))} — {d.strftime('%b %d, %Y') if d else '—'}")
 _send(c,"\n".join(lines),_main_menu())
def _due(c):
 p=STORE.load();rows=[];lines=["⚠️ Items that may be running low:"]
 for i,r in consumption_stats(p).items():
  if r["due"] and i not in p["shopping"]:lines.append(f"• {CATALOG[i]['name']}");rows.append([{"text":f"➕ {CATALOG[i]['name']} ({default_unit(i)})","callback_data":f"add:{i}"}])
 if not rows:return _send(c,"✅ No items are currently predicted to be running low.",_main_menu())
 rows.append([{"text":"⬅️ Back","callback_data":"home"}]);_send(c,"\n".join(lines),_inline(rows))
def _trends(c):
 learned=[(i,r) for i,r in consumption_stats(STORE.load()).items() if r["average_days"]]
 if not learned:return _send(c,"📊 Record at least two purchases of an item to calculate its consumption trend.",_main_menu())
 _send(c,"\n".join(["📊 Household consumption trends:"]+[f"• {CATALOG[i]['name']}: every {r['average_days']} days" for i,r in learned[:20]]),_main_menu())
def handle_update(data):
 cb=data.get("callback_query") or {};msg=data.get("message") or {};actor=(cb.get("from") or msg.get("from") or {}).get("id");source=cb.get("message") or msg;c=(source.get("chat") or {}).get("id")
 if not actor or not c:return
 if not _authorized(actor):return _send(c,"⛔ This bot is private.")
 if cb:
  cid=cb.get("id");a=str(cb.get("data") or "")
  if a=="home":STORE.clear_session(c);_answer(cid);_home(c)
  elif a=="categories":_answer(cid);_categories(c)
  elif a=="shopping-list":STORE.clear_session(c);_answer(cid);_shopping(c)
  elif a=="purchase-list":STORE.clear_session(c);_answer(cid);_shopping(c,True)
  elif a.startswith("category:"):_answer(cid);_catalog(c,a.split(":",1)[1])
  elif a.startswith("add:"):
   i=a.split(":",1)[1]
   if i in CATALOG:STORE.add_to_list(i);_answer(cid,"Added");_catalog(c,CATALOG[i]["category"])
  elif a.startswith("remove:"):STORE.remove_from_list(a.split(":",1)[1]);_answer(cid,"Removed");_shopping(c)
  elif a.startswith("buy:"):
   i=a.split(":",1)[1];STORE.clear_session(c);_answer(cid);_ask_quantity(c,i,"purchase")
  elif a.startswith("setqty:"):
   i=a.split(":",1)[1];STORE.clear_session(c);_answer(cid);_ask_quantity(c,i,"list")
  elif a.startswith("pdate:"):
   _,i,days=a.split(":",2);s=STORE.session(c)
   if i in CATALOG and days.isdigit() and s.get("quantity") is not None:
    d=date.today()-timedelta(days=int(days));q=s["quantity"];STORE.record_purchase(i,q,_day_iso(d));STORE.clear_session(c);_answer(cid,"Purchase recorded");_send(c,f"✅ Purchase recorded!\n{CATALOG[i]['name']} — {_fmt(q)} {default_unit(i)}\n📅 {d.strftime('%b %d, %Y')}",_main_menu())
  return
 text=str(msg.get("text") or "").strip();s=STORE.session(c)
 if s.get("stage")=="quantity" and s.get("item_id") in CATALOG and text!="🏠 Main Menu":
  try:q=float(text.replace(",","."))
  except ValueError:return _send(c,"Please enter a number only, for example 20 or 2.5.")
  if q<=0:return _send(c,"Please enter an amount greater than 0.")
  i=s["item_id"]
  if s.get("mode")=="list":
   p=STORE.load();p["shopping"][i]={"quantity":_num(q),"unit":default_unit(i),"added_at":p["shopping"].get(i,{}).get("added_at") or _now_iso()};STORE.save(p);STORE.clear_session(c);return _send(c,f"✅ {CATALOG[i]['name']} — {_fmt(q)} {default_unit(i)}",_main_menu())
  STORE.set_session(c,quantity=_num(q),stage="date");return _purchase_date(c,i)
 if text in ("/start","/menu","🏠 Main Menu"):STORE.clear_session(c);_home(c)
 elif text=="🛒 Shopping List":_shopping(c)
 elif text=="➕ Add Items":_categories(c)
 elif text=="✅ Record Purchase":_shopping(c,True)
 elif text=="⚠️ Running Low":_due(c)
 elif text=="📊 Consumption Trends":_trends(c)
 elif text=="📜 Purchase History":_history(c)
 else:_send(c,"Please choose one of the buttons.",_main_menu())
def _configure_telegram():
 if not BOT_TOKEN or not PUBLIC_URL:return {"ok":False,"description":"token_or_public_url_missing"}
 wh={"url":f"{PUBLIC_URL}/webhook/household","allowed_updates":["message","callback_query"],"drop_pending_updates":False}
 if WEBHOOK_SECRET:wh["secret_token"]=WEBHOOK_SECRET
 wr=_telegram("setWebhook",**wh);cr=_telegram("setMyCommands",commands=[{"command":"start","description":"Open the home manager"},{"command":"menu","description":"Show the main menu"}]);return {"ok":bool(wr.get("ok") and cr.get("ok")),"webhook":wr,"commands":cr}
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
  p=STORE.load();return jsonify({"status":"ok","shopping_items":len(p["shopping"]),"purchase_records":len(p["purchases"])})
 threading.Thread(target=_configure_telegram,daemon=True).start();logger.info("HOUSEHOLD BOT routes registered");return True
