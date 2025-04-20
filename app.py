import os
import time
import threading
import sqlite3
from flask import (
    Flask, request, render_template, redirect,
    url_for, flash, session, g
)
from dotenv import load_dotenv
from sqlite3 import Error as SQLiteError

load_dotenv()

app = Flask(__name__, static_folder="static")
app.secret_key = os.urandom(24)

# ─────────────────────────────────────────────────────────
# 환경 변수에서 관리자/주방 계정 정보 로드
# ─────────────────────────────────────────────────────────
ADMIN_ID   = os.getenv("ADMIN_ID", "admin")
ADMIN_PW   = os.getenv("ADMIN_PW", "admin123")
KITCHEN_ID = os.getenv("KITCHEN_ID", "kitchen")
KITCHEN_PW = os.getenv("KITCHEN_PW", "kitchen123")

# ─────────────────────────────────────────────────────────
# DB 경로 및 커넥션, Lock
# ─────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), 'app.db')

# 파이썬 전역 Lock(스레드 간)을 사용
# (주의: 멀티프로세스 환경에는 적용되지 않음)
db_lock = threading.Lock()

def get_db():
    """
    요청마다 새로운 DB 연결을 반환.
    - busy_timeout=5000 : DB가 Lock 중이면 최대 5초 기다림
    - journal_mode=WAL  : WAL 모드 사용(동시성 향상)
    """
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH, check_same_thread=False)
        db.execute("PRAGMA busy_timeout = 5000")
        db.execute("PRAGMA journal_mode = WAL")
    return db

@app.teardown_appcontext
def close_connection(exception):
    """요청 종료 시 DB 연결 닫기."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# ─────────────────────────────────────────────────────────
# DB 초기화
# ─────────────────────────────────────────────────────────
def init_db():
    with db_lock:  # 초기화도 Lock으로 보호
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")

        cur = conn.cursor()

        # menu 테이블
        cur.execute("""
        CREATE TABLE IF NOT EXISTS menu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            category TEXT NOT NULL,
            stock INTEGER NOT NULL,
            soldOut INTEGER NOT NULL DEFAULT 0
        )
        """)

        # orders 테이블
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,       -- int(time.time()) 로 생성
            tableNumber TEXT NOT NULL,
            peopleCount INTEGER NOT NULL,
            totalPrice INTEGER NOT NULL,
            status TEXT NOT NULL,         -- pending / paid / completed
            createdAt INTEGER NOT NULL,   -- time.time() (초)
            confirmedAt INTEGER,          -- paid 시점 time
            alertTime1 INTEGER NOT NULL DEFAULT 0, -- 50분 경과 알림 여부
            alertTime2 INTEGER NOT NULL DEFAULT 0, -- 60분 경과 알림 여부
            service INTEGER NOT NULL DEFAULT 0      -- 0원 서비스 여부(1이면 true)
        )
        """)

        # order_items 테이블
        cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,     -- orders.id 참조
            menu_id INTEGER NOT NULL,      -- menu.id 참조
            quantity INTEGER NOT NULL,
            doneQuantity INTEGER NOT NULL DEFAULT 0,
            deliveredQuantity INTEGER NOT NULL DEFAULT 0
        )
        """)

        # logs 테이블
        cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time INTEGER NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT NOT NULL
        )
        """)

        # settings 테이블
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            main_required_enabled INTEGER NOT NULL DEFAULT 1,
            main_anju_ratio INTEGER NOT NULL DEFAULT 3,
            beer_limit_enabled INTEGER NOT NULL DEFAULT 1,
            beer_limit_count INTEGER NOT NULL DEFAULT 1,
            time_warning1 INTEGER NOT NULL DEFAULT 50,
            time_warning2 INTEGER NOT NULL DEFAULT 60
        )
        """)

        # 기본 데이터가 없으면 생성
        cur.execute("SELECT COUNT(*) FROM menu")
        if cur.fetchone()[0] == 0:
            sample_menu = [
                ("메인안주A", 12000, "main", 10, 0),
                ("메인안주B", 15000, "main", 7, 0),
                ("소주", 4000, "soju", 100, 0),
                ("맥주(1L)", 8000, "beer", 50, 0),
                ("콜라", 2000, "drink", 40, 0),
                ("사이다", 2000, "drink", 40, 0),
                ("생수", 1000, "drink", 50, 0),
            ]
            cur.executemany("""
                INSERT INTO menu (name, price, category, stock, soldOut)
                VALUES (?, ?, ?, ?, ?)
            """, sample_menu)

        cur.execute("SELECT COUNT(*) FROM settings")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                INSERT INTO settings (id, main_required_enabled, main_anju_ratio,
                                      beer_limit_enabled, beer_limit_count,
                                      time_warning1, time_warning2)
                VALUES (1, 1, 3, 1, 1, 50, 60)
            """)

        conn.commit()
        conn.close()

