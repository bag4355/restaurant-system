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
ADMIN_ID   = os.getenv("ADMIN_ID")
ADMIN_PW   = os.getenv("ADMIN_PW")
KITCHEN_ID = os.getenv("KITCHEN_ID")
KITCHEN_PW = os.getenv("KITCHEN_PW")

DATA_FILE = os.path.join(os.path.dirname(__file__), 'orders.json')

def load_data():
    """JSON 파일 로드 (없으면 기본 구조 생성)"""
    if not os.path.exists(DATA_FILE):
        return {
            "menuItems": [
                {
                    "id":1,"name":"메인안주A","price":12000,
                    "category":"main","soldOut":False,
                    "stock":10,"stockBeforeSoldOut":None
                },
                {
                    "id":2,"name":"메인안주B","price":15000,
                    "category":"main","soldOut":False,
                    "stock":7,"stockBeforeSoldOut":None
                },
                {
                    "id":3,"name":"소주","price":4000,
                    "category":"soju","soldOut":False,
                    "stock":100,"stockBeforeSoldOut":None
                },
                {
                    "id":4,"name":"맥주(1L)","price":8000,
                    "category":"beer","soldOut":False,
                    "stock":50,"stockBeforeSoldOut":None
                },
                {
                    "id":5,"name":"콜라","price":2000,
                    "category":"drink","soldOut":False,
                    "stock":40,"stockBeforeSoldOut":None
                },
                {
                    "id":6,"name":"사이다","price":2000,
                    "category":"drink","soldOut":False,
                    "stock":40,"stockBeforeSoldOut":None
                },
                {
                    "id":7,"name":"생수","price":1000,
                    "category":"drink","soldOut":False,
                    "stock":50,"stockBeforeSoldOut":None
                }
            ],
            "orders": [],
            "logs": [],
            "lastOrderIdUsed": 0
        }
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(d):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def add_log(action, detail):
    d = load_data()
    new_log = {
        "time": int(time.time()),
        "role": session.get("role", "unknown"),
        "action": action,
        "detail": detail
    }
    d["logs"].append(new_log)
    save_data(d)

def generate_order_id():
    """
    lastOrderIdUsed를 1 증가시키고, 그 값을 새 주문번호로 반환.
    실제 JSON에 저장하므로 재시작해도 이어집니다.
    """
    d = load_data()
    d["lastOrderIdUsed"] += 1
    new_id = d["lastOrderIdUsed"]
    save_data(d)
    return new_id

def calculate_total_price(items):
    d = load_data()
    total = 0
    for it in items:
        # it["menuName"] 기준으로 menuItems 찾아 가격 계산
        m = next((x for x in d["menuItems"] if x["name"]==it["menuName"]), None)
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
    # 1분마다 50/60분 경과 알림
    while True:
        time.sleep(60)
        d = load_data()
        changed = False
        now = int(time.time())
        for o in d["orders"]:
            if o["status"] == "paid" and o.get("confirmedAt"):
                diff = (now - o["confirmedAt"]) // 60
                if diff >= 50 and not o.get("alertFifty"):
                    o["alertFifty"] = True
                    changed = True
                    print(f"[알림] 50분 경과 - 주문ID={o['id']}")
                if diff >= 60 and not o.get("alertSixty"):
                    o["alertSixty"] = True
                    changed = True
                    print(f"[알림] 60분 경과 - 주문ID={o['id']}")
        if changed:
            save_data(d)

threading.Thread(target=time_checker, daemon=True).start()

# 매출 계산 (service=False인 주문만)
def get_current_sales(d):
    total = 0
    for o in d["orders"]:
        if not o.get("service") and o["status"] in ["paid","completed"]:
            total += o["totalPrice"]
    return total

# ───────────────────────────────────────────
# 라우트
# ───────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        uid = request.form.get("userid")
        pw  = request.form.get("userpw")
        if uid==ADMIN_ID and pw==ADMIN_PW:
            session["role"]="admin"
            flash("관리자 로그인되었습니다.")
            return redirect(url_for("admin"))
        if uid==KITCHEN_ID and pw==KITCHEN_PW:
            session["role"]="kitchen"
            flash("주방 로그인되었습니다.")
            return redirect(url_for("kitchen"))
        flash("로그인 실패: 아이디/비밀번호를 확인하세요.")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("role", None)
    flash("로그아웃 되었습니다.")
    return redirect(url_for("index"))

# ───────────────────────────────────────────
# 주문자 페이지
# ───────────────────────────────────────────

