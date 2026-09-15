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
def _item_id(c,i): return f"{c}-{i}"
CATALOG={_item_id(c,i):{"name":n,"category":c} for c,(_,names) in CATEGORIES.items() for i,n in enumerate(names)}
UNIT_OPTIONS={
"Milk":["L","carton"],"Yogurt":["pcs","pack","g"],"Cheese":["g","pack"],"Butter":["g","pack"],"Eggs":["pcs","dozen"],"Bread":["loaf","pack"],"Breakfast cereal":["box","g"],
"Bananas":["pcs","kg"],"Apples":["pcs","kg"],"Oranges":["pcs","kg"],"Strawberries":["pack","g"],"Cucumbers":["pcs","kg"],"Tomatoes":["pcs","kg","pack"],"Potatoes":["kg","bag"],"Onions":["kg","bag","pcs"],"Vegetables":["kg","pack"],"Salad":["pack","pcs"],
"Chicken":["kg","pack"],"Beef":["kg","pack"],"Fish":["kg","pack"],"Tuna":["can","pack"],"Legumes":["can","pack","kg"],"Rice":["kg","bag"],"Pasta":["pack","g"],"Cooking oil":["L","bottle"],"Flour":["kg","bag"],"Sugar":["kg","bag"],"Salt":["pack","g"],"Coffee":["g","pack"],"Tea":["box","pack"],"Tomato paste":["can","jar"],"Napkins":["pack"],
"Bottled water":["bottle","pack","L"],"Juice":["L","bottle","carton"],"Soft drinks":["can","bottle","pack"],"Sparkling water":["bottle","pack","L"],"Dish soap":["bottle","mL"],"Dishwasher tablets":["pcs","pack"],"Laundry detergent":["bottle","L","pack"],"Fabric softener":["bottle","L"],"Hand soap":["bottle","mL"],"Surface cleaner":["bottle","mL"],"Garbage bags":["pcs","box"],"Paper towels":["roll","pack"],"Toilet paper":["roll","pack"],
"Shampoo":["bottle","mL"],"Soap":["pcs","pack"],"Toothpaste":["tube","pack"],"Toothbrushes":["pcs","pack"],"Deodorant":["pcs","pack"],"Razors":["pcs","pack"],"School snacks":["pcs","pack"],"Arvin's juice":["box","pack"],"Wet wipes":["pack"],"School supplies":["pcs","pack"]}
def units_for(i): return UNIT_OPTIONS.get(CATALOG.get(i,{}).get("name"),["pcs"])
def default_unit(i): return units_for(i)[0]
def _now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _parse_day(v):
 try:return datetime.fromisoformat(str(v).replace("Z","+00:00")).date()
 except (TypeError,ValueError):return None
def _day_iso(d): return datetime(d.year,d.month,d.day,12,0,tzinfo=timezone.utc).isoformat(timespec="seconds")
def _num(v):
 n=float(v); return int(n) if n.is_integer() else n
def _fmt(v):
 try:
  n=float(v); return str(int(n)) if n.is_integer() else f"{n:g}"
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
 def add_to_list(self,i,quantity=1):
  with self.lock:
   p=self.load();r=dict(p["shopping"].get(i) or {});r["quantity"]=float(r.get("quantity") or 0)+float(quantity);r["unit"]=r.get("unit") or default_unit(i);r["added_at"]=r.get("added_at") or _now_iso();p["shopping"][i]=r;self.save(p);return r
 def remove_from_list(self,i):
  with self.lock:p=self.load();p["shopping"].pop(i,None);self.save(p)
 def record_purchase(self,i,quantity=1,unit=None,purchased_at=None):
  with self.lock:
   p=self.load();item=CATALOG[i];p["purchases"].append({"item_id":i,"name":item["name"],"quantity":_num(quantity),"unit":unit or default_unit(i),"purchased_at":purchased_at or _now_iso()});p["purchases"]=p["purchases"][-3000:];p["shopping"].pop(i,None);self.save(p)
 def set_session(self,chat_id,**values):
  with self.lock:p=self.load();s=dict(p["sessions"].get(str(chat_id)) or {});s.update(values);p["sessions"][str(chat_id)]=s;self.save(p)
 def session(self,chat_id):return dict(self.load()["sessions"].get(str(chat_id)) or {})
 def clear_session(self,chat_id):
  with self.lock:p=self.load();p["sessions"].pop(str(chat_id),None);self.save(p)