def log_action(role, action, detail):
    """logs 테이블에 로그 기록."""
    with db_lock:
        conn = get_db()
        cur = conn.cursor()
        now = int(time.time())
        cur.execute("""
            INSERT INTO logs (time, role, action, detail)
            VALUES (?, ?, ?, ?)
        """, (now, role, action, detail))
        conn.commit()

def get_settings():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM settings WHERE id=1")
    row = cur.fetchone()
    if not row:
        # 없으면 기본값 생성
        with db_lock:
            cur.execute("""
                INSERT INTO settings (id, main_required_enabled, main_anju_ratio,
                                      beer_limit_enabled, beer_limit_count,
                                      time_warning1, time_warning2)
                VALUES (1, 1, 3, 1, 1, 50, 60)
            """)
            conn.commit()
        return {
            "id": 1,
            "main_required_enabled": 1,
            "main_anju_ratio": 3,
            "beer_limit_enabled": 1,
            "beer_limit_count": 1,
            "time_warning1": 50,
            "time_warning2": 60
        }
    return {
        "id": row[0],
        "main_required_enabled": (row[1] == 1),
        "main_anju_ratio": row[2],
        "beer_limit_enabled": (row[3] == 1),
        "beer_limit_count": row[4],
        "time_warning1": row[5],
        "time_warning2": row[6]
    }

def update_settings(form_data):
    with db_lock:
        conn = get_db()
        cur = conn.cursor()
        main_required_enabled = 1 if form_data.get("mainRequiredEnabled")=="1" else 0
        beer_limit_enabled = 1 if form_data.get("beerLimitEnabled")=="1" else 0

        main_anju_ratio = int(form_data.get("mainAnjuRatio", "3") or 3)
        beer_limit_count = int(form_data.get("beerLimitCount", "1") or 1)
        time_warning1 = int(form_data.get("timeWarning1", "50") or 50)
        time_warning2 = int(form_data.get("timeWarning2", "60") or 60)

        cur.execute("""
            UPDATE settings
            SET main_required_enabled=?,
                main_anju_ratio=?,
                beer_limit_enabled=?,
                beer_limit_count=?,
                time_warning1=?,
                time_warning2=?
            WHERE id=1
        """, (main_required_enabled, main_anju_ratio, beer_limit_enabled,
              beer_limit_count, time_warning1, time_warning2))
        conn.commit()

# ─────────────────────────────────────────────────────────
# 50분/60분 확인 쓰레드
# ─────────────────────────────────────────────────────────

time_checker_thread = None
time_checker_started = False

