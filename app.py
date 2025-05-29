# app.py  ────────────────────────────────────────────────────────────
# Alcohol Is Free – 주문·주방·관리 시스템
# (수정사항 1‒10 반영: 2025-05-29)
# ────────────────────────────────────────────────────────────────────
import os, time, threading, traceback, pytz, datetime
from flask import (
    Flask, request, render_template, redirect,
    url_for, flash, session
)
from dotenv import load_dotenv
from sqlalchemy import (
    create_engine, Column, Integer, String,
    Boolean, ForeignKey, func, or_
)
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.exc import SQLAlchemyError

# ─────────────────────────────────────────────────────────
# 0) 환경변수
# ─────────────────────────────────────────────────────────
load_dotenv()
ADMIN_ID   = os.getenv("ADMIN_ID")
ADMIN_PW   = os.getenv("ADMIN_PW")
KITCHEN_ID = os.getenv("KITCHEN_ID")
KITCHEN_PW = os.getenv("KITCHEN_PW")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

DB_URL = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

# ─────────────────────────────────────────────────────────
# 1) Flask & SQLAlchemy 초기화
# ─────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static")
app.secret_key = os.urandom(24)

engine = create_engine(
    DB_URL,
    pool_size=10,
    max_overflow=5,
    pool_timeout=30,
    pool_recycle=1800,
    echo=False
)
SessionLocal   = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base           = declarative_base()

# ─────────────────────────────────────────────────────────
# 2) 시간 유틸
# ─────────────────────────────────────────────────────────
def current_hhmmss() -> str:
    """한국시간 HHMMSS 문자열"""
    now = datetime.datetime.now(pytz.timezone("Asia/Seoul"))
    return now.strftime("%H%M%S")

def hhmmss_to_minutes(hhmmss_str: str) -> int:
    """HHMMSS → 0-1440 분"""
    hh = int(hhmmss_str[0:2])
    mm = int(hhmmss_str[2:4])
    ss = int(hhmmss_str[4:6])
    return (hh*3600 + mm*60 + ss)//60

# ─────────────────────────────────────────────────────────
# 3) 데이터베이스 모델
# ─────────────────────────────────────────────────────────
class Menu(Base):
    __tablename__ = "menu"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    name     = Column(String(120), nullable=False)
    price    = Column(Integer, nullable=False)
    category = Column(String(30), nullable=False)      # special / main / side / dessert / options / drink
    stock    = Column(Integer, nullable=False, default=0)
    sold_out = Column(Boolean, default=False)

class Order(Base):
    __tablename__ = "orders"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    order_id    = Column(String(50), nullable=False)   # HHMMSS 기반 식별자
    tableNumber = Column(String(20), nullable=False)   # "TAKEOUT" or "1".."23"
    phoneNumber = Column(String(30))                   # TAKEOUT 시 휴대폰
    peopleCount = Column(Integer, nullable=False)      # 최초 주문이 아니면 0
    totalPrice  = Column(Integer, nullable=False)
    status      = Column(String(20), nullable=False)   # pending / paid / completed / rejected
    createdAt   = Column(Integer, nullable=False)      # HHMMSS
    confirmedAt = Column(Integer)                      # HHMMSS
    alertTime1  = Column(Integer, default=0)           # 50분 경고
    alertTime2  = Column(Integer, default=0)           # 60분 경고
    service     = Column(Boolean, default=False)       # 0원 서비스 여부
    items       = relationship("OrderItem", back_populates="order")

class OrderItem(Base):
    __tablename__ = "order_items"
    id                = Column(Integer, primary_key=True, autoincrement=True)
    order_id          = Column(Integer, ForeignKey("orders.id"), nullable=False)
    menu_id           = Column(Integer, ForeignKey("menu.id"),   nullable=False)
    quantity          = Column(Integer, nullable=False)
    doneQuantity      = Column(Integer, default=0)
    deliveredQuantity = Column(Integer, default=0)
    order = relationship("Order", back_populates="items")
    menu  = relationship("Menu")

class Log(Base):
    __tablename__ = "logs"
    id     = Column(Integer, primary_key=True, autoincrement=True)
    time   = Column(Integer, nullable=False)   # HHMMSS
    role   = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
    detail = Column(String(200), nullable=False)

