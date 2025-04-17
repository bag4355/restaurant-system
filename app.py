import os
import json
import threading
import time
from flask import (
    Flask, request, render_template, redirect, url_for, flash, session
)
from dotenv import load_dotenv

load_dotenv()  # .env 파일 등에 환경변수가 있으면 불러옴

app = Flask(__name__)
app.secret_key = 'SOME_RANDOM_SECRET_KEY'  # 세션/플래시 메시지용

# 환경변수에서 ID/PW 불러오기
ADMIN_ID = os.environ["ADMIN_ID"]
ADMIN_PW = os.environ["ADMIN_PW"]
KITCHEN_ID = os.environ["KITCHEN_ID"]
KITCHEN_PW = os.environ["KITCHEN_PW"]

# JSON 파일 경로
DATA_FILE = os.path.join(os.path.dirname(__file__), 'orders.json')

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "menuItems": [
                {"id": 1, "name": "메인안주A", "price": 12000, "category": "main", "soldOut": False},
                {"id": 2, "name": "메인안주B", "price": 15000, "category": "main", "soldOut": False},
                {"id": 3, "name": "소주",      "price": 4000,  "category": "soju", "soldOut": False},
                {"id": 4, "name": "맥주(1L)",  "price": 8000,  "category": "beer", "soldOut": False},
                {"id": 5, "name": "콜라",      "price": 2000,  "category": "drink","soldOut": False},
                {"id": 6, "name": "사이다",    "price": 2000,  "category": "drink","soldOut": False},
                {"id": 7, "name": "생수",      "price": 1000,  "category": "drink","soldOut": False},
            ],
            "orders": [],
            "logs": []
        }
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(d):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

data = load_data()
# logs 필드가 없을 경우 대비
if "logs" not in data:
    data["logs"] = []

##########################################
# 로그 기록 함수
##########################################
def add_log(action, detail):
    """
    - action: 예) 'CONFIRM_ORDER', 'COMPLETE_ORDER', 'KITCHEN_DONE_ITEM', 'SOLDOUT_TOGGLE'
    - detail: 구체 정보(주문ID, 메뉴ID 등)
    """
    new_log = {
        "time": int(time.time()),
        "role": session.get("role", "unknown"),  # 누가 작업했는지
        "action": action,
        "detail": detail
    }
    data["logs"].append(new_log)
    save_data(data)

##########################################
# 시간 체크(50분/60분) 스레드
##########################################
def time_checker():
    while True:
        time.sleep(60)  # 1분마다 체크
        now = int(time.time())
        changed = False
        for order in data["orders"]:
            if order["status"] == "paid" and order["confirmedAt"] is not None:
                diff = (now - order["confirmedAt"]) // 60  # 분 단위
                if diff >= 50 and (not order.get("alertFifty", False)):
                    order["alertFifty"] = True
                    print(f"[관리자알림] 테이블 {order['tableNumber']} (주문ID={order['id']}) 50분 경과 - 퇴장 10분 전 알림")
                    changed = True
                if diff >= 60 and (not order.get("alertSixty", False)):
                    order["alertSixty"] = True
                    print(f"[관리자알림] 테이블 {order['tableNumber']} (주문ID={order['id']}) 60분 경과 - 퇴장 알림")
                    changed = True
        if changed:
            save_data(data)

checker_thread = threading.Thread(target=time_checker, daemon=True)
checker_thread.start()

##########################################
# 유틸 함수
##########################################

def calculate_total_price(ordered_items):
    total = 0
    for oi in ordered_items:
        menu = next((m for m in data["menuItems"] if m["id"] == oi["menuId"]), None)
        if menu:
            total += menu["price"] * oi["quantity"]
    return total

def generate_order_id():
    return f"order_{int(time.time() * 1000)}"

def login_required(role=None):
    """
    Decorator-like function (간단 구현):
    - role="admin" 또는 "kitchen" 이어야 접근 가능
    - session["role"]와 비교
    """
    def wrapper(func):
        def inner(*args, **kwargs):
            if "role" not in session:
                flash("로그인 후 이용 가능합니다.")
                return redirect(url_for("login"))
            if role and session["role"] != role:
                flash("권한이 없습니다.")
                return redirect(url_for("login"))
            return func(*args, **kwargs)
        inner.__name__ = func.__name__
        return inner
    return wrapper

##########################################
# 라우트
##########################################

# 로그인 페이지
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        input_id = request.form.get("userid")
        input_pw = request.form.get("userpw")

        if input_id == ADMIN_ID and input_pw == ADMIN_PW:
            session["role"] = "admin"
            flash("관리자 계정으로 로그인되었습니다.")
            return redirect(url_for("admin"))

        if input_id == KITCHEN_ID and input_pw == KITCHEN_PW:
            session["role"] = "kitchen"
            flash("주방 계정으로 로그인되었습니다.")
            return redirect(url_for("kitchen"))

        flash("로그인 실패: 아이디/비밀번호를 확인하세요.")
        return redirect(url_for("login"))

    # GET
    return render_template("login.html")