def start_time_checker():
    global time_checker_thread, time_checker_started
    if time_checker_started:
        return
    time_checker_started = True

    def run_checker():
        while True:
            time.sleep(60)  # 1분 주기
            try:
                with db_lock:  # DB 접근 전 Lock
                    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
                    conn.execute("PRAGMA busy_timeout = 5000")
                    conn.execute("PRAGMA journal_mode = WAL")
                    cur = conn.cursor()

                    # settings
                    cur.execute("SELECT * FROM settings WHERE id=1")
                    srow = cur.fetchone()
                    if not srow:
                        # 설정 없으면 넘어감
                        conn.close()
                        continue

                    (_, main_required_enabled, main_anju_ratio,
                     beer_limit_enabled, beer_limit_count,
                     time_warning1, time_warning2) = srow

                    now_sec = int(time.time())

                    # paid 상태이면서 confirmedAt != None
                    cur.execute("""
                        SELECT id, order_id, confirmedAt, alertTime1, alertTime2
                        FROM orders
                        WHERE status='paid' AND confirmedAt IS NOT NULL
                    """)
                    orders = cur.fetchall()
                    for o in orders:
                        oid = o[0]
                        order_id = o[1]
                        cAt = o[2]
                        a1 = o[3]
                        a2 = o[4]
                        if cAt is None:
                            continue
                        diff_min = (now_sec - cAt) // 60

                        # 첫 번째 경고
                        if a1 == 0 and diff_min >= time_warning1:
                            cur.execute("UPDATE orders SET alertTime1=1 WHERE id=?", (oid,))
                            # 로그
                            now_t = int(time.time())
                            cur.execute("""
                                INSERT INTO logs (time, role, action, detail)
                                VALUES (?, ?, ?, ?)
                            """, (now_t, "system", "TIME_WARNING1", f"order_id={order_id}"))

                        # 두 번째 경고
                        if a2 == 0 and diff_min >= time_warning2:
                            cur.execute("UPDATE orders SET alertTime2=1 WHERE id=?", (oid,))
                            now_t = int(time.time())
                            cur.execute("""
                                INSERT INTO logs (time, role, action, detail)
                                VALUES (?, ?, ?, ?)
                            """, (now_t, "system", "TIME_WARNING2", f"order_id={order_id}"))

                    conn.commit()
                    conn.close()
            except Exception as ex:
                print("[time_checker] 예외 발생:", ex)


# ─────────────────────────────────────────────────────────
# 이전엔 @app.before_first_request 로 초기화했지만
# Flask 3.x에서 제거되었으므로, 아래처럼 대체
# ─────────────────────────────────────────────────────────

inited_once = False

@app.before_request
def init_once():
    global inited_once
    if not inited_once:
        init_db()
        start_time_checker()
        inited_once = True

# ─────────────────────────────────────────────────────────
# 에러 핸들러: DB 오류 등
# ─────────────────────────────────────────────────────────
@app.errorhandler(SQLiteError)
def handle_sqlite_error(e):
    flash("DB 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", "error")
    return redirect(url_for("index"))

# ─────────────────────────────────────────────────────────
# 로그인 / 로그아웃
# ─────────────────────────────────────────────────────────
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        uid = request.form.get("userid")
        pw  = request.form.get("userpw")
        if uid==ADMIN_ID and pw==ADMIN_PW:
            session["role"] = "admin"
            flash("관리자 로그인되었습니다.")
            return redirect(url_for("admin"))
        elif uid==KITCHEN_ID and pw==KITCHEN_PW:
            session["role"] = "kitchen"
            flash("주방 로그인되었습니다.")
            return redirect(url_for("kitchen"))
        else:
            flash("로그인 실패: 아이디/비밀번호를 확인하세요.")
            return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("role", None)
    flash("로그아웃 되었습니다.")
    return redirect(url_for("index"))

def login_required(fn):
    """세션에 role이 없으면 /login으로."""
    def wrapper(*args, **kwargs):
        if "role" not in session:
            flash("로그인 후 이용 가능합니다.")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper

# ─────────────────────────────────────────────────────────
# 메인 페이지
# ─────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

