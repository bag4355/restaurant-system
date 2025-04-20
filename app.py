import os, json, threading, time
from flask import (
    Flask, request, render_template, redirect,
    url_for, flash, session
)
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__, static_folder="static")
app.secret_key = os.urandom(24)

ADMIN_ID   = os.getenv("ADMIN_ID")
ADMIN_PW   = os.getenv("ADMIN_PW")
KITCHEN_ID = os.getenv("KITCHEN_ID")
KITCHEN_PW = os.getenv("KITCHEN_PW")

DATA_FILE = os.path.join(os.path.dirname(__file__), 'orders.json')

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "menuItems": [
                {"id":1, "name":"메인안주A", "price":12000, "category":"main",  "soldOut":False, "stock":10, "stockBeforeSoldOut":None},
                {"id":2, "name":"메인안주B", "price":15000, "category":"main",  "soldOut":False, "stock":7,  "stockBeforeSoldOut":None},
                {"id":3, "name":"소주",       "price":4000,  "category":"soju",  "soldOut":False, "stock":100,"stockBeforeSoldOut":None},
                {"id":4, "name":"맥주(1L)",   "price":8000,  "category":"beer",  "soldOut":False, "stock":50, "stockBeforeSoldOut":None},
                {"id":5, "name":"콜라",       "price":2000,  "category":"drink", "soldOut":False, "stock":40, "stockBeforeSoldOut":None},
                {"id":6, "name":"사이다",     "price":2000,  "category":"drink", "soldOut":False, "stock":40, "stockBeforeSoldOut":None},
                {"id":7, "name":"생수",       "price":1000,  "category":"drink", "soldOut":False, "stock":50, "stockBeforeSoldOut":None}
            ],
            "orders": [],
            "logs": []
        }
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(d):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def add_log(action, detail):
    d = load_data()
    d["logs"].append({
        "time": int(time.time()),
        "role": session.get("role","unknown"),
        "action": action,
        "detail": detail
    })
    save_data(d)

def generate_order_id():
    """
    기존 주문들 중 최대 ID를 찾아 +1 반환.
    (파일에 별도 카운터 저장이 필요 없습니다)
    """
    d = load_data()
    ids = [o["id"] for o in d["orders"] if isinstance(o.get("id"), int)]
    max_id = max(ids) if ids else 0
    return max_id + 1

def calculate_total_price(items):
    d = load_data()
    total = 0
    for it in items:
        m = next((m for m in d["menuItems"] if m["name"]==it["menuName"]), None)
        if m:
            total += m["price"] * it["quantity"]
    return total

def login_required():
    def wrapper(fn):
        def inner(*args, **kwargs):
            if "role" not in session:
                flash("로그인 후 이용 가능합니다.")
                return redirect(url_for("login"))
            return fn(*args, **kwargs)
        inner.__name__ = fn.__name__
        return inner
    return wrapper

def time_checker():
    while True:
        time.sleep(60)
        d = load_data()
        changed = False
        now = int(time.time())
        for o in d["orders"]:
            if o["status"]=="paid" and o.get("confirmedAt"):
                diff = (now - o["confirmedAt"])//60
                if diff>=50 and not o.get("alertFifty"):
                    o["alertFifty"]=True; changed=True
                    print(f"[알림] 50분 경과 주문ID={o['id']}")
                if diff>=60 and not o.get("alertSixty"):
                    o["alertSixty"]=True; changed=True
                    print(f"[알림] 60분 경과 주문ID={o['id']}")
        if changed:
            save_data(d)

threading.Thread(target=time_checker, daemon=True).start()

def get_current_sales(d):
    total=0
    for o in d["orders"]:
        if not o.get("service") and o["status"] in ("paid","completed"):
            total += o["totalPrice"]
    return total

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        uid = request.form.get("userid")
        pw  = request.form.get("userpw")
        if uid==ADMIN_ID and pw==ADMIN_PW:
            session["role"]="admin"; flash("관리자 로그인되었습니다.")
            return redirect(url_for("admin"))
        if uid==KITCHEN_ID and pw==KITCHEN_PW:
            session["role"]="kitchen"; flash("주방 로그인되었습니다.")
            return redirect(url_for("kitchen"))
        flash("로그인 실패: 아이디/비밀번호를 확인하세요.")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("role",None); flash("로그아웃 되었습니다.")
    return redirect(url_for("index"))

@app.route("/order", methods=["GET","POST"])
def order():
    d = load_data()
    if request.method=="POST":
        table   = request.form.get("tableNumber","")
        first   = (request.form.get("isFirstOrder")=="true")
        people  = int(request.form.get("peopleCount","0") or 0)
        notice  = (request.form.get("noticeChecked")=="on")

        items=[]
        for m in d["menuItems"]:
            qty=int(request.form.get(f"qty_{m['id']}","0") or 0)
            if qty>0:
                items.append({
                    "menuName": m["name"],
                    "quantity": qty,
                    "doneQuantity":0,
                    "deliveredQuantity":0
                })
        # (생략: validation as before, with flash("...", "error"))
        new_id = generate_order_id()
        total  = calculate_total_price(items)
        now    = int(time.time())
        order = {
            "id": new_id,
            "tableNumber": table,
            "peopleCount": people,
            "items": items,
            "totalPrice": total,
            "status":"pending",
            "createdAt":now,
            "confirmedAt":None,
            "alertFifty":False,
            "alertSixty":False,
            "kitchenDone":False,
            "service":False
        }
        d["orders"].append(order)
        save_data(d)
        flash(f"주문 접수되었습니다 (주문번호 {new_id}).")
        return render_template("order_result.html",
                               total_price=total,
                               order_id=new_id)
    return render_template("order_form.html", menu_items=d["menuItems"])

