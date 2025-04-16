import os
import json
import threading
import time
from flask import Flask, request, render_template, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = 'Adobe_Is_Free'  # 플래시 메시지용

# JSON 파일 경로
DATA_FILE = os.path.join(os.path.dirname(__file__), 'orders.json')

# 프로그램 기동 시 JSON 파일에서 데이터를 불러옴
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
            "orders": []
        }
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 전역 데이터(메모리에 올려놓음). 실제 처리 시에는 DB나 캐시 사용을 권장
data = load_data()

##########################################
# 시간 체크(50분/60분) 스레드
##########################################
def time_checker():
    while True:
        time.sleep(60)  # 1분마다 체크
        now = int(time.time())
        for order in data["orders"]:
            if order["status"] == "paid" and order["confirmedAt"] is not None:
                diff = (now - order["confirmedAt"]) // 60  # 분 단위
                # 50분 알림
                if diff >= 50 and (not order.get("alertFifty", False)):
                    order["alertFifty"] = True
                    print(f"[관리자알림] 테이블 {order['tableNumber']} (주문ID={order['id']}) 50분 경과 - 퇴장 10분 전 알림")
                # 60분 알림
                if diff >= 60 and (not order.get("alertSixty", False)):
                    order["alertSixty"] = True
                    print(f"[관리자알림] 테이블 {order['tableNumber']} (주문ID={order['id']}) 60분 경과 - 퇴장 알림")
        save_data(data)

# 백그라운드 스레드 시작
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
    return f"order_{int(time.time() * 1000)}"  # 예: order_1681648889773

##########################################
# 라우트
##########################################

# 메인 페이지(간단 안내)
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------
# 1) 주문자용 페이지
# ---------------------------
@app.route("/order", methods=["GET", "POST"])
def order():
    """
    GET: 주문 폼 렌더링
    POST: 주문 처리
    """
    if request.method == "POST":
        table_number = request.form.get("tableNumber", "")
        is_first_order = (request.form.get("isFirstOrder") == "true")
        people_count = request.form.get("peopleCount")
        if people_count == "":
            people_count = 0
        else:
            people_count = int(people_count)

        # 체크박스(주의사항 확인)
        notice_checked = (request.form.get("noticeChecked") == "on")

        # 메뉴 주문 정보 수집
        ordered_items = []
        for m in data["menuItems"]:
            # form에서 "qty_<메뉴id>" 로 전달된 값이 있을 것
            qty_str = request.form.get(f"qty_{m['id']}", "0")
            if qty_str.isdigit():
                qty = int(qty_str)
                if qty > 0:
                    ordered_items.append({"menuId": m["id"], "quantity": qty})

        # 유효성 검증
        # 1) 테이블 번호 필수
        if table_number == "":
            flash("테이블 번호를 선택해주세요.")
            return redirect(url_for("order"))

        # 2) 최초 주문 시
        if is_first_order:
            # - 주의사항 체크 필수
            if not notice_checked:
                flash("최초 주문 시 주의사항 확인이 필수입니다.")
                return redirect(url_for("order"))
            # - 인원수 >= 1
            if people_count < 1:
                flash("최초 주문 시 인원수는 1명 이상이어야 합니다.")
                return redirect(url_for("order"))
            # - 3명당 메인안주 1개
            main_dishes = [itm for itm in ordered_items if next((mm for mm in data["menuItems"] if mm["id"] == itm["menuId"] and mm["category"] == "main"), None)]
            total_main_qty = sum([md["quantity"] for md in main_dishes])
            needed = people_count // 3  # 예: 5명 -> 1개, 6명 -> 2개
            if needed > 0 and total_main_qty < needed:
                flash(f"인원수 대비 메인안주가 부족합니다 (필요: {needed}개 이상).")
                return redirect(url_for("order"))
            # - 맥주(beer)는 최대 1병
            beer_ordered = [itm for itm in ordered_items if next((mm for mm in data["menuItems"] if mm["id"] == itm["menuId"] and mm["category"] == "beer"), None)]
            total_beer_qty = sum([b["quantity"] for b in beer_ordered])
            if total_beer_qty > 1:
                flash("최초 주문 시 맥주는 1병(1L)만 주문 가능합니다.")
                return redirect(url_for("order"))
        else:
            # 추가 주문 시 맥주는 주문 불가
            beer_ordered = [itm for itm in ordered_items if next((mm for mm in data["menuItems"] if mm["id"] == itm["menuId"] and mm["category"] == "beer"), None)]
            if len(beer_ordered) > 0:
                flash("추가 주문에서는 맥주를 주문할 수 없습니다.")
                return redirect(url_for("order"))

        # 3) 품절 여부 체크
        for oi in ordered_items:
            menu_obj = next((m for m in data["menuItems"] if m["id"] == oi["menuId"]), None)
            if menu_obj and menu_obj["soldOut"]:
                flash(f"품절된 메뉴가 포함되어 있습니다: {menu_obj['name']}")
                return redirect(url_for("order"))

        # 총 금액 계산
        total_price = calculate_total_price(ordered_items)

        # 주문 생성
        new_order_id = generate_order_id()
        now_ts = int(time.time())
        new_order = {
            "id": new_order_id,
            "tableNumber": table_number,
            "isFirstOrder": is_first_order,
            "peopleCount": people_count,
            "items": ordered_items,
            "totalPrice": total_price,
            "status": "pending",  # 관리자가 입금 확인 전
            "createdAt": now_ts,
            "confirmedAt": None,   # 입금 확인 후
            "alertFifty": False,
            "alertSixty": False
        }
        data["orders"].append(new_order)
        save_data(data)

        # 주문 완료 페이지로 이동(총 금액/계좌 표시)
        return render_template("order_result.html", total_price=total_price, order_id=new_order_id)

    # GET
    menu_items = data["menuItems"]
    return render_template("order_form.html", menu_items=menu_items)