# ─────────────────────────────────────────────────────────
# 주문하기
# ─────────────────────────────────────────────────────────
@app.route("/order", methods=["GET","POST"])
def order():
    conn = get_db()
    cur = conn.cursor()

    # 메뉴 목록
    cur.execute("SELECT id, name, price, category, stock, soldOut FROM menu")
    menus = cur.fetchall()
    menu_items = []
    for m in menus:
        menu_items.append({
            "id": m[0],
            "name": m[1],
            "price": m[2],
            "category": m[3],
            "stock": m[4],
            "soldOut": (m[5] == 1)
        })

    settings = get_settings()

    if request.method == "POST":
        table_number   = request.form.get("tableNumber","")
        is_first_order = (request.form.get("isFirstOrder")=="true")
        people_count   = int(request.form.get("peopleCount","0") or 0)
        notice_checked = (request.form.get("noticeChecked")=="on")

        ordered_items = []
        for m in menu_items:
            qty_str = request.form.get(f"qty_{m['id']}", "0")
            qty = int(qty_str or 0)
            if qty > 0:
                ordered_items.append( (m, qty) )

        # (규칙 체크)
        if not table_number:
            flash("테이블 번호를 선택해주세요.", "error")
            return redirect(url_for("order"))

        if is_first_order:
            if not notice_checked:
                flash("최초 주문 시 주의사항 확인이 필수입니다.", "error")
                return redirect(url_for("order"))
            if people_count < 1:
                flash("최초 주문 시 인원수는 1명 이상이어야 합니다.", "error")
                return redirect(url_for("order"))

            # 메인안주 필수
            if settings["main_required_enabled"]:
                needed = people_count // settings["main_anju_ratio"]
                main_qty = sum(q for (menu_obj, q) in ordered_items if menu_obj["category"]=="main")
                if needed > 0 and main_qty < needed:
                    flash(f"인원수 대비 메인안주가 부족합니다. (필요: {needed}개)", "error")
                    return redirect(url_for("order"))

            # 맥주 제한
            if settings["beer_limit_enabled"]:
                beer_limit = settings["beer_limit_count"]
                beer_count = sum(q for (menu_obj, q) in ordered_items if menu_obj["category"]=="beer")
                if beer_count > beer_limit:
                    flash(f"최초 주문 시 맥주는 최대 {beer_limit}병까지만 가능합니다.", "error")
                    return redirect(url_for("order"))
        else:
            # 추가 주문 시 맥주 불가(예시 정책)
            if settings["beer_limit_enabled"]:
                # beer_limit = settings["beer_limit_count"]
                for (menu_obj, q) in ordered_items:
                    if menu_obj["category"]=="beer" and q>0:
                        flash("추가 주문에서는 맥주를 주문할 수 없습니다.", "error")
                        return redirect(url_for("order"))

        # 품절 체크
        for (menu_obj, q) in ordered_items:
            if menu_obj["soldOut"]:
                flash(f"품절된 메뉴[{menu_obj['name']}]는 주문 불가합니다.", "error")
                return redirect(url_for("order"))

        # 주문번호(초단위)
        new_order_id_str = str(int(time.time()))
        total_price = sum(menu_obj["price"]*q for (menu_obj, q) in ordered_items)
        now_sec = int(time.time())

        # 동시성 제어 + 트랜잭션
        with db_lock:
            try:
                cur.execute("BEGIN")
                cur.execute("""
                    INSERT INTO orders
                    (order_id, tableNumber, peopleCount, totalPrice, status, createdAt, service)
                    VALUES (?, ?, ?, ?, 'pending', ?, 0)
                """, (new_order_id_str, table_number, people_count, total_price, now_sec))
                new_db_order_id = cur.lastrowid

                for (menu_obj, q) in ordered_items:
                    cur.execute("""
                        INSERT INTO order_items
                        (order_id, menu_id, quantity, doneQuantity, deliveredQuantity)
                        VALUES (?, ?, ?, 0, 0)
                    """, (new_db_order_id, menu_obj["id"], q))

                cur.execute("COMMIT")
                flash(f"주문이 접수되었습니다 (주문번호: {new_order_id_str}).")
            except:
                cur.execute("ROLLBACK")
                flash("주문 처리 중 오류가 발생했습니다.", "error")
                return redirect(url_for("order"))

        return render_template("order_result.html",
                               total_price=total_price,
                               order_id=new_order_id_str)

    return render_template("order_form.html", menu_items=menu_items)

