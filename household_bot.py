"""Simple Telegram household purchase and consumption tracker."""
from __future__ import annotations
import hmac,json,logging,os,statistics,threading
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import requests
from flask import jsonify,request
logger=logging.getLogger(__name__)
BOT_TOKEN=os.environ.get("HOUSEHOLD_BOT_TOKEN","").strip(); WEBHOOK_SECRET=os.environ.get("HOUSEHOLD_WEBHOOK_SECRET","").strip(); SETUP_SECRET=os.environ.get("HOUSEHOLD_SETUP_SECRET",os.environ.get("SETUP_SECRET","")).strip()
PUBLIC_URL=os.environ.get("HOUSEHOLD_PUBLIC_URL",os.environ.get("PUBLIC_URL",os.environ.get("ODS_PUBLIC_URL",""))).strip().rstrip("/")
if not PUBLIC_URL and os.environ.get("RAILWAY_PUBLIC_DOMAIN"):PUBLIC_URL=f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN'].strip()}"
ALLOWED_USERS={int(v) for v in os.environ.get("HOUSEHOLD_ALLOWED_TELEGRAM_USER_IDS",os.environ.get("ALLOWED_TELEGRAM_USER_IDS","")).split(",") if v.strip().isdigit()}
DATA_FILE=Path(os.environ.get("DATA_DIR","/data"))/"household_purchases.json"
CATEGORIES={"dairy":("🥛 Dairy & Breakfast",["Milk","Yogurt","Cheese","Butter","Eggs","Bread","Breakfast cereal"]),"produce":("🍎 Fruit & Vegetables",["Bananas","Apples","Oranges","Strawberries","Cucumbers","Tomatoes","Potatoes","Onions","Vegetables","Salad"]),"protein":("🍗 Meat & Protein",["Chicken","Beef","Fish","Tuna","Legumes"]),"pantry":("🧺 Pantry",["Rice","Pasta","Cooking oil","Flour","Sugar","Salt","Coffee","Tea","Tomato paste","Napkins"]),"drinks":("🧃 Drinks",["Bottled water","Juice","Soft drinks","Sparkling water"]),"cleaning":("🧽 Home Cleaning",["Dish soap","Dishwasher tablets","Laundry detergent","Fabric softener","Hand soap","Surface cleaner","Garbage bags","Paper towels","Toilet paper"]),"personal":("🧴 Personal Care",["Shampoo","Soap","Toothpaste","Toothbrushes","Deodorant","Razors"]),"arvin":("🧒 Arvin",["School snacks","Arvin's juice","Wet wipes","School supplies"])}
def _iid(c,i):return f"{c}-{i}"
CATALOG={_iid(c,i):{"name":n,"category":c} for c,(_,ns) in CATEGORIES.items() for i,n in enumerate(ns)}
UNITS={"Milk":"L","Yogurt":"pack","Cheese":"g","Butter":"g","Eggs":"pcs","Bread":"loaf","Breakfast cereal":"box","Bananas":"kg","Apples":"kg","Oranges":"kg","Strawberries":"pack","Cucumbers":"pcs","Tomatoes":"kg","Potatoes":"kg","Onions":"kg","Vegetables":"kg","Salad":"pack","Chicken":"kg","Beef":"kg","Fish":"kg","Tuna":"can","Legumes":"can","Rice":"kg","Pasta":"pack","Cooking oil":"L","Flour":"kg","Sugar":"kg","Salt":"pack","Coffee":"g","Tea":"box","Tomato paste":"can","Napkins":"pack","Bottled water":"pack","Juice":"L","Soft drinks":"pack","Sparkling water":"pack","Dish soap":"bottle","Dishwasher tablets":"pcs","Laundry detergent":"L","Fabric softener":"L","Hand soap":"bottle","Surface cleaner":"bottle","Garbage bags":"pcs","Paper towels":"roll","Toilet paper":"roll","Shampoo":"bottle","Soap":"pcs","Toothpaste":"tube","Toothbrushes":"pcs","Deodorant":"pcs","Razors":"pcs","School snacks":"pack","Arvin's juice":"pack","Wet wipes":"pack","School supplies":"pcs"}
def unit(i):return UNITS.get(CATALOG.get(i,{}).get("name"),"pcs")
def day(v):
 try:return datetime.fromisoformat(str(v).replace("Z","+00:00")).date()
 except:return None