STORE=HouseholdStore()
def consumption_stats(p,today=None):
 today=today or date.today();g={}
 for r in p.get("purchases",[]):
  i,d=r.get("item_id"),_parse_day(r.get("purchased_at"))
  if i in CATALOG and d:g.setdefault(i,[]).append(d)
 out={}
 for i,days in g.items():
  u=sorted(set(days));ints=[(b-a).days for a,b in zip(u,u[1:]) if (b-a).days>0];avg=int(round(statistics.median(ints))) if ints else None;nxt=u[-1]+timedelta(days=avg) if avg else None;out[i]={"purchases":len(days),"average_days":avg,"last_date":u[-1],"next_date":nxt,"due":bool(nxt and nxt<=today+timedelta(days=3))}
 return out
def _main_menu():return {"keyboard":[[{"text":"🛒 Shopping List"},{"text":"➕ Add Items"}],[{"text":"✅ Record Purchase"},{"text":"⚠️ Running Low"}],[{"text":"📊 Consumption Trends"},{"text":"📜 Purchase History"}],[{"text":"🏠 Main Menu"}]],"resize_keyboard":True,"is_persistent":True,"input_field_placeholder":"Choose a button…"}
def _inline(rows):return {"inline_keyboard":rows}
def _category_keyboard(action="category"):
 items=list(CATEGORIES.items());rows=[]
 for x in range(0,len(items),2):rows.append([{"text":label,"callback_data":f"{action}:{key}"} for key,(label,_) in items[x:x+2]])
 rows.append([{"text":"⬅️ Back","callback_data":"home"}]);return _inline(rows)
def _telegram(method,**payload):
 if not BOT_TOKEN:return {"ok":False,"description":"HOUSEHOLD_BOT_TOKEN is missing"}
 r=requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",json=payload,timeout=20)
 try:return r.json()
 except ValueError:return {"ok":False,"description":r.text[:200]}
def _send(chat_id,text,reply_markup=None):
 p={"chat_id":chat_id,"text":text}
 if reply_markup:p["reply_markup"]=reply_markup
 return _telegram("sendMessage",**p)
def _answer_callback(cid,text=""):return _telegram("answerCallbackQuery",callback_query_id=cid,text=text)
def _authorized(actor):return bool(ALLOWED_USERS) and int(actor) in ALLOWED_USERS
def _show_home(chat_id):
 p=STORE.load();st=consumption_stats(p);due=sum(1 for i,r in st.items() if r["due"] and i not in p["shopping"]);_send(chat_id,f"🏠 Home Shopping Manager\n\n🛒 {len(p['shopping'])} item(s) on the shopping list\n⚠️ {due} item(s) may be running low\n\nChoose an option:",_main_menu())
def _show_categories(chat_id):_send(chat_id,"Choose a category:",_category_keyboard())
def _show_catalog(chat_id,c):
 info=CATEGORIES.get(c)
 if not info:return _show_categories(chat_id)
 p=STORE.load();rows=[]
 for i,item in CATALOG.items():
  if item["category"]==c:
   q=(p["shopping"].get(i) or {}).get("quantity",0);prefix=f"✅ {_fmt(q)} {default_unit(i)} " if q else "➕ ";rows.append([{"text":prefix+item["name"],"callback_data":f"add:{i}"}])
 rows.append([{"text":"⬅️ Categories","callback_data":"categories"}]);_send(chat_id,f"{info[0]}\nTap an item to add it:",_inline(rows))