class Setting(Base):
    __tablename__ = "settings"
    id            = Column(Integer, primary_key=True)
    time_warning1 = Column(Integer, default=50)  # 50분
    time_warning2 = Column(Integer, default=60)  # 60분
    total_tables  = Column(Integer, default=23)  # 1-23

class TableState(Base):
    __tablename__ = "table_state"
    tableNumber = Column(String(20), primary_key=True)
    usageStart  = Column(Integer)                # HHMMSS or None
    blocked     = Column(Boolean, default=False)

# ─────────────────────────────────────────────────────────
# 4) DB 초기화 & 샘플 데이터
# ─────────────────────────────────────────────────────────
def init_db():
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        if db.query(Menu).count() == 0:
            sample_menus = [
                # Special Set
                Menu(name="[Special Set] 안톤이고's best pick (세트)", price=29000,
                     category="special", stock=40),
                # Main dish
                Menu(name="[Main] 포크 앙 투움바", price=18000, category="main", stock=40),
                Menu(name="[Main] 루즈 & 블랑",     price=14000, category="main", stock=40),
                # Side dish
                Menu(name="[Side] 떡 롤레",       price=11000, category="side", stock=30),
                Menu(name="[Side] 그랑 포와송",   price=8000,  category="side", stock=30),
                # Dessert
                Menu(name="[Dessert] 스모어",     price=6000,  category="dessert", stock=30),
                # Options
                Menu(name="[Opt] 빵 2pcs 추가",     price=1500,  category="options", stock=50),
                Menu(name="[Opt] 숙취해소제 2pcs", price=5000,  category="options", stock=40),
                # Drink
                Menu(name="[Drink] 사이다",        price=2000,  category="drink", stock=60),
                Menu(name="[Drink] 환타 포도",      price=2000,  category="drink", stock=60),
                Menu(name="[Drink] 생수",          price=1000,  category="drink", stock=60),
            ]
            db.add_all(sample_menus)

        if not db.query(Setting).filter_by(id=1).first():
            db.add(Setting(id=1, time_warning1=50, time_warning2=60, total_tables=23))

        db.commit()

# ─────────────────────────────────────────────────────────
# 5) 로그 유틸
# ─────────────────────────────────────────────────────────
def log_action(role: str, action: str, detail: str):
    with SessionLocal() as db:
        db.add(Log(time=int(current_hhmmss()), role=role, action=action, detail=detail))
        db.commit()

# ─────────────────────────────────────────────────────────
# 6) 설정 접근
# ─────────────────────────────────────────────────────────
def get_settings() -> Setting:
    with SessionLocal() as db:
        s = db.query(Setting).filter_by(id=1).first()
        if not s:
            s = Setting(id=1); db.add(s); db.commit(); db.refresh(s)
        return s

def update_settings(form):
    with SessionLocal() as db:
        s = db.query(Setting).filter_by(id=1).first()
        s.time_warning1 = int(form.get("timeWarning1", 50))
        s.time_warning2 = int(form.get("timeWarning2", 60))
        s.total_tables  = int(form.get("totalTables", 23))
        db.commit()

# ─────────────────────────────────────────────────────────
# 7) 50/60분 경고 스레드
# ─────────────────────────────────────────────────────────
_started = False
def start_time_checker():
    global _started
    if _started:
        return
    _started = True

    def runner():
        while True:
            time.sleep(60)
            try:
                with SessionLocal() as db:
                    s = db.query(Setting).filter_by(id=1).first()
                    now_min = hhmmss_to_minutes(current_hhmmss())
                    orders = db.query(Order).filter(
                        Order.status == "paid",
                        Order.confirmedAt != None
                    ).all()

                    for o in orders:
                        diff = now_min - hhmmss_to_minutes(f"{o.confirmedAt:06d}")
                        if o.alertTime1 == 0 and diff >= s.time_warning1:
                            o.alertTime1 = 1
                            db.add(Log(time=int(current_hhmmss()),
                                       role="system", action="TIME_WARNING1",
                                       detail=f"id={o.order_id}"))
                        if o.alertTime2 == 0 and diff >= s.time_warning2:
                            o.alertTime2 = 1
                            db.add(Log(time=int(current_hhmmss()),
                                       role="system", action="TIME_WARNING2",
                                       detail=f"id={o.order_id}"))
                    db.commit()
            except Exception:
                traceback.print_exc()

    threading.Thread(target=runner, daemon=True).start()