@app.route("/order", methods=["GET","POST"])
def order():
    d = load_data()
    if request.method=="POST":
        table_number   = request.form.get("tableNumber","")
        is_first_order = (request.form.get("isFirstOrder")=="true")
        people_count   = int(request.form.get("peopleCount","0") or 0)
        notice_checked = (request.form.get("noticeChecked")=="on")

        # 메뉴 선택
        ordered_items=[]
        for m in d["menuItems"]:
            qty = int(request.form.get(f"qty_{m['id']}", "0") or 0)
            if qty>0:
                ordered_items.append({
                    "menuName": m["name"],
                    "quantity": qty,
                    "doneQuantity": 0,
                    "deliveredQuantity": 0
                })

        # (규칙 체크) (생략)
        if not table_number:
            flash("테이블 번호를 선택해주세요.", "error")
            return redirect(url_for("order"))
        if is_first_order:
            if not notice_checked:
                flash("최초 주문 시 주의사항 확인이 필수입니다.", "error")
                return redirect(url_for("order"))
            if people_count<1:
                flash("최초 주문 시 인원수는 1명 이상이어야 합니다.", "error")
                return redirect(url_for("order"))
            # 3명당 메인안주 1개
            main_items = [it for it in ordered_items if any(
                mm["name"]==it["menuName"] and mm["category"]=="main" for mm in d["menuItems"]
            )]
            main_qty = sum(mi["quantity"] for mi in main_items)
            needed = people_count//3
            if needed>0 and main_qty<needed:
                flash(f"인원수 대비 메인안주가 부족합니다 (필요: {needed}개).","error")
                return redirect(url_for("order"))
            # 맥주 최대 1병
            beer_items = [it for it in ordered_items if any(
                mm["name"]==it["menuName"] and mm["category"]=="beer" for mm in d["menuItems"]
            )]
            if sum(b["quantity"] for b in beer_items)>1:
                flash("최초 주문 시 맥주는 1병(1L)까지만 가능합니다.", "error")
                return redirect(url_for("order"))
        else:
            # 추가 주문: 맥주 불가
            beer_items = [it for it in ordered_items if any(
                mm["name"]==it["menuName"] and mm["category"]=="beer" for mm in d["menuItems"]
            )]
            if len(beer_items)>0:
                flash("추가 주문에서는 맥주를 주문할 수 없습니다.", "error")
                return redirect(url_for("order"))

        # 품절 체크
        for it in ordered_items:
            mm = next((x for x in d["menuItems"] if x["name"]==it["menuName"]), None)
            if mm and mm["soldOut"]:
                flash(f"품절된 메뉴[{mm['name']}]는 주문 불가합니다.","error")
                return redirect(url_for("order"))

        # 주문번호 생성
        new_order_id = generate_order_id()  # 순차 증가
        total_price = calculate_total_price(ordered_items)
        now = int(time.time())
        new_order = {
            "id": new_order_id,
            "tableNumber": table_number,
            "peopleCount": people_count,
            "items": ordered_items,
            "totalPrice": total_price,
            "status": "pending",
            "createdAt": now,
            "confirmedAt": None,
            "alertFifty": False,
            "alertSixty": False,
            "kitchenDone": False,
            "service": False
        }
        d["orders"].append(new_order)
        save_data(d)
        flash(f"주문이 접수되었습니다 (주문번호 {new_order_id}).")
        return render_template("order_result.html",
                               total_price=total_price,
                               order_id=new_order_id)

    return render_template("order_form.html", menu_items=d["menuItems"])

# ───────────────────────────────────────────
# 관리자 페이지
# ───────────────────────────────────────────

@app.route("/admin")
@login_required()
def admin():
    d = load_data()
    pending_orders   = [o for o in d["orders"] if o["status"]=="pending"]
    paid_orders      = [o for o in d["orders"] if o["status"]=="paid"]
    completed_orders = [o for o in d["orders"] if o["status"]=="completed"]
    current_sales    = get_current_sales(d)
    return render_template("admin.html",
        pending_orders=pending_orders,
        paid_orders=paid_orders,
        completed_orders=completed_orders,
        menu_items=d["menuItems"],
        current_sales=current_sales
    )

@app.route("/admin/confirm/<int:order_id>", methods=["POST"])
@login_required()
def admin_confirm(order_id):
    d = load_data()
    o = next((x for x in d["orders"] if x["id"]==order_id), None)
    if o and o["status"]=="pending":
        o["status"] = "paid"
        o["confirmedAt"] = int(time.time())
        # 재고 차감, 음료 자동조리
        for it in o["items"]:
            mm = next((m for m in d["menuItems"] if m["name"]==it["menuName"]), None)
            if mm:
                mm["stock"] -= it["quantity"]
                # 소주/맥주/음료류 → 자동 조리완료
                if mm["category"] in ["soju","beer","drink"]:
                    it["doneQuantity"] = it["quantity"]

        save_data(d)
        add_log("CONFIRM_ORDER", f"주문ID={order_id}")
        flash(f"주문 {order_id} 입금확인 완료!")
    return redirect(url_for("admin"))

@app.route("/admin/complete/<int:order_id>", methods=["POST"])
@login_required()
def admin_complete(order_id):
    d = load_data()
    o = next((x for x in d["orders"] if x["id"]==order_id), None)
    if o and o["status"]=="paid":
        o["status"] = "completed"
        save_data(d)
        add_log("COMPLETE_ORDER", f"주문ID={order_id}")
        flash(f"주문 {order_id} 최종 완료되었습니다!")
    return redirect(url_for("admin"))