def _show_shopping(chat_id,purchasing=False):
 p=STORE.load();shopping=p["shopping"]
 if not shopping:return _send(chat_id,"🛒 Your shopping list is empty.",_category_keyboard())
 lines=["✅ Select the items you purchased:" if purchasing else "🛒 Home shopping list:"];rows=[]
 for i,r in shopping.items():
  item=CATALOG.get(i)
  if not item:continue
  q=r.get("quantity",1);u=r.get("unit") or default_unit(i);lines.append(f"• {item['name']} — {_fmt(q)} {u}");rows.append([{"text":f"✅ {item['name']}","callback_data":f"buy:{i}"}]) if purchasing else rows.append([{"text":f"➕ {item['name']}","callback_data":f"add:{i}"},{"text":"🗑","callback_data":f"remove:{i}"}])
 rows += [[{"text":"➕ Add Items","callback_data":"categories"}],[{"text":"⬅️ Back","callback_data":"home"}]];_send(chat_id,"\n".join(lines),_inline(rows))
def _ask_quantity(chat_id,i):
 item=CATALOG[i];s=STORE.session(chat_id);u=s.get("unit") or default_unit(i);STORE.set_session(chat_id,item_id=i,unit=u,stage="quantity")
 _send(chat_id,f"✏️ {item['name']}\nUnit: {u}\n\nType the quantity (for example: 20 or 2.5).",_inline([[{"text":f"🔄 Change Unit ({u})","callback_data":f"changeunit:{i}"}],[{"text":"⬅️ Back","callback_data":"purchase-list"}]]))
def _show_units(chat_id,i):
 opts=units_for(i);rows=[]
 for x in range(0,len(opts),3):rows.append([{"text":u,"callback_data":f"unit:{i}:{u}"} for u in opts[x:x+3]])
 rows.append([{"text":"⬅️ Back","callback_data":f"buy:{i}"}]);_send(chat_id,f"Select the unit for {CATALOG[i]['name']}:",_inline(rows))
def _show_purchase_date(chat_id,i):
 choices=[("Today",0),("Yesterday",1),("2 days ago",2),("3 days ago",3),("7 days ago",7)];rows=[[{"text":f"📅 {label}","callback_data":f"pdate:{i}:{days}"}] for label,days in choices];rows.append([{"text":"⬅️ Change quantity","callback_data":f"buy:{i}"}]);s=STORE.session(chat_id);_send(chat_id,f"{CATALOG[i]['name']} — {_fmt(s.get('quantity',1))} {s.get('unit') or default_unit(i)}\nSelect purchase date:",_inline(rows))
def _show_history(chat_id):
 rows=STORE.load()["purchases"][-50:]
 if not rows:return _send(chat_id,"📜 No purchases have been recorded yet.",_main_menu())
 lines=["📜 Recent purchases:"]
 for r in reversed(rows):
  d=_parse_day(r.get("purchased_at"));when=d.strftime("%b %d, %Y") if d else "—";u=r.get("unit") or default_unit(r.get("item_id"));lines.append(f"• {r.get('name','Item')} — {_fmt(r.get('quantity',1))} {u} — {when}")
 _send(chat_id,"\n".join(lines),_main_menu())
def _show_due(chat_id):
 p=STORE.load();st=consumption_stats(p);rows=[];lines=["⚠️ Items that may be running low based on past purchases:"]
 for i,r in sorted(st.items(),key=lambda e:e[1]["next_date"] or date.max):
  if r["due"] and i not in p["shopping"]:lines.append(f"• {CATALOG[i]['name']} — about every {r['average_days']} days");rows.append([{"text":f"➕ {CATALOG[i]['name']}","callback_data":f"add:{i}"}])
 if not rows:return _send(chat_id,"✅ No items are currently predicted to be running low.\nPredictions improve as purchases are recorded.",_main_menu())
 rows.append([{"text":"⬅️ Back","callback_data":"home"}]);_send(chat_id,"\n".join(lines),_inline(rows))
def _show_trends(chat_id):
 st=consumption_stats(STORE.load());learned=[(i,r) for i,r in st.items() if r["average_days"]];learned.sort(key=lambda e:e[1]["average_days"])
 if not learned:return _send(chat_id,"📊 Record at least two purchases of an item to calculate its consumption trend.",_main_menu())
 _send(chat_id,"\n".join(["📊 Household consumption trends:"]+[f"• {CATALOG[i]['name']}: every {r['average_days']} days | last {r['last_date'].strftime('%b %d, %Y')}" for i,r in learned[:20]]),_main_menu())