# 로그아웃
@app.route("/logout")
def logout():
    session.pop("role", None)
    flash("로그아웃되었습니다.")
    return redirect(url_for("index"))


# 메인 페이지(간단 안내)
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------
# 1) 주문자용 페이지
# ---------------------------
@app.route("/order", methods=["GET", "POST"])
def order():
    if request.method == "POST":
        table_number = request.form.get("tableNumber", "")
        is_first_order = (request.form.get("isFirstOrder") == "true")
        people_count = request.form.get("peopleCount")
        if people_count == "":
            people_count = 0
        else:
            people_count = int(people_count)

        notice_checked = (request.form.get("noticeChecked") == "on")

        ordered_items = []
        for m in data["menuItems"]:
            qty_str = request.form.get(f"qty_{m['id']}", "0")
            if qty_str.isdigit():
                qty = int(qty_str)
                if qty > 0:
                    # 초기 doneQuantity=0 추가 (주방 조리용)
                    ordered_items.append({"menuId": m["id"], "quantity": qty, "doneQuantity": 0})

        # 유효성 검증
        if table_number == "":
            flash("테이블 번호를 선택해주세요.")
            return redirect(url_for("order"))

        if is_first_order:
            # 주의사항 체크
            if not notice_checked:
                flash("최초 주문 시 주의사항 확인이 필수입니다.")
                return redirect(url_for("order"))
            # 인원수 >= 1
            if people_count < 1:
                flash("최초 주문 시 인원수는 1명 이상이어야 합니다.")
                return redirect(url_for("order"))
            # 3명당 메인안주 1개
            main_dishes = [oi for oi in ordered_items if
                next((mm for mm in data["menuItems"] if mm["id"] == oi["menuId"] and mm["category"] == "main"), None)
            ]
            total_main_qty = sum([md["quantity"] for md in main_dishes])
            needed = people_count // 3
            if needed > 0 and total_main_qty < needed:
                flash(f"인원수 대비 메인안주가 부족합니다 (필요: {needed}개 이상).")
                return redirect(url_for("order"))
            # 맥주(beer) 최대 1병
            beer_items = [oi for oi in ordered_items if
                next((mm for mm in data["menuItems"] if mm["id"] == oi["menuId"] and mm["category"] == "beer"), None)
            ]
            total_beer_qty = sum([b["quantity"] for b in beer_items])
            if total_beer_qty > 1:
                flash("최초 주문 시 맥주는 1병(1L)만 주문 가능합니다.")
                return redirect(url_for("order"))
        else:
            # 추가 주문 시 맥주 불가
            beer_items = [oi for oi in ordered_items if
                next((mm for mm in data["menuItems"] if mm["id"] == oi["menuId"] and mm["category"] == "beer"), None)
            ]
            if len(beer_items) > 0:
                flash("추가 주문에서는 맥주를 주문할 수 없습니다.")
                return redirect(url_for("order"))

        # 품절 체크
        for oi in ordered_items:
            menu_obj = next((x for x in data["menuItems"] if x["id"] == oi["menuId"]), None)
            if menu_obj and menu_obj["soldOut"]:
                flash(f"품절된 메뉴가 포함되어 있습니다: {menu_obj['name']}")
                return redirect(url_for("order"))

        total_price = calculate_total_price(ordered_items)
        new_order_id = generate_order_id()
        now_ts = int(time.time())
        new_order = {
            "id": new_order_id,
            "tableNumber": table_number,
            "isFirstOrder": is_first_order,
            "peopleCount": people_count,
            "items": ordered_items,
            "totalPrice": total_price,
            "status": "pending",
            "createdAt": now_ts,
            "confirmedAt": None,
            "alertFifty": False,
            "alertSixty": False,
            "kitchenDone": False
        }
        data["orders"].append(new_order)
        save_data(data)

        return render_template("order_result.html", total_price=total_price, order_id=new_order_id)

    menu_items = data["menuItems"]
    return render_template("order_form.html", menu_items=menu_items)


@app.route("/order/<order_id>")
def order_detail(order_id):
    order = next((o for o in data["orders"] if o["id"] == order_id), None)
    if not order:
        return "존재하지 않는 주문입니다.", 404
    return f"주문 상세(ID={order_id}): {order}"


# ---------------------------
# 2) 관리자용 페이지
# ---------------------------
@app.route("/admin")
@login_required(role="admin")  # 관리자 전용
def admin():
    pending_orders = [o for o in data["orders"] if o["status"] == "pending"]
    paid_orders = [o for o in data["orders"] if o["status"] == "paid"]
    completed_orders = [o for o in data["orders"] if o["status"] == "completed"]
    menu_items = data["menuItems"]
    return render_template(
        "admin.html",
        pending_orders=pending_orders,
        paid_orders=paid_orders,
        completed_orders=completed_orders,
        menu_items=menu_items
    )