# 주문 상세 확인 (주문자가 확인할 때 등)
@app.route("/order/<order_id>")
def order_detail(order_id):
    order = next((o for o in data["orders"] if o["id"] == order_id), None)
    if not order:
        return "존재하지 않는 주문입니다.", 404
    return f"주문 상세(ID={order_id}): {order}"  # 간단 표시 (실제론 예쁘게 표시 가능)


# ---------------------------
# 2) 관리자용 페이지
# ---------------------------
@app.route("/admin")
def admin():
    """
    주문 상태별 목록:
    - pending (대기중)
    - paid (확정됨)
    - completed (완료됨)
    """
    pending_orders = [o for o in data["orders"] if o["status"] == "pending"]
    paid_orders = [o for o in data["orders"] if o["status"] == "paid"]
    completed_orders = [o for o in data["orders"] if o["status"] == "completed"]
    # 메뉴 목록(품절 처리용)
    menu_items = data["menuItems"]
    return render_template(
        "admin.html",
        pending_orders=pending_orders,
        paid_orders=paid_orders,
        completed_orders=completed_orders,
        menu_items=menu_items
    )

# 주문 확정(입금 확인)
@app.route("/admin/confirm/<order_id>", methods=["POST"])
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
    flash(f"{order_id} 주문이 확정되었습니다.")
    return redirect(url_for("admin"))

# 주문 완료 처리
@app.route("/admin/complete/<order_id>", methods=["POST"])
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
    flash(f"{order_id} 주문이 완료 처리되었습니다.")
    return redirect(url_for("admin"))

# 메뉴 품절 처리
@app.route("/admin/soldout/<int:menu_id>", methods=["POST"])
def admin_soldout(menu_id):
    menu_obj = next((m for m in data["menuItems"] if m["id"] == menu_id), None)
    if not menu_obj:
        flash("해당 메뉴가 존재하지 않습니다.")
        return redirect(url_for("admin"))

    # soldOut 토글
    menu_obj["soldOut"] = not menu_obj["soldOut"]
    save_data(data)
    state = "품절" if menu_obj["soldOut"] else "품절 해제"
    flash(f"{menu_obj['name']} {state} 처리되었습니다.")
    return redirect(url_for("admin"))


# ---------------------------
# 3) 주방용 페이지
# ---------------------------
@app.route("/kitchen")
def kitchen():
    # 'paid' 상태의 주문만(확정된 주문), confirmedAt가 오래된 순(오래된=작은 값)
    paid_orders = sorted([o for o in data["orders"] if o["status"] == "paid"],
                         key=lambda x: x["confirmedAt"] if x["confirmedAt"] else 0)

    # 현재 만들어야 할 전체 메뉴 수량
    # paid 상태의 모든 주문 항목을 합산
    item_counts = {}
    for o in paid_orders:
        for i in o["items"]:
            mid = i["menuId"]
            qty = i["quantity"]
            item_counts[mid] = item_counts.get(mid, 0) + qty

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

    return render_template("kitchen.html", paid_orders=paid_orders, kitchen_status=kitchen_status)

# 주방에서 "조리 완료" 처리
@app.route("/kitchen/done/<order_id>", methods=["POST"])
def kitchen_done(order_id):
    order = next((o for o in data["orders"] if o["id"] == order_id), None)
    if not order:
        flash("해당 주문이 존재하지 않습니다.")
        return redirect(url_for("kitchen"))
    if order["status"] != "paid":
        flash("이미 완료되었거나 처리할 수 없는 주문입니다.")
        return redirect(url_for("kitchen"))

    # 주방에서 조리 완료 -> 실제론 order["kitchenDone"] = True 등으로만 처리할 수 있음
    # 여기서는 별도 플래그를 달아두자
    order["kitchenDone"] = True
    save_data(data)
    flash(f"주문 {order_id} 조리 완료 처리되었습니다.")
    return redirect(url_for("kitchen"))


# 메인 실행
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