def dayiso(d):return datetime(d.year,d.month,d.day,12,tzinfo=timezone.utc).isoformat(timespec="seconds")
def fmt(v):
 try:n=float(v);return str(int(n)) if n.is_integer() else f"{n:g}"
 except:return str(v)
class Store:
 def __init__(self,path=DATA_FILE):self.path=Path(path);self.lock=threading.RLock()
 def load(self):
  with self.lock:
   try:p=json.loads(self.path.read_text(encoding="utf-8"))
   except:p={}
   p.setdefault("shopping",{});p.setdefault("purchases",[]);p.setdefault("sessions",{});return p
 def save(self,p):
  with self.lock:self.path.parent.mkdir(parents=True,exist_ok=True);t=self.path.with_suffix(".tmp");t.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding="utf-8");t.replace(self.path)
 def session(self,c):return dict(self.load()["sessions"].get(str(c)) or {})
 def set(self,c,**v):p=self.load();s=dict(p["sessions"].get(str(c)) or {});s.update(v);p["sessions"][str(c)]=s;self.save(p)
 def clear(self,c):p=self.load();p["sessions"].pop(str(c),None);self.save(p)
 def purchase(self,i,q,when):p=self.load();p["purchases"].append({"item_id":i,"name":CATALOG[i]["name"],"quantity":q,"unit":unit(i),"purchased_at":when});p["purchases"]=p["purchases"][-3000:];self.save(p)
 def edit(self,n,**v):
  p=self.load()
  if 0<=n<len(p["purchases"]):p["purchases"][n].update(v);self.save(p);return True
  return False
 def delete(self,n):
  p=self.load()
  if 0<=n<len(p["purchases"]):return p["purchases"].pop(n),self.save(p)
STORE=Store()
def stats(p,today=None):
 today=today or date.today();g={}
 for r in p.get("purchases",[]):
  i,d=r.get("item_id"),day(r.get("purchased_at"))
  if i in CATALOG and d:g.setdefault(i,[]).append(d)
 out={}
 for i,ds in g.items():
  u=sorted(set(ds));iv=[(b-a).days for a,b in zip(u,u[1:]) if b>a];avg=int(round(statistics.median(iv))) if iv else None;nxt=u[-1]+timedelta(days=avg) if avg else None;out[i]={"count":len(ds),"last":u[-1],"average_days":avg,"next":nxt,"due":bool(nxt and nxt<=today+timedelta(days=3))}
 return out
def menu():return {"keyboard":[[{"text":"➕ Record Purchase"}],[{"text":"📜 Purchase History"},{"text":"📊 Consumption"}]],"resize_keyboard":True,"is_persistent":True,"input_field_placeholder":"Choose an option…"}
def inline(rows):return {"inline_keyboard":rows}
def tg(method,**p):
 if not BOT_TOKEN:return {"ok":False}
 try:return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",json=p,timeout=20).json()
 except:return {"ok":False}
def send(c,t,rm=None):
 p={"chat_id":c,"text":t}
 if rm:p["reply_markup"]=rm
 return tg("sendMessage",**p)
def answer(cid,t=""):return tg("answerCallbackQuery",callback_query_id=cid,text=t)
def home(c):send(c,"🏠 Home Shopping Manager\n\nRecord what you buy. I’ll learn your household consumption over time.",menu())
def categories(c):
 items=list(CATEGORIES.items());rows=[]
 for x in range(0,len(items),2):rows.append([{"text":label,"callback_data":f"pcat:{key}"} for key,(label,_) in items[x:x+2]])
 rows.append([{"text":"⬅️ Back","callback_data":"home"}]);send(c,"➕ Record Purchase\nChoose a category:",inline(rows))
def catalog(c,cat):
 if cat not in CATEGORIES:return categories(c)
 rows=[[{"text":f"{it['name']} ({unit(i)})","callback_data":f"buy:{i}"}] for i,it in CATALOG.items() if it["category"]==cat];rows.append([{"text":"⬅️ Categories","callback_data":"purchase-categories"}]);send(c,CATEGORIES[cat][0],inline(rows))