@app.route("/admin/confirm/<order_id>", methods=["POST"])
@login_required(role="admin")
def admin_confirm(order_id):
    order = next((o for o in data["orders"] if o["id"] == order_id), None)
    if not order:
        flash("해당 주문이 존재하지 않습니다.")
        return redirect(url_for("admin"))
    if order["status"] != "pending":
        flash("이미 확정되었거나 처리 불가능한 상태입니다.")
        return redirect(url_for("admin"))

    order["status"] = "paid"
    order["confirmedAt"] = int(time.time())
    save_data(data)
    add_log("CONFIRM_ORDER", f"주문ID={order_id} 확정")
    flash(f"{order_id} 주문이 확정되었습니다.")
    return redirect(url_for("admin"))

@app.route("/admin/complete/<order_id>", methods=["POST"])
@login_required(role="admin")
def admin_complete(order_id):
    order = next((o for o in data["orders"] if o["id"] == order_id), None)
    if not order:
        flash("해당 주문이 존재하지 않습니다.")
        return redirect(url_for("admin"))
    if order["status"] != "paid":
        flash("확정되지 않았거나 이미 완료된 주문입니다.")
        return redirect(url_for("admin"))

    order["status"] = "completed"
    save_data(data)
    add_log("COMPLETE_ORDER", f"주문ID={order_id} 완료")
    flash(f"{order_id} 주문이 완료 처리되었습니다.")
    return redirect(url_for("admin"))

@app.route("/admin/soldout/<int:menu_id>", methods=["POST"])
@login_required(role="admin")
def admin_soldout(menu_id):
    menu_obj = next((m for m in data["menuItems"] if m["id"] == menu_id), None)
    if not menu_obj:
        flash("해당 메뉴가 존재하지 않습니다.")
        return redirect(url_for("admin"))

    menu_obj["soldOut"] = not menu_obj["soldOut"]
    save_data(data)
    state = "품절" if menu_obj["soldOut"] else "품절 해제"
    add_log("SOLDOUT_TOGGLE", f"메뉴ID={menu_id}, {state}")
    flash(f"{menu_obj['name']} {state} 처리되었습니다.")
    return redirect(url_for("admin"))

# 관리자 로그 페이지
@app.route("/admin/log")
@login_required(role="admin")
def admin_log_page():
    logs = data["logs"]
    # 시간 내림차순 정렬(가장 최근이 위로)
    logs_sorted = sorted(logs, key=lambda x: x["time"], reverse=True)
    return render_template("admin_log.html", logs=logs_sorted)


# ---------------------------
# 3) 주방용 페이지
# ---------------------------
@app.route("/kitchen")
@login_required(role="kitchen")  # 주방 전용
def kitchen():
    paid_orders = sorted(
        [o for o in data["orders"] if o["status"] == "paid"],
        key=lambda x: x["confirmedAt"] if x["confirmedAt"] else 0
    )

    # 현재 만들어야 할 전체 메뉴 수량(조리 안된 부분만 카운트)
    item_counts = {}
    for o in paid_orders:
        for i in o["items"]:
            left_qty = i["quantity"] - i.get("doneQuantity", 0)
            if left_qty > 0:
                mid = i["menuId"]
                item_counts[mid] = item_counts.get(mid, 0) + left_qty

    # 메뉴 이름 매핑
    menu_map = {m["id"]: m["name"] for m in data["menuItems"]}
    kitchen_status = [
        {
            "menuId": mid,
            "menuName": menu_map.get(mid, f"Unknown_{mid}"),
            "count": c
        }
        for mid, c in item_counts.items()
    ]

    return render_template(
        "kitchen.html",
        paid_orders=paid_orders,
        kitchen_status=kitchen_status
    )

# 주방에서 "메뉴 아이템" 조리 완료(1개씩)
@app.route("/kitchen/done-item/<order_id>/<int:menu_id>", methods=["POST"])
@login_required(role="kitchen")
def kitchen_done_item(order_id, menu_id):
    order = next((o for o in data["orders"] if o["id"] == order_id), None)
    if not order:
        flash("해당 주문이 존재하지 않습니다.")
        return redirect(url_for("kitchen"))
    if order["status"] != "paid":
        flash("이미 완료됐거나 준비할 수 없는 주문입니다.")
        return redirect(url_for("kitchen"))

    item = next((i for i in order["items"] if i["menuId"] == menu_id), None)
    if not item:
        flash("해당 주문 내에 해당 메뉴가 없습니다.")
        return redirect(url_for("kitchen"))

    done_qty = item.get("doneQuantity", 0)
    if done_qty < item["quantity"]:
        item["doneQuantity"] = done_qty + 1
        add_log("KITCHEN_DONE_ITEM", f"주문ID={order_id}, 메뉴ID={menu_id}, 조리1개 완료")

    # 모든 아이템이 quantity == doneQuantity이면, kitchenDone = True
    all_done = True
    for i in order["items"]:
        if i["quantity"] > i.get("doneQuantity", 0):
            all_done = False
            break
    order["kitchenDone"] = all_done

    save_data(data)
    flash(f"주문 {order_id} / 메뉴ID {menu_id} 조리 1개 완료 (done={item['doneQuantity']}/{item['quantity']})")
    return redirect(url_for("kitchen"))

# 메인 실행
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