# ─────────────────────────────────────────────────────────
# 8) 공통 에러 핸들러
# ─────────────────────────────────────────────────────────
@app.errorhandler(SQLAlchemyError)
def handle_db_error(e):
    traceback.print_exc()
    flash(f"DB 오류: {e}", "error")
    return redirect(url_for("index"))

# ─────────────────────────────────────────────────────────
# 9) 로그인 / 로그아웃
# ─────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        uid = request.form.get("userid")
        pw  = request.form.get("userpw")
        if uid == ADMIN_ID and pw == ADMIN_PW:
            session["role"] = "admin"
            flash("관리자 로그인되었습니다.")
            return redirect(url_for("admin"))
        elif uid == KITCHEN_ID and pw == KITCHEN_PW:
            session["role"] = "kitchen"
            flash("주방 로그인되었습니다.")
            return redirect(url_for("kitchen"))
        else:
            flash("로그인 실패: 아이디/비밀번호를 확인하세요.", "error")
            return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("role", None)
    flash("로그아웃 되었습니다.")
    return redirect(url_for("index"))

def login_required(fn):
    def wrapper(*args, **kwargs):
        if "role" not in session:
            flash("로그인 후 이용 가능합니다.")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper

# ─────────────────────────────────────────────────────────
# 10) 메인 페이지
# ─────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