# ─────────────────────────────────────────────────────────
# 관리자 페이지
# ─────────────────────────────────────────────────────────
@app.route("/admin")
@login_required
def admin():
    conn = get_db()
    cur = conn.cursor()

    # pending
    cur.execute("SELECT id, order_id, tableNumber, peopleCount, totalPrice FROM orders WHERE status='pending' ORDER BY id DESC")
    pending_rows = cur.fetchall()
    pending_orders = []
    for r in pending_rows:
        row_id, oid, tnum, pcount, tprice = r
        cur.execute("""
            SELECT i.quantity, m.name
            FROM order_items i
            JOIN menu m ON i.menu_id=m.id
            WHERE i.order_id=?
        """, (row_id,))
        its = cur.fetchall()
        items_list = []
        for it in its:
            qty, mname = it
            items_list.append({
                "menuName": mname,
                "quantity": qty
            })
        pending_orders.append({
            "id": row_id,
            "order_id": oid,
            "tableNumber": tnum,
            "peopleCount": pcount,
            "totalPrice": tprice,
            "items": items_list
        })

    # paid
    cur.execute("SELECT id, order_id, tableNumber, peopleCount, totalPrice, service FROM orders WHERE status='paid' ORDER BY id DESC")
    paid_rows = cur.fetchall()
    paid_orders = []
    for r in paid_rows:
        row_id, oid, tnum, pcount, tprice, svc = r
        cur.execute("""
            SELECT i.quantity, i.doneQuantity, i.deliveredQuantity, m.name
            FROM order_items i
            JOIN menu m ON i.menu_id=m.id
            WHERE i.order_id=?
        """, (row_id,))
        its = cur.fetchall()
        items_list = []
        for it in its:
            qty, done, delv, mname = it
            items_list.append({
                "menuName": mname,
                "quantity": qty,
                "doneQuantity": done,
                "deliveredQuantity": delv
            })
        paid_orders.append({
            "id": row_id,
            "order_id": oid,
            "tableNumber": tnum,
            "totalPrice": tprice,
            "items": items_list,
            "service": (svc == 1)
        })

    # completed
    cur.execute("SELECT id, order_id, tableNumber, totalPrice, service FROM orders WHERE status='completed' ORDER BY id DESC")
    completed_rows = cur.fetchall()
    completed_orders = []
    for r in completed_rows:
        row_id, oid, tnum, tprice, svc = r
        completed_orders.append({
            "id": row_id,
            "order_id": oid,
            "tableNumber": tnum,
            "totalPrice": tprice,
            "service": (svc==1)
        })

    # 메뉴 목록
    cur.execute("SELECT id, name, price, category, stock, soldOut FROM menu")
    menu_rows = cur.fetchall()
    menu_items = []
    for m in menu_rows:
        menu_items.append({
            "id": m[0],
            "name": m[1],
            "price": m[2],
            "category": m[3],
            "stock": m[4],
            "soldOut": (m[5] == 1)
        })

    # 매출 (service=0인 paid/completed)
    cur.execute("""
        SELECT SUM(totalPrice) FROM orders
        WHERE service=0 AND (status='paid' OR status='completed')
    """)
    sales_sum = cur.fetchone()[0]
    if sales_sum is None:
        sales_sum = 0

    current_settings = get_settings()

    return render_template("admin.html",
        pending_orders=pending_orders,
        paid_orders=paid_orders,
        completed_orders=completed_orders,
        menu_items=menu_items,
        current_sales=sales_sum,
        settings=current_settings
    )