@app.route("/admin")
@login_required()
def admin():
    d = load_data()
    return render_template("admin.html",
        pending_orders   = [o for o in d["orders"] if o["status"]=="pending"],
        paid_orders      = [o for o in d["orders"] if o["status"]=="paid"],
        completed_orders = [o for o in d["orders"] if o["status"]=="completed"],
        menu_items       = d["menuItems"],
        current_sales    = get_current_sales(d)
    )

@app.route("/admin/confirm/<int:order_id>", methods=["POST"])
@login_required()
def admin_confirm(order_id):
    d = load_data()
    o = next((x for x in d["orders"] if x["id"]==order_id), None)
    if o and o["status"]=="pending":
        o["status"]="paid"; o["confirmedAt"]=int(time.time())
        # 재고 차감 + 음료류 자동 조리완료
        for it in o["items"]:
            mm=next(m for m in d["menuItems"] if m["name"]==it["menuName"])
            mm["stock"]-=it["quantity"]
            if mm["category"] in ("soju","beer","drink"):
                it["doneQuantity"]=it["quantity"]
        save_data(d); add_log("CONFIRM_ORDER",f"주문ID={order_id}")
        flash(f"주문 {order_id} 입금확인 완료!")
    return redirect(url_for("admin"))

@app.route("/admin/complete/<int:order_id>", methods=["POST"])
@login_required()
def admin_complete(order_id):
    d = load_data()
    o = next((x for x in d["orders"] if x["id"]==order_id), None)
    if o and o["status"]=="paid":
        o["status"]="completed"; save_data(d)
        add_log("COMPLETE_ORDER",f"주문ID={order_id}")
        flash(f"주문 {order_id} 최종 완료!")
    return redirect(url_for("admin"))

@app.route("/admin/deliver/<int:order_id>/<menu_name>", methods=["POST"])
@login_required()
def admin_deliver_item(order_id, menu_name):
    d = load_data()
    o = next(x for x in d["orders"] if x["id"]==order_id)
    if o["status"] in ("paid","completed"):
        it=next(i for i in o["items"] if i["menuName"]==menu_name)
        if it["deliveredQuantity"]<it["doneQuantity"]:
            it["deliveredQuantity"]+=1
            add_log("ADMIN_DELIVER_ITEM",f"{order_id}/{menu_name}")
            flash(f"{order_id}번 주문 {menu_name} 1개 전달!")
        if all(i["deliveredQuantity"]>=i["quantity"] for i in o["items"]):
            o["status"]="completed"
        save_data(d)
    return redirect(url_for("admin"))

@app.route("/admin/soldout/<int:menu_id>", methods=["POST"])
@login_required()
def admin_soldout(menu_id):
    d = load_data()
    m = next(x for x in d["menuItems"] if x["id"]==menu_id)
    if not m["soldOut"]:
        m["soldOut"]=True; m["stockBeforeSoldOut"]=m["stock"]
    else:
        m["soldOut"]=False
        if m["stockBeforeSoldOut"] is not None:
            m["stock"]=m["stockBeforeSoldOut"]
            m["stockBeforeSoldOut"]=None
    save_data(d)
    add_log("SOLDOUT_TOGGLE",f"{m['name']} soldOut={m['soldOut']}")
    flash(f"메뉴[{m['name']}] 품절토글!")
    return redirect(url_for("admin"))

@app.route("/admin/log")
@login_required()
def admin_log_page():
    logs=sorted(load_data()["logs"],key=lambda x:x["time"],reverse=True)
    return render_template("admin_log.html",logs=logs)

@app.route("/kitchen")
@login_required()
def kitchen():
    d = load_data()
    paid_orders = sorted(
        [o for o in d["orders"] if o["status"]=="paid"],
        key=lambda x: x.get("confirmedAt",0)
    )
    item_count={}
    for o in paid_orders:
        for it in o["items"]:
            left=it["quantity"]-it["doneQuantity"]
            if left>0:
                item_count[it["menuName"]] = item_count.get(it["menuName"],0) + left
    return render_template("kitchen.html",
                           paid_orders=paid_orders,
                           kitchen_status=item_count)

@app.route("/kitchen/done-item/<int:order_id>/<menu_name>", methods=["POST"])
@login_required()
def kitchen_done_item(order_id, menu_name):
    d = load_data()
    o = next(x for x in d["orders"] if x["id"]==order_id)
    it=next(i for i in o["items"] if i["menuName"]==menu_name)
    if it["doneQuantity"]<it["quantity"]:
        it["doneQuantity"]+=1
        add_log("KITCHEN_DONE_ITEM",f"{order_id}/{menu_name}")
        if all(i["doneQuantity"]>=i["quantity"] for i in o["items"]):
            o["kitchenDone"]=True
        save_data(d)
    return redirect(url_for("kitchen"))

if __name__=="__main__":
    port = int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