# ─────────────────────────────────────────────────────────
# 11) 주문 페이지
# ─────────────────────────────────────────────────────────
@app.route("/order", methods=["GET", "POST"])
def order():
    with SessionLocal() as db:
        menu_list = db.query(Menu).all()
        settings  = db.query(Setting).filter_by(id=1).first()

        table_numbers = ["TAKEOUT"] + [str(i) for i in range(1, settings.total_tables + 1)]

        if request.method == "POST":
            table_number   = request.form.get("tableNumber", "")
            is_first_order = (request.form.get("isFirstOrder") == "true")
            people_count   = int(request.form.get("peopleCount", "0") or 0)
            notice_checked = (request.form.get("noticeChecked") == "on")
            phone_number   = request.form.get("phoneNumber", "").strip()

            # TAKEOUT 휴대폰 검사
            if table_number == "TAKEOUT" and not phone_number:
                flash("TAKEOUT 주문 시 휴대전화번호를 입력해주세요.", "error")
                return redirect(url_for("order"))

            # TableState 확보
            ts = db.query(TableState).filter_by(tableNumber=table_number).first()
            if not ts:
                ts = TableState(tableNumber=table_number, usageStart=None, blocked=False)
                db.add(ts); db.commit(); db.refresh(ts)

            if ts.blocked:
                flash("현재 차단된 테이블입니다. 주문 불가합니다.", "error")
                return redirect(url_for("order"))

            # 주문 메뉴 파싱
            ordered_items = []
            for m in menu_list:
                qty = int(request.form.get(f"qty_{m.id}", "0") or 0)
                if qty > 0:
                    if m.sold_out:
                        flash(f"품절된 메뉴[{m.name}]는 주문 불가합니다.", "error")
                        return redirect(url_for("order"))
                    ordered_items.append((m, qty))

            if not table_number:
                flash("테이블 번호를 선택해주세요.", "error")
                return redirect(url_for("order"))
            if not ordered_items:
                flash("하나 이상의 메뉴를 선택해주세요.", "error")
                return redirect(url_for("order"))

            # 최초 주문 제약
            if is_first_order:
                if not notice_checked:
                    flash("최초 주문 시 주의사항 확인이 필수입니다.", "error")
                    return redirect(url_for("order"))
                if people_count < 1:
                    flash("최초 주문 시 인원수는 1명 이상이어야 합니다.", "error")
                    return redirect(url_for("order"))

                needed = max(1, (people_count + 1) // 2)  # 2명당 1개, 올림
                total_main_side_dessert = sum(
                    q for (menu_obj, q) in ordered_items
                    if menu_obj.category in ["main", "side", "dessert"]
                )
                main_count = sum(
                    q for (menu_obj, q) in ordered_items
                    if menu_obj.category == "main"
                )

                if total_main_side_dessert < needed:
                    flash(f"인원수 대비 (Main/Side/Dessert) 메뉴가 부족합니다. "
                          f"(필요: {needed}개 이상)", "error")
                    return redirect(url_for("order"))
                if main_count < 1:
                    flash("Main Dish는 최소 1개 이상 포함되어야 합니다.", "error")
                    return redirect(url_for("order"))

            # 주문 저장
            new_order_id_str = current_hhmmss()
            total_price = sum(m.price * q for (m, q) in ordered_items)
            now_int = int(new_order_id_str)

            try:
                new_order = Order(
                    order_id=new_order_id_str,
                    tableNumber=table_number,
                    phoneNumber=phone_number if table_number == "TAKEOUT" else None,
                    peopleCount=people_count,
                    totalPrice=total_price,
                    status="pending",
                    createdAt=now_int,
                    confirmedAt=None,
                    alertTime1=0,
                    alertTime2=0,
                    service=False
                )
                db.add(new_order)
                db.flush()

                for (m, q) in ordered_items:
                    db.add(OrderItem(
                        order_id=new_order.id,
                        menu_id=m.id,
                        quantity=q,
                        doneQuantity=0,
                        deliveredQuantity=0
                    ))

                db.commit()
                flash(f"주문이 접수되었습니다 (주문번호: {new_order_id_str}).")

                return render_template("order_result.html",
                                       total_price=total_price,
                                       order_id=new_order_id_str)
            except Exception:
                db.rollback()
                flash("주문 처리 중 오류가 발생했습니다.", "error")
                return redirect(url_for("order"))

        return render_template("order_form.html",
                               menu_items=menu_list,
                               table_numbers=table_numbers,
                               settings=settings)

# ─────────────────────────────────────────────────────────
# 12) 관리자 페이지
# ─────────────────────────────────────────────────────────
@app.route("/admin")
@login_required
def admin():
    sort_mode = request.args.get("sort", "asc")
    sort_mode = "desc" if sort_mode == "desc" else "asc"

    with SessionLocal() as db:
        s = get_settings()
        total_tables = s.total_tables
        table_nums = ["TAKEOUT"] + [str(i) for i in range(1, total_tables + 1)]

        now_min = hhmmss_to_minutes(current_hhmmss())

        # ── 테이블 현황
        table_status_info = []
        for t in table_nums:
            ts = db.query(TableState).filter_by(tableNumber=t).first()
            if ts:
                blocked = ts.blocked
                if ts.usageStart is not None:
                    diff = now_min - hhmmss_to_minutes(f"{ts.usageStart:06d}")
                    color = ("red" if diff >= s.time_warning2 else
                             "yellow" if diff >= s.time_warning1 else
                             "normal")
                    table_status_info.append((t, f"{diff}분", color, blocked, False))
                else:
                    table_status_info.append((t, "-", "empty", blocked, True))
            else:
                table_status_info.append((t, "-", "empty", False, True))

        order_by_clause = Order.id.desc() if sort_mode == "desc" else Order.id.asc()

        # ── pending
        pending_orders = []
        for o in db.query(Order).filter_by(status="pending").order_by(order_by_clause):
            pending_orders.append({
                "id": o.id,
                "order_id": o.order_id,
                "tableNumber": o.tableNumber,
                "phone": o.phoneNumber or "",
                "peopleCount": o.peopleCount,
                "totalPrice": o.totalPrice,
                "items": [
                    {"menuName": it.menu.name, "quantity": it.quantity}
                    for it in o.items
                ],
                "is_first": (o.peopleCount > 0),
                "stock_negative_warning": any(it.menu.stock < 0 for it in o.items),
                "createdAt": o.createdAt
            })

        # ── paid
        paid_orders = []
        for o in db.query(Order).filter_by(status="paid").order_by(order_by_clause):
            paid_orders.append({
                "id": o.id,
                "order_id": o.order_id,
                "tableNumber": o.tableNumber,
                "phone": o.phoneNumber or "",
                "totalPrice": o.totalPrice,
                "service": o.service,
                "items": [
                    {
                        "menuName": it.menu.name,
                        "quantity": it.quantity,
                        "doneQuantity": it.doneQuantity,
                        "deliveredQuantity": it.deliveredQuantity
                    } for it in o.items
                ],
                "createdAt": o.createdAt
            })

        # ── completed
        completed_orders = []
        for o in db.query(Order).filter_by(status="completed").order_by(order_by_clause):
            completed_orders.append({
                "id": o.id,
                "order_id": o.order_id,
                "tableNumber": o.tableNumber,
                "totalPrice": o.totalPrice,
                "service": o.service,
                "createdAt": o.createdAt
            })

        # ── rejected
        rejected_orders = []
        for o in db.query(Order).filter_by(status="rejected").order_by(order_by_clause):
            rejected_orders.append({
                "id": o.id,
                "order_id": o.order_id,
                "tableNumber": o.tableNumber,
                "createdAt": o.createdAt
            })

        # ── 메뉴
        menu_items = [
            {
                "id": m.id,
                "name": m.name,
                "price": m.price,
                "category": m.category,
                "stock": m.stock,
                "soldOut": m.sold_out
            } for m in db.query(Menu)
        ]

        sales_sum = db.query(
            func.coalesce(func.sum(Order.totalPrice), 0)
        ).filter(
            Order.service == False,
            or_(Order.status == "paid", Order.status == "completed")
        ).scalar()

    return render_template("admin.html",
                           table_status_info=table_status_info,
                           pending_orders=pending_orders,
                           paid_orders=paid_orders,
                           completed_orders=completed_orders,
                           rejected_orders=rejected_orders,
                           menu_items=menu_items,
                           current_sales=sales_sum,
                           settings=s,
                           sort_mode=sort_mode)

# ─────────────────────────────────────────────────────────
# 13) 관리자 – 주문 상태 전환/조작
# ─────────────────────────────────────────────────────────
@app.route("/admin/confirm/<int:order_id>", methods=["POST"])
@login_required
def admin_confirm(order_id):
    with SessionLocal() as db:
        now_int = int(current_hhmmss())
        try:
            o = db.query(Order).filter_by(id=order_id).with_for_update().first()
            if not o or o.status != "pending":
                flash("해당 주문은 'pending' 상태가 아닙니다.")
                return redirect(url_for("admin"))

            o.status = "paid"
            o.confirmedAt = now_int

            # 테이블 사용 시작 기록
            if o.peopleCount > 0:
                ts = db.query(TableState).filter_by(tableNumber=o.tableNumber).first()
                if ts and ts.usageStart is None:
                    ts.usageStart = now_int

            # 재고 차감
            for it in o.items:
                m = db.query(Menu).filter_by(id=it.menu_id).with_for_update().first()
                m.stock -= it.quantity

            db.commit()
            log_action(session["role"], "CONFIRM_ORDER", f"주문ID={order_id}")
            flash(f"주문 {order_id} 입금확인 완료!")
        except Exception:
            db.rollback()
            flash("입금 확인 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/reject/<int:order_id>", methods=["POST"])
@login_required
def admin_reject(order_id):
    with SessionLocal() as db:
        try:
            o = db.query(Order).filter_by(id=order_id).with_for_update().first()
            if not o or o.status != "pending":
                flash("해당 주문은 'pending' 상태가 아닙니다.")
                return redirect(url_for("admin"))
            o.status = "rejected"
            db.commit()
            log_action(session["role"], "REJECT_ORDER", f"주문ID={order_id}")
            flash(f"주문 {order_id}를 거절 처리했습니다.")
        except Exception:
            db.rollback()
            flash("주문 거절 처리 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/complete/<int:order_id>", methods=["POST"])
@login_required
def admin_complete(order_id):
    with SessionLocal() as db:
        try:
            o = db.query(Order).filter_by(id=order_id).with_for_update().first()
            if not o or o.status != "paid":
                flash("해당 주문은 'paid' 상태가 아닙니다.")
                return redirect(url_for("admin"))
            o.status = "completed"
            db.commit()
            log_action(session["role"], "COMPLETE_ORDER", f"주문ID={order_id}")
            flash(f"주문 {order_id} 최종 완료되었습니다!")
        except Exception:
            db.rollback()
            flash("주문 완료 처리 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/deliver_item_count/<int:order_id>/<menu_name>", methods=["POST"])
@login_required
def admin_deliver_item_count(order_id, menu_name):
    count_str = request.form.get("deliver_count", "0")
    try:
        count = int(count_str)
    except ValueError:
        count = 0

    if count < 1:
        flash("잘못된 전달 수량입니다.", "error")
        return redirect(url_for("admin"))

    with SessionLocal() as db:
        try:
            o = db.query(Order).filter_by(id=order_id).with_for_update().first()
            if not o or o.status not in ["paid", "completed"]:
                flash("해당 주문 상태가 조리중이 아닙니다.", "error")
                return redirect(url_for("admin"))

            it = next((i for i in o.items if i.menu.name == menu_name), None)
            if not it:
                flash("해당 메뉴가 주문에 없습니다.", "error")
                return redirect(url_for("admin"))

            left_deliver = it.doneQuantity - it.deliveredQuantity
            if left_deliver <= 0 or count > left_deliver:
                flash("잘못된 전달 수량입니다.", "error")
                return redirect(url_for("admin"))

            it.deliveredQuantity += count

            # 모든 아이템 전달 완료?
            if all(x.deliveredQuantity >= x.quantity for x in o.items):
                o.status = "completed"

            db.commit()
            log_action(session["role"], "ADMIN_DELIVER_ITEM",
                       f"{order_id}/{menu_name}/{count}")
            flash(f"주문 {o.order_id} (ID={o.id}), [{menu_name}] {count}개 전달 완료!")
        except Exception:
            db.rollback()
            flash("전달 처리 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/soldout/<int:menu_id>", methods=["POST"])
@login_required
def admin_soldout(menu_id):
    with SessionLocal() as db:
        try:
            m = db.query(Menu).filter_by(id=menu_id).first()
            m.sold_out = not m.sold_out
            db.commit()
            log_action(session["role"], "SOLDOUT_TOGGLE",
                       f"메뉴[{m.name}] => soldOut={m.sold_out}")
            flash(f"메뉴 [{m.name}] 품절상태 변경!")
        except Exception:
            db.rollback()
            flash("품절상태 변경 중 오류가 발생했습니다.", "error")
    return redirect(url_for("admin"))

@app.route("/admin/log")
@login_required
def admin_log_page():
    role_filter   = request.args.get("role", "")
    action_filter = request.args.get("action", "")
    detail_filter = request.args.get("detail", "")
    time_start    = request.args.get("time_start", "")
    time_end      = request.args.get("time_end", "")

    with SessionLocal() as db:
        q = db.query(Log)
        if role_filter:
            q = q.filter(Log.role.ilike(f"%{role_filter}%"))
        if action_filter:
            q = q.filter(Log.action.ilike(f"%{action_filter}%"))
        if detail_filter:
            q = q.filter(Log.detail.ilike(f"%{detail_filter}%"))
        if time_start.isdigit() and len(time_start) == 6:
            q = q.filter(Log.time >= int(time_start))
        if time_end.isdigit() and len(time_end) == 6:
            q = q.filter(Log.time <= int(time_end))

        logs = [{
            "time": f"{l.time:06d}",
            "role": l.role,
            "action": l.action,
            "detail": l.detail
        } for l in q.order_by(Log.id.desc())]

    return render_template("admin_log.html", logs=logs,
                           role_filter=role_filter,
                           action_filter=action_filter,
                           detail_filter=detail_filter,
                           time_start=time_start,
                           time_end=time_end)

@app.route("/admin/service", methods=["POST"])
@login_required
def admin_service():
    table = request.form.get("serviceTable", "")
    menu_name = request.form.get("serviceMenu", "")
    qty = int(request.form.get("serviceQty", "0") or 0)

    if not table or not menu_name or qty < 1:
        flash("서비스 등록 실패: 테이블/메뉴/수량 확인 필요", "error")
        return redirect(url_for("admin"))

    with SessionLocal() as db:
        ts = db.query(TableState).filter_by(tableNumber=table).first()
        if not ts:
            ts = TableState(tableNumber=table, usageStart=None, blocked=False)
            db.add(ts); db.commit(); db.refresh(ts)

        if ts.blocked:
            flash("차단된 테이블에는 서비스를 등록할 수 없습니다.", "error")
            return redirect(url_for("admin"))

        m = db.query(Menu).filter_by(name=menu_name).with_for_update().first()
        if not m:
            flash("해당 메뉴가 존재하지 않습니다.", "error")
            return redirect(url_for("admin"))
        if m.sold_out:
            flash("해당 메뉴는 품절 상태입니다.", "error")
            return redirect(url_for("admin"))

        now_str = current_hhmmss()
        now_int = int(now_str)
        try:
            new_order = Order(
                order_id=now_str,
                tableNumber=table,
                phoneNumber=None,
                peopleCount=0,
                totalPrice=0,
                status="paid",
                createdAt=now_int,
                confirmedAt=now_int,
                service=True
            )
            db.add(new_order)
            db.flush()

            db.add(OrderItem(order_id=new_order.id, menu_id=m.id,
                             quantity=qty, doneQuantity=0, deliveredQuantity=0))
            m.stock -= qty

            db.commit()
            log_action(session["role"], "ADMIN_SERVICE",
                       f"주문ID={new_order.id}/메뉴:{menu_name}/{qty}")
            flash(f"0원 서비스 주문이 등록되었습니다. (order_id={now_str})")
        except Exception:
            db.rollback()
            flash("서비스 등록 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/update-settings", methods=["POST"])
@login_required
def admin_update_settings():
    update_settings(request.form)
    log_action(session["role"], "UPDATE_SETTINGS", "설정 업데이트")
    flash("설정이 업데이트되었습니다.")
    return redirect(url_for("admin"))

@app.route("/admin/update_stock/<int:menu_id>", methods=["POST"])
@login_required
def admin_update_stock(menu_id):
    new_stock_str = request.form.get("new_stock", "0")
    try:
        new_stock = int(new_stock_str)
    except ValueError:
        flash("잘못된 재고 입력값입니다.", "error")
        return redirect(url_for("admin"))

    with SessionLocal() as db:
        try:
            m = db.query(Menu).filter_by(id=menu_id).first()
            old_stock = m.stock
            m.stock = new_stock
            db.commit()
            log_action(session["role"], "UPDATE_STOCK",
                       f"메뉴[{m.name}], {old_stock} -> {new_stock}")
            flash(f"메뉴 [{m.name}] 재고가 {new_stock} 으로 수정되었습니다.")
        except Exception:
            db.rollback()
            flash("재고 수정 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 14) 주방 페이지
# ─────────────────────────────────────────────────────────
@app.route("/kitchen")
@login_required
def kitchen():
    with SessionLocal() as db:
        paid_orders = db.query(Order).filter_by(status="paid").all()
        item_count = {}
        for o in paid_orders:
            for it in o.items:
                left = it.quantity - it.doneQuantity
                if left > 0:
                    item_count[it.menu.name] = item_count.get(it.menu.name, 0) + left

    return render_template("kitchen.html", kitchen_status=item_count)

@app.route("/kitchen/done-item/<menu_name>", methods=["POST"])
@login_required
def kitchen_done_item(menu_name):
    count_str = request.form.get("done_count", "0")
    try:
        count = int(count_str)
    except ValueError:
        count = 0

    if count < 1:
        flash("잘못된 조리 완료 수량입니다.", "error")
        return redirect(url_for("kitchen"))

    with SessionLocal() as db:
        try:
            orders = db.query(Order).filter_by(status="paid").order_by(Order.id.asc()).all()
            remaining = count
            for o in orders:
                for it in o.items:
                    if it.menu.name == menu_name:
                        left = it.quantity - it.doneQuantity
                        if left > 0:
                            if left <= remaining:
                                it.doneQuantity += left
                                remaining -= left
                            else:
                                it.doneQuantity += remaining
                                remaining = 0
                            if remaining <= 0:
                                break
                if remaining <= 0:
                    break

            log_action(session["role"], "KITCHEN_DONE_ITEM",
                       f"{menu_name} {count}개 조리완료")
            db.commit()
            flash(f"[{menu_name}] {count}개 조리 완료 처리.")
        except Exception:
            db.rollback()
            flash("조리 완료 처리 중 오류가 발생했습니다.", "error")

    return redirect(url_for("kitchen"))

# ─────────────────────────────────────────────────────────
# 15) 앱 시작
# ─────────────────────────────────────────────────────────
init_db()
start_time_checker()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