@app.route("/admin/confirm/<int:order_id>", methods=["POST"])
@login_required
def admin_confirm(order_id):
    conn = get_db()
    cur = conn.cursor()
    now_sec = int(time.time())

    with db_lock:
        try:
            cur.execute("BEGIN")
            # 상태 확인
            cur.execute("SELECT status FROM orders WHERE id=?", (order_id,))
            row = cur.fetchone()
            if not row or row[0] != "pending":
                cur.execute("ROLLBACK")
                flash("해당 주문은 'pending' 상태가 아닙니다.")
                return redirect(url_for("admin"))

            # paid로 전환
            cur.execute("""
                UPDATE orders
                SET status='paid', confirmedAt=?
                WHERE id=?
            """, (now_sec, order_id))

            # 재고 차감 & 자동조리
            cur.execute("""
                SELECT i.id, i.quantity, m.id, m.category
                FROM order_items i
                JOIN menu m ON i.menu_id=m.id
                WHERE i.order_id=?
            """, (order_id,))
            items = cur.fetchall()
            for irow in items:
                item_id, qty, menu_id, cat = irow

                # 재고 차감
                cur.execute("UPDATE menu SET stock=stock-? WHERE id=?", (qty, menu_id))

                # 재고가 음수가 됐는지 체크
                cur.execute("SELECT stock FROM menu WHERE id=?", (menu_id,))
                st = cur.fetchone()[0]
                if st < 0:
                    # 롤백
                    cur.execute("ROLLBACK")
                    flash("재고 부족으로 인한 주문 확정 실패(동시 주문 문제).", "error")
                    return redirect(url_for("admin"))

                # 소주/맥주/음료 → doneQuantity = quantity
                if cat in ["soju","beer","drink"]:
                    cur.execute("""
                        UPDATE order_items
                        SET doneQuantity=?
                        WHERE id=?
                    """, (qty, item_id))

            cur.execute("COMMIT")
            log_action(session["role"], "CONFIRM_ORDER", f"주문ID={order_id}")
            flash(f"주문 {order_id} 입금확인 완료!")
        except:
            cur.execute("ROLLBACK")
            flash("입금 확인 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/complete/<int:order_id>", methods=["POST"])
@login_required
def admin_complete(order_id):
    with db_lock:
        conn = get_db()
        cur = conn.cursor()

        try:
            cur.execute("BEGIN")
            cur.execute("SELECT status FROM orders WHERE id=?", (order_id,))
            row = cur.fetchone()
            if not row or row[0] != "paid":
                cur.execute("ROLLBACK")
                flash("해당 주문은 'paid' 상태가 아닙니다.")
                return redirect(url_for("admin"))

            cur.execute("""
                UPDATE orders
                SET status='completed'
                WHERE id=?
            """, (order_id,))

            cur.execute("COMMIT")
            log_action(session["role"], "COMPLETE_ORDER", f"주문ID={order_id}")
            flash(f"주문 {order_id} 최종 완료되었습니다!")
        except:
            cur.execute("ROLLBACK")
            flash("주문 완료 처리 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/deliver/<int:order_id>/<menu_name>", methods=["POST"])
@login_required
def admin_deliver_item(order_id, menu_name):
    with db_lock:
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("BEGIN")
            # 상태 확인
            cur.execute("SELECT status FROM orders WHERE id=?", (order_id,))
            orow = cur.fetchone()
            if not orow or orow[0] not in ["paid","completed"]:
                cur.execute("ROLLBACK")
                return redirect(url_for("admin"))

            # item 찾기
            cur.execute("""
                SELECT i.id, i.doneQuantity, i.deliveredQuantity, i.quantity
                FROM order_items i
                JOIN menu m ON i.menu_id=m.id
                WHERE i.order_id=? AND m.name=?
            """, (order_id, menu_name))
            item_row = cur.fetchone()
            if not item_row:
                cur.execute("ROLLBACK")
                flash("해당 메뉴가 주문에 없습니다.")
                return redirect(url_for("admin"))
            item_id, done_q, delivered_q, total_q = item_row

            if delivered_q < done_q:
                new_delivered = delivered_q + 1
                cur.execute("""
                    UPDATE order_items
                    SET deliveredQuantity=?
                    WHERE id=?
                """, (new_delivered, item_id))

            # 모든 item 전달완료 시 → status=completed
            cur.execute("""
                SELECT quantity, deliveredQuantity
                FROM order_items
                WHERE order_id=?
            """, (order_id,))
            all_items = cur.fetchall()
            all_delivered = all(dv >= qt for (qt, dv) in all_items)

            if all_delivered:
                cur.execute("""
                    UPDATE orders
                    SET status='completed'
                    WHERE id=?
                """, (order_id,))

            cur.execute("COMMIT")
            log_action(session["role"], "ADMIN_DELIVER_ITEM", f"{order_id}/{menu_name}")
            flash(f"주문 {order_id}, 메뉴 [{menu_name}] 1개 전달!")
        except:
            cur.execute("ROLLBACK")
            flash("전달 처리 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/soldout/<int:menu_id>", methods=["POST"])