def askqty(c,i):STORE.set(c,item_id=i,stage="quantity");send(c,f"✏️ {CATALOG[i]['name']} ({unit(i)})\n\nEnter the amount in {unit(i)}:\nExample: 20 or 2.5",inline([[{"text":"⬅️ Back","callback_data":f"pcat:{CATALOG[i]['category']}"}]]))
def askdate(c,i):
 s=STORE.session(c);q=s.get("quantity");rows=[[{"text":"📅 Today","callback_data":f"pdate:{i}:0"},{"text":"Yesterday","callback_data":f"pdate:{i}:1"}],[{"text":"2 days ago","callback_data":f"pdate:{i}:2"},{"text":"3 days ago","callback_data":f"pdate:{i}:3"}],[{"text":"⬅️ Change amount","callback_data":f"buy:{i}"}]];send(c,f"{CATALOG[i]['name']} — {fmt(q)} {unit(i)}\nSelect purchase date:",inline(rows))
def history(c):
 rs=STORE.load()["purchases"]
 if not rs:return send(c,"📜 No purchases recorded yet.",menu())
 rows=[]
 for n in range(len(rs)-1,max(-1,len(rs)-11),-1):
  r=rs[n];d=day(r.get("purchased_at"));label=f"{r.get('name','Item')} · {fmt(r.get('quantity',1))} {r.get('unit') or unit(r.get('item_id'))} · {d.strftime('%b %d') if d else '—'}";rows.append([{"text":label,"callback_data":f"hist:{n}"}])
 rows.append([{"text":"🏠 Main Menu","callback_data":"home"}]);send(c,"📜 Recent purchases\nTap a purchase to edit or delete it:",inline(rows))
def histitem(c,n):
 p=STORE.load();
 if not 0<=n<len(p["purchases"]):return history(c)
 r=p["purchases"][n];d=day(r.get("purchased_at"));send(c,f"🧾 {r.get('name','Item')}\nAmount: {fmt(r.get('quantity',1))} {r.get('unit') or unit(r.get('item_id'))}\nDate: {d.strftime('%b %d, %Y') if d else '—'}",inline([[{"text":"✏️ Edit amount","callback_data":f"hedit:{n}"},{"text":"📅 Edit date","callback_data":f"hdate:{n}"}],[{"text":"🗑 Delete","callback_data":f"hdelask:{n}"}],[{"text":"⬅️ History","callback_data":"history"}]]))
def consumption(c):
 st=stats(STORE.load())
 if not st:return send(c,"📊 Not enough data yet.\n\nRecord purchases and I’ll start learning after the second purchase of each item.",menu())
 lines=["📊 Consumption"]
 for i,r in sorted(st.items(),key=lambda x:x[1]["last"],reverse=True)[:25]:
  name=CATALOG[i]["name"];lines.append(f"• {name}: every ~{r['average_days']} days · {'⚠️ likely running low' if r['due'] else 'next ≈ '+r['next'].strftime('%b %d')}" if r["average_days"] else f"• {name}: 1 purchase · learning…")
 send(c,"\n".join(lines),menu())