@app.route("/admin/deliver/<int:order_id>/<menu_name>", methods=["POST"])
@login_required()
def admin_deliver_item(order_id, menu_name):
    d = load_data()
    o = next((xx for xx in d["orders"] if xx["id"]==order_id), None)
    if o and o["status"] in ["paid","completed"]:
        it = next((i for i in o["items"] if i["menuName"]==menu_name), None)
        if it:
            delivered = it["deliveredQuantity"]
            done      = it["doneQuantity"]
            if delivered < done:
                it["deliveredQuantity"] += 1
                add_log("ADMIN_DELIVER_ITEM", f"{order_id}/{menu_name}")
                flash(f"주문 {order_id}, 메뉴 [{menu_name}] 1개 전달!")
            if all(i["deliveredQuantity"]>=i["quantity"] for i in o["items"]):
                o["status"] = "completed"
        save_data(d)
    return redirect(url_for("admin"))

@app.route("/admin/soldout/<int:menu_id>", methods=["POST"])
@login_required()
def admin_soldout(menu_id):
    d = load_data()
    m = next((x for x in d["menuItems"] if x["id"]==menu_id), None)
    if m:
        if not m["soldOut"]:
            m["soldOut"] = True
            m["stockBeforeSoldOut"] = m["stock"]
        else:
            m["soldOut"] = False
            if m["stockBeforeSoldOut"] is not None:
                m["stock"] = m["stockBeforeSoldOut"]
                m["stockBeforeSoldOut"] = None
        save_data(d)
        add_log("SOLDOUT_TOGGLE", f"메뉴[{m['name']}] => soldOut={m['soldOut']}")
        flash(f"메뉴 [{m['name']}] 품절상태 변경!")
    return redirect(url_for("admin"))

@app.route("/admin/log")
@login_required()
def admin_log_page():
    d = load_data()
    logs = sorted(d["logs"], key=lambda x: x["time"], reverse=True)
    return render_template("admin_log.html", logs=logs)

# 0원 서비스
@app.route("/admin/service", methods=["POST"])
@login_required()
def admin_service():
    d = load_data()
    table = request.form.get("serviceTable","")
    menu_name = request.form.get("serviceMenu","")
    qty = int(request.form.get("serviceQty","0") or 0)
    if not table or not menu_name or qty<1:
        flash("서비스 등록 실패: 테이블/메뉴/수량 확인 필요","error")
        return redirect(url_for("admin"))

    mm = next((m for m in d["menuItems"] if m["name"]==menu_name), None)
    if mm and mm["soldOut"]:
        flash("해당 메뉴는 품절 처리된 상태입니다.","error")
        return redirect(url_for("admin"))

    new_id = generate_order_id()  # 서비스도 새 주문번호
    now = int(time.time())
    item = {
        "menuName": menu_name,
        "quantity": qty,
        "doneQuantity": 0,
        "deliveredQuantity": 0
    }
    new_order = {
        "id": new_id,
        "tableNumber": table,
        "peopleCount": 0,
        "items": [item],
        "totalPrice": 0,
        "status": "paid",
        "createdAt": now,
        "confirmedAt": now,
        "alertFifty": False,
        "alertSixty": False,
        "kitchenDone": False,
        "service": True
    }
    d["orders"].append(new_order)
    # 재고 차감
    if mm:
        mm["stock"] -= qty
        # 소주/맥주/음료류 자동 조리
        if mm["category"] in ["soju","beer","drink"]:
            item["doneQuantity"] = qty

    save_data(d)
    add_log("ADMIN_SERVICE", f"주문ID={new_id} /메뉴:{menu_name}/{qty}")
    flash(f"0원 서비스 주문이 등록되었습니다. (주문 {new_id})")
    return redirect(url_for("admin"))

# ───────────────────────────────────────────
# 주방 페이지
# ───────────────────────────────────────────

@app.route("/kitchen")
@login_required()
def kitchen():
    d = load_data()
    paid_orders = sorted(
        [o for o in d["orders"] if o["status"]=="paid"],
        key=lambda x: x.get("confirmedAt", 0)
    )
    # 미조리 합계
    item_count = {}
    for o in paid_orders:
        for it in o["items"]:
            left = it["quantity"] - it["doneQuantity"]
            if left>0:
                item_count[it["menuName"]] = item_count.get(it["menuName"],0)+left

    return render_template("kitchen.html",
                           paid_orders=paid_orders,
                           kitchen_status=item_count)

@app.route("/kitchen/done-item/<int:order_id>/<menu_name>", methods=["POST"])
@login_required()
def kitchen_done_item(order_id, menu_name):
    d = load_data()
    o = next((x for x in d["orders"] if x["id"]==order_id), None)
    if o and o["status"]=="paid":
        it = next((i for i in o["items"] if i["menuName"]==menu_name), None)
        if it and it["doneQuantity"]<it["quantity"]:
            it["doneQuantity"] += 1
            add_log("KITCHEN_DONE_ITEM", f"{order_id}/{menu_name}")
            # 모두 조리완료?
            if all(i["doneQuantity"]>=i["quantity"] for i in o["items"]):
                o["kitchenDone"] = True
        save_data(d)
    return redirect(url_for("kitchen"))

if __name__=="__main__":
    port = int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