@login_required
def admin_soldout(menu_id):
    with db_lock:
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("SELECT name, soldOut FROM menu WHERE id=?", (menu_id,))
            mrow = cur.fetchone()
            if not mrow:
                flash("해당 메뉴가 존재하지 않습니다.")
                return redirect(url_for("admin"))
            name, so = mrow
            new_val = 0 if so==1 else 1
            cur.execute("UPDATE menu SET soldOut=? WHERE id=?", (new_val, menu_id))
            conn.commit()
            log_action(session["role"], "SOLDOUT_TOGGLE", f"메뉴[{name}] => soldOut={new_val}")
            flash(f"메뉴 [{name}] 품절상태 변경!")
        except:
            flash("품절상태 변경 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/log")
@login_required
def admin_log_page():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT time, role, action, detail FROM logs ORDER BY id DESC")
    logs_raw = cur.fetchall()

    logs = []
    for lr in logs_raw:
        t, r, a, d = lr
        logs.append({
            "time": t,
            "role": r,
            "action": a,
            "detail": d
        })
    return render_template("admin_log.html", logs=logs)

@app.route("/admin/service", methods=["POST"])
@login_required
def admin_service():
    service_table = request.form.get("serviceTable","")
    service_menu  = request.form.get("serviceMenu","")
    service_qty   = int(request.form.get("serviceQty","0") or 0)

    if not service_table or not service_menu or service_qty<1:
        flash("서비스 등록 실패: 테이블/메뉴/수량 확인 필요", "error")
        return redirect(url_for("admin"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, category, soldOut, stock FROM menu WHERE name=?", (service_menu,))
    mrow = cur.fetchone()
    if not mrow:
        flash("해당 메뉴를 찾을 수 없습니다.", "error")
        return redirect(url_for("admin"))
    menu_id, cat, so, st = mrow
    if so == 1:
        flash("해당 메뉴는 품절 처리된 상태입니다.", "error")
        return redirect(url_for("admin"))

    now_sec = int(time.time())
    order_id_str = str(now_sec)

    with db_lock:
        try:
            cur.execute("BEGIN")
            # 새 주문 (status='paid', totalPrice=0, service=1)
            cur.execute("""
                INSERT INTO orders
                (order_id, tableNumber, peopleCount, totalPrice, status, createdAt, confirmedAt, service)
                VALUES (?, ?, 0, 0, 'paid', ?, ?, 1)
            """, (order_id_str, service_table, now_sec, now_sec))
            new_order_db_id = cur.lastrowid

            cur.execute("""
                INSERT INTO order_items
                (order_id, menu_id, quantity, doneQuantity, deliveredQuantity)
                VALUES (?, ?, ?, 0, 0)
            """, (new_order_db_id, menu_id, service_qty))

            # 재고 차감
            cur.execute("UPDATE menu SET stock=stock-? WHERE id=?", (service_qty, menu_id))
            # 재고 음수 체크
            cur.execute("SELECT stock FROM menu WHERE id=?", (menu_id,))
            st2 = cur.fetchone()[0]
            if st2 < 0:
                cur.execute("ROLLBACK")
                flash("재고 부족으로 서비스 등록 실패.", "error")
                return redirect(url_for("admin"))

            # 소주/맥주/음료 → 자동 조리 완료
            if cat in ["soju","beer","drink"]:
                cur.execute("""
                    UPDATE order_items
                    SET doneQuantity=?
                    WHERE order_id=? AND menu_id=?
                """, (service_qty, new_order_db_id, menu_id))

            cur.execute("COMMIT")
            log_action(session["role"], "ADMIN_SERVICE", f"주문ID={new_order_db_id} /메뉴:{service_menu}/{service_qty}")
            flash(f"0원 서비스 주문이 등록되었습니다. (주문 DB ID {new_order_db_id}, order_id={order_id_str})")
        except:
            cur.execute("ROLLBACK")
            flash("서비스 등록 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/update-settings", methods=["POST"])
@login_required
def admin_update_settings():
    update_settings(request.form)
    log_action(session["role"], "UPDATE_SETTINGS", "제한사항 업데이트")
    flash("설정이 업데이트되었습니다.")
    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 주방 페이지
# ─────────────────────────────────────────────────────────
@app.route("/kitchen")
@login_required
def kitchen():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, order_id, tableNumber
        FROM orders
        WHERE status='paid'
        ORDER BY confirmedAt ASC
    """)
    paid_orders_raw = cur.fetchall()

    paid_orders = []
    item_count = {}

    for row in paid_orders_raw:
        row_id, oid, tnum = row
        cur.execute("""
            SELECT i.id, i.quantity, i.doneQuantity, i.deliveredQuantity, m.name
            FROM order_items i
            JOIN menu m ON i.menu_id=m.id
            WHERE i.order_id=?
        """, (row_id,))
        its = cur.fetchall()
        items_list = []
        for it2 in its:
            iid, qty, done, delv, mname = it2
            items_list.append({
                "menuName": mname,
                "quantity": qty,
                "doneQuantity": done,
                "deliveredQuantity": delv
            })
            left = qty - done
            if left>0:
                item_count[mname] = item_count.get(mname,0) + left

        paid_orders.append({
            "id": row_id,
            "order_id": oid,
            "tableNumber": tnum,
            "items": items_list
        })

    return render_template("kitchen.html",
                           paid_orders=paid_orders,
                           kitchen_status=item_count)

@app.route("/kitchen/done-item/<int:order_id>/<menu_name>", methods=["POST"])
@login_required
def kitchen_done_item(order_id, menu_name):
    with db_lock:
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("BEGIN")
            cur.execute("SELECT status FROM orders WHERE id=?", (order_id,))
            orow = cur.fetchone()
            if not orow or orow[0] != "paid":
                cur.execute("ROLLBACK")
                flash("해당 주문이 'paid' 상태가 아닙니다.", "error")
                return redirect(url_for("kitchen"))

            cur.execute("""
                SELECT i.id, i.doneQuantity, i.quantity
                FROM order_items i
                JOIN menu m ON i.menu_id=m.id
                WHERE i.order_id=? AND m.name=?
            """, (order_id, menu_name))
            irow = cur.fetchone()
            if not irow:
                cur.execute("ROLLBACK")
                flash("해당 메뉴 항목이 없습니다.", "error")
                return redirect(url_for("kitchen"))
            iid, done, q = irow

            if done < q:
                new_done = done + 1
                cur.execute("""
                    UPDATE order_items
                    SET doneQuantity=?
                    WHERE id=?
                """, (new_done, iid))

            cur.execute("COMMIT")
            log_action(session["role"], "KITCHEN_DONE_ITEM", f"{order_id}/{menu_name}")
        except:
            cur.execute("ROLLBACK")
            flash("조리 완료 처리 중 오류가 발생했습니다.", "error")

    return redirect(url_for("kitchen"))

# ─────────────────────────────────────────────────────────
# 앱 실행
# ─────────────────────────────────────────────────────────
if __name__=="__main__":
    # 굳이 여기서도 init_db() & start_time_checker()를 해도 되지만
    # 지금은 @app.before_request 로 대체했으므로 생략 가능
    port = int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