def handle_update(data):
 cb=data.get("callback_query") or {};msg=data.get("message") or {};actor=(cb.get("from") or msg.get("from") or {}).get("id");src=cb.get("message") or msg;c=(src.get("chat") or {}).get("id")
 if not actor or not c:return
 if not ALLOWED_USERS or int(actor) not in ALLOWED_USERS:return send(c,"⛔ This bot is private.")
 if cb:
  cid=cb.get("id");a=str(cb.get("data") or "")
  if a=="home":STORE.clear(c);answer(cid);home(c)
  elif a=="history":answer(cid);history(c)
  elif a=="purchase-categories":answer(cid);categories(c)
  elif a.startswith("pcat:"):answer(cid);catalog(c,a.split(":",1)[1])
  elif a.startswith("buy:"):
   i=a.split(":",1)[1]
   if i in CATALOG:STORE.clear(c);answer(cid);askqty(c,i)
  elif a.startswith("pdate:"):
   _,i,n=a.split(":",2);s=STORE.session(c)
   if i in CATALOG and n.isdigit() and s.get("quantity") is not None:d=date.today()-timedelta(days=int(n));q=s["quantity"];STORE.purchase(i,q,dayiso(d));STORE.clear(c);answer(cid,"Purchase recorded");send(c,f"✅ Purchase recorded!\n{CATALOG[i]['name']} — {fmt(q)} {unit(i)}\n📅 {d.strftime('%b %d, %Y')}",menu())
  elif a.startswith("hist:"):answer(cid);histitem(c,int(a.split(":")[1]))
  elif a.startswith("hedit:"):
   n=int(a.split(":")[1]);p=STORE.load();answer(cid)
   if 0<=n<len(p["purchases"]):r=p["purchases"][n];STORE.set(c,stage="edit_amount",edit_index=n);send(c,f"✏️ {r['name']}\nCurrent: {fmt(r.get('quantity',1))} {r.get('unit','')}\nEnter the corrected amount:")
  elif a.startswith("hdate:"):
   n=int(a.split(":")[1]);STORE.set(c,stage="edit_date",edit_index=n);answer(cid);send(c,"📅 Select corrected purchase date:",inline([[{"text":"Today","callback_data":f"hedate:{n}:0"},{"text":"Yesterday","callback_data":f"hedate:{n}:1"}],[{"text":"2 days ago","callback_data":f"hedate:{n}:2"},{"text":"3 days ago","callback_data":f"hedate:{n}:3"}],[{"text":"⬅️ Cancel","callback_data":f"hist:{n}"}]]))
  elif a.startswith("hedate:"):
   _,n,x=a.split(":");n=int(n);d=date.today()-timedelta(days=int(x));STORE.edit(n,purchased_at=dayiso(d));STORE.clear(c);answer(cid,"Date updated");send(c,"✅ Purchase date updated.");histitem(c,n)
  elif a.startswith("hdelask:"):
   n=int(a.split(":")[1]);answer(cid);send(c,"Delete this purchase?",inline([[{"text":"🗑 Yes, delete","callback_data":f"hdel:{n}"},{"text":"Cancel","callback_data":f"hist:{n}"}]]))
  elif a.startswith("hdel:"):
   n=int(a.split(":")[1]);STORE.delete(n);STORE.clear(c);answer(cid,"Deleted");send(c,"🗑 Purchase deleted.");history(c)
  return
 text=str(msg.get("text") or "").strip();s=STORE.session(c)
 if s.get("stage") in ("quantity","edit_amount"):
  try:q=float(text.replace(",","."))
  except:return send(c,"Please enter a number only, for example 20 or 2.5.")
  if q<=0:return send(c,"Please enter an amount greater than 0.")
  q=int(q) if q.is_integer() else q
  if s.get("stage")=="edit_amount":
   n=int(s.get("edit_index",-1));STORE.edit(n,quantity=q);STORE.clear(c);send(c,"✅ Amount updated.");return histitem(c,n)
  i=s.get("item_id")
  if i in CATALOG:STORE.set(c,quantity=q,stage="date");return askdate(c,i)
 if text in ("/start","/menu","🏠 Main Menu"):STORE.clear(c);home(c)
 elif text=="➕ Record Purchase":STORE.clear(c);categories(c)
 elif text=="📜 Purchase History":history(c)
 elif text=="📊 Consumption":consumption(c)
 else:send(c,"Please choose one of the buttons.",menu())
def configure():
 if not BOT_TOKEN or not PUBLIC_URL:return {"ok":False,"description":"token_or_public_url_missing"}
 wh={"url":f"{PUBLIC_URL}/webhook/household","allowed_updates":["message","callback_query"],"drop_pending_updates":False}
 if WEBHOOK_SECRET:wh["secret_token"]=WEBHOOK_SECRET
 wr=tg("setWebhook",**wh);cr=tg("setMyCommands",commands=[{"command":"start","description":"Open Home Shopping Manager"},{"command":"menu","description":"Show main menu"}]);return {"ok":bool(wr.get("ok") and cr.get("ok")),"webhook":wr,"commands":cr}
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
  return jsonify(configure())
 @app.get("/status/household")
 def household_status():
  if not SETUP_SECRET or not hmac.compare_digest(request.args.get("key",""),SETUP_SECRET):return "forbidden",403
  p=STORE.load();return jsonify({"status":"ok","purchase_records":len(p["purchases"])})
 threading.Thread(target=configure,daemon=True).start();logger.info("HOUSEHOLD BOT routes registered");return True