def handle_update(data):
 cb=data.get("callback_query") or {};msg=data.get("message") or {};actor=(cb.get("from") or msg.get("from") or {}).get("id");source=cb.get("message") or msg;chat_id=(source.get("chat") or {}).get("id")
 if not actor or not chat_id:return
 if not _authorized(actor):return _send(chat_id,"⛔ This bot is private.")
 if cb:
  cid=cb.get("id");a=str(cb.get("data") or "")
  if a=="home":STORE.clear_session(chat_id);_answer_callback(cid);_show_home(chat_id)
  elif a=="categories":_answer_callback(cid);_show_categories(chat_id)
  elif a.startswith("category:"):_answer_callback(cid);_show_catalog(chat_id,a.split(":",1)[1])
  elif a.startswith("add:"):
   i=a.split(":",1)[1]
   if i in CATALOG:STORE.add_to_list(i);_answer_callback(cid,f"{CATALOG[i]['name']} added");_show_catalog(chat_id,CATALOG[i]["category"])
  elif a.startswith("remove:"):_answer_callback(cid,"Removed");STORE.remove_from_list(a.split(":",1)[1]);_show_shopping(chat_id)
  elif a=="purchase-list":STORE.clear_session(chat_id);_answer_callback(cid);_show_shopping(chat_id,True)
  elif a.startswith("buy:"):
   i=a.split(":",1)[1];STORE.clear_session(chat_id);STORE.set_session(chat_id,item_id=i,unit=default_unit(i));_answer_callback(cid);_ask_quantity(chat_id,i)
  elif a.startswith("changeunit:"):
   i=a.split(":",1)[1];_answer_callback(cid);_show_units(chat_id,i)
  elif a.startswith("unit:"):
   _,i,u=a.split(":",2)
   if i in CATALOG and u in units_for(i):STORE.set_session(chat_id,item_id=i,unit=u);_answer_callback(cid);_ask_quantity(chat_id,i)
  elif a.startswith("pdate:"):
   _,i,days=a.split(":",2);s=STORE.session(chat_id)
   if i in CATALOG and days.isdigit() and s.get("quantity") is not None:
    d=date.today()-timedelta(days=int(days));q=s["quantity"];u=s.get("unit") or default_unit(i);STORE.record_purchase(i,q,u,_day_iso(d));STORE.clear_session(chat_id);_answer_callback(cid,"Purchase recorded");_send(chat_id,f"✅ Purchase recorded!\n{CATALOG[i]['name']} — {_fmt(q)} {u}\n📅 {d.strftime('%b %d, %Y')}",_main_menu())
  else:_answer_callback(cid)
  return
 text=str(msg.get("text") or "").strip();s=STORE.session(chat_id)
 if s.get("stage")=="quantity" and s.get("item_id") in CATALOG and text not in ("🏠 Main Menu",):
  try:q=float(text.replace(",","."))
  except ValueError:return _send(chat_id,"Please type a number only, for example 20 or 2.5.")
  if q<=0 or q>100000:return _send(chat_id,"Please enter a quantity greater than 0.")
  i=s["item_id"];STORE.set_session(chat_id,quantity=_num(q),stage="date");return _show_purchase_date(chat_id,i)
 if text in ("/start","/menu","🏠 Main Menu"):STORE.clear_session(chat_id);_show_home(chat_id)
 elif text=="🛒 Shopping List":_show_shopping(chat_id)
 elif text=="➕ Add Items":_show_categories(chat_id)
 elif text=="✅ Record Purchase":_show_shopping(chat_id,True)
 elif text=="⚠️ Running Low":_show_due(chat_id)
 elif text=="📊 Consumption Trends":_show_trends(chat_id)
 elif text=="📜 Purchase History":_show_history(chat_id)
 else:_send(chat_id,"Please choose one of the buttons.",_main_menu())
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
