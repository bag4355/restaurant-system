import os, json, threading, time
from flask import (
    Flask, request, render_template, redirect,
    url_for, flash, session
)
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__, static_folder="static")
app.secret_key = os.urandom(24)

# 환경변수
ADMIN_ID = os.getenv("ADMIN_ID")
ADMIN_PW = os.getenv("ADMIN_PW")
KITCHEN_ID = os.getenv("KITCHEN_ID")
KITCHEN_PW = os.getenv("KITCHEN_PW")

DATA_FILE = os.path.join(os.path.dirname(__file__), 'orders.json')

def load_data():
    """파일로부터 최신 상태 로드"""
    if not os.path.exists(DATA_FILE):
        # 기본 구조 생성
        return {
            "menuItems": [
                {"id":1,"name":"메인안주A","price":12000,"category":"main","soldOut":False},
                {"id":2,"name":"메인안주B","price":15000,"category":"main","soldOut":False},
                {"id":3,"name":"소주","price":4000,"category":"soju","soldOut":False},
                {"id":4,"name":"맥주(1L)","price":8000,"category":"beer","soldOut":False},
                {"id":5,"name":"콜라","price":2000,"category":"drink","soldOut":False},
                {"id":6,"name":"사이다","price":2000,"category":"drink","soldOut":False},
                {"id":7,"name":"생수","price":1000,"category":"drink","soldOut":False},
            ],
            "orders": [],
            "logs": []
        }
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(d):
    """파일에 저장"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def add_log(action, detail):
    """로그 추가 후 저장·리로드"""
    d = load_data()
    new_log = {
        "time": int(time.time()),
        "role": session.get("role", "unknown"),
        "action": action,
        "detail": detail
    }
    d["logs"].append(new_log)
    save_data(d)

def calculate_total_price(items):
    d = load_data()
    total = 0
    for oi in items:
        m = next((x for x in d["menuItems"] if x["id"]==oi["menuId"]), None)
        if m:
            total += m["price"] * oi["quantity"]
    return total

def generate_order_id():
    return f"order_{int(time.time()*1000)}"

def login_required(role=None):
    def wrapper(fn):
        def inner(*a, **k):
            if "role" not in session:
                flash("로그인 후 이용 가능합니다.")
                return redirect(url_for("login"))
            if role and session["role"]!=role:
                flash("권한이 없습니다.")
                return redirect(url_for("login"))
            return fn(*a, **k)
        inner.__name__ = fn.__name__
        return inner
    return wrapper

# 1분마다 50/60분 알림 체크
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
                    print(f"[알림] 50분 경과: {o['id']}")
                if diff>=60 and not o.get("alertSixty"):
                    o["alertSixty"]=True; changed=True
                    print(f"[알림] 60분 경과: {o['id']}")
        if changed:
            save_data(d)

threading.Thread(target=time_checker, daemon=True).start()

# ─── 라우트 ─────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        ui, pw = request.form["userid"], request.form["userpw"]
        if ui==ADMIN_ID and pw==ADMIN_PW:
            session["role"]="admin"; flash("관리자 로그인!")
            return redirect(url_for("admin"))
        if ui==KITCHEN_ID and pw==KITCHEN_PW:
            session["role"]="kitchen"; flash("주방 로그인!")
            return redirect(url_for("kitchen"))
        flash("로그인 실패"); return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("role", None)
    flash("로그아웃 되었습니다.")
    return redirect(url_for("index"))

# 주문자 페이지
@app.route("/order", methods=["GET","POST"])
def order():
    if request.method=="POST":
        # 항상 최신 데이터 로드
        d = load_data()

        table = request.form.get("tableNumber","")
        is_first = (request.form.get("isFirstOrder")=="true")
        people = int(request.form.get("peopleCount","0") or 0)
        notice = (request.form.get("noticeChecked")=="on")

        ordered_items = []
        for m in d["menuItems"]:
            qty = int(request.form.get(f"qty_{m['id']}","0") or 0)
            if qty>0:
                ordered_items.append({
                    "menuId": m["id"], "quantity": qty, "doneQuantity": 0
                })

        # (생략: 유효성 검증 로직 동일)

        total = calculate_total_price(ordered_items)
        oid   = generate_order_id()
        now   = int(time.time())
        newo = {
            "id": oid,
            "tableNumber": table,
            "items": ordered_items,
            "totalPrice": total,
            "status": "pending",
            "createdAt": now,
            "confirmedAt": None,
            "alertFifty": False,
            "alertSixty": False,
            "kitchenDone": False
        }
        d["orders"].append(newo)
        save_data(d)    # 저장
        # (선택) 다시 최신 로드: d = load_data()
        return render_template("order_result.html",
                               total_price=total, order_id=oid)

    menu_items = load_data()["menuItems"]
    return render_template("order_form.html", menu_items=menu_items)

# 관리자 페이지
@app.route("/admin")
@login_required(role="admin")
def admin():
    d = load_data()
    return render_template("admin.html",
        pending_orders = [o for o in d["orders"] if o["status"]=="pending"],
        paid_orders    = [o for o in d["orders"] if o["status"]=="paid"],
        completed_orders = [o for o in d["orders"] if o["status"]=="completed"],
        menu_items     = d["menuItems"]
    )

@app.route("/admin/confirm/<order_id>", methods=["POST"])
@login_required(role="admin")
def admin_confirm(order_id):
    d = load_data()  # 사전 새로고침
    o = next((x for x in d["orders"] if x["id"]==order_id), None)
    if o and o["status"]=="pending":
        o["status"] = "paid"
        o["confirmedAt"] = int(time.time())
        save_data(d)   # 저장
    add_log("CONFIRM_ORDER", order_id)
    return redirect(url_for("admin"))

@app.route("/admin/complete/<order_id>", methods=["POST"])
@login_required(role="admin")
def admin_complete(order_id):
    d = load_data()
    o = next((x for x in d["orders"] if x["id"]==order_id), None)
    if o and o["status"]=="paid":
        o["status"] = "completed"
        save_data(d)
    add_log("COMPLETE_ORDER", order_id)
    return redirect(url_for("admin"))

@app.route("/admin/soldout/<int:menu_id>", methods=["POST"])
@login_required(role="admin")
def admin_soldout(menu_id):
    d = load_data()
    m = next((x for x in d["menuItems"] if x["id"]==menu_id), None)
    if m:
        m["soldOut"] = not m["soldOut"]
        save_data(d)
    add_log("SOLDOUT_TOGGLE", str(menu_id))
    return redirect(url_for("admin"))

@app.route("/admin/log")
@login_required(role="admin")
def admin_log_page():
    logs = sorted(load_data()["logs"], key=lambda x: x["time"], reverse=True)
    return render_template("admin_log.html", logs=logs)

# 주방 페이지
@app.route("/kitchen")
@login_required(role="kitchen")
def kitchen():
    d = load_data()
    paid = sorted(
        [o for o in d["orders"] if o["status"]=="paid"],
        key=lambda x: x.get("confirmedAt",0)
    )
    # 남은 조리 수량 집계
    cnt = {}
    for o in paid:
        for i in o["items"]:
            left = i["quantity"] - i.get("doneQuantity",0)
            if left>0:
                cnt[i["menuId"]] = cnt.get(i["menuId"],0) + left
    mm = {m["id"]:m["name"] for m in d["menuItems"]}
    ks = [{"menuId":k, "menuName":mm.get(k,"?"), "count":v} for k,v in cnt.items()]
    return render_template("kitchen.html",
                           paid_orders=paid, kitchen_status=ks)

@app.route("/kitchen/done-item/<order_id>/<int:menu_id>", methods=["POST"])
@login_required(role="kitchen")
def kitchen_done_item(order_id, menu_id):
    d = load_data()
    o = next((x for x in d["orders"] if x["id"]==order_id), None)
    if o and o["status"]=="paid":
        it = next((i for i in o["items"] if i["menuId"]==menu_id), None)
        if it and it["doneQuantity"] < it["quantity"]:
            it["doneQuantity"] += 1
            if all(i["doneQuantity"]>=i["quantity"] for i in o["items"]):
                o["kitchenDone"] = True
            save_data(d)
    add_log("KITCHEN_DONE_ITEM", f"{order_id}/{menu_id}")
    return redirect(url_for("kitchen"))

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)), debug=True)
