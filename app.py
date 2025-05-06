import os
import time
import threading
import traceback
import pytz
import datetime

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
# 환경변수 로드
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
# Flask, SQLAlchemy 초기화
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

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# ─────────────────────────────────────────────────────────
# 시간 유틸
# ─────────────────────────────────────────────────────────
def current_hhmmss():
    """한국시간(Asia/Seoul)을 HHMMSS 형태 문자열로 반환 (예: '221305')"""
    now = datetime.datetime.now(pytz.timezone('Asia/Seoul'))
    return now.strftime("%H%M%S")

def hhmmss_to_minutes(hhmmss_str):
    """
    HHMMSS 형태 문자열(예: '221305') -> 하루 기준 분 단위로 환산.
    """
    hh = int(hhmmss_str[0:2])
    mm = int(hhmmss_str[2:4])
    ss = int(hhmmss_str[4:6])
    total_seconds = hh * 3600 + mm * 60 + ss
    return total_seconds // 60

# ─────────────────────────────────────────────────────────
# 모델 정의
# ─────────────────────────────────────────────────────────

class Menu(Base):
    __tablename__ = "menu"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    name     = Column(String(100), nullable=False)
    price    = Column(Integer, nullable=False)
    category = Column(String(50), nullable=False)  # main, side, dessert, etc, drink
    stock    = Column(Integer, nullable=False, default=0)
    sold_out = Column(Boolean, default=False)

class Order(Base):
    __tablename__ = "orders"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    order_id    = Column(String(50), nullable=False)
    tableNumber = Column(String(50), nullable=False)
    peopleCount = Column(Integer, nullable=False)
    totalPrice  = Column(Integer, nullable=False)
    status      = Column(String(20), nullable=False)  # pending, paid, completed, rejected
    createdAt   = Column(Integer, nullable=False)     # HHMMSS(정수)
    confirmedAt = Column(Integer)                     # HHMMSS(정수)
    alertTime1  = Column(Integer, default=0)          # 0 또는 1
    alertTime2  = Column(Integer, default=0)          # 0 또는 1
    service     = Column(Boolean, default=False)
    items       = relationship("OrderItem", back_populates="order")

class OrderItem(Base):
    __tablename__ = "order_items"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    order_id         = Column(Integer, ForeignKey("orders.id"), nullable=False)
    menu_id          = Column(Integer, ForeignKey("menu.id"), nullable=False)
    quantity         = Column(Integer, nullable=False)
    doneQuantity     = Column(Integer, default=0)
    deliveredQuantity= Column(Integer, default=0)
    order            = relationship("Order", back_populates="items")
    menu             = relationship("Menu")

class Log(Base):
    __tablename__ = "logs"
    id     = Column(Integer, primary_key=True, autoincrement=True)
    time   = Column(Integer, nullable=False)   # HHMMSS
    role   = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
    detail = Column(String(200), nullable=False)

class Setting(Base):
    __tablename__ = "settings"
    id           = Column(Integer, primary_key=True)
    # beer/메인안주 관련 필드는 제거
    time_warning1 = Column(Integer, default=50)
    time_warning2 = Column(Integer, default=60)
    total_tables  = Column(Integer, default=12)

class TableState(Base):
    """
    _table_usage_start 및 _blocked_tables를 DB로 관리하기 위한 모델
    """
    __tablename__ = "table_state"
    tableNumber = Column(String(50), primary_key=True)  # 'TAKEOUT' or '1' ~ ...
    usageStart  = Column(Integer, nullable=True)        # HHMMSS(정수), None이면 아직 사용 시작 안 함
    blocked     = Column(Boolean, default=False)        # 차단 여부

# ─────────────────────────────────────────────────────────
# DB 초기화 & 기본데이터 삽입
# ─────────────────────────────────────────────────────────
def init_db():
    Base.metadata.create_all(bind=engine)

    # 초기 데이터 세팅
    with SessionLocal() as db:
        # 메뉴가 없다면, 새로 추가
        if db.query(Menu).count() == 0:
            sample_menus = [
                # Main Dish
                Menu(name="두부김치 (Rouge & Blanc)",       price=8000,  category="main",    stock=10),
                Menu(name="포크찹 투움바 (Pork en Toowoomba)", price=15000, category="main",    stock=7),
                # Side Dish
                Menu(name="먹태 (Grand Poisson)",           price=12000, category="side",    stock=5),
                Menu(name="베이컨 떡말이 (Tteok Roulé)",      price=9000,  category="side",    stock=8),
                # Dessert
                Menu(name="화채 (Punch aux Fruits)",         price=7000,  category="dessert", stock=10),
                # 기타
                Menu(name="빵추가 (baguette)",               price=3000,  category="etc",     stock=20),
                Menu(name="숙취해소제 (condition bâton)",      price=5000,  category="etc",     stock=15),
                # 주류/음료 (drink)
                Menu(name="소주 (Le soju)",                 price=4000,  category="drink",   stock=50),
                Menu(name="사이다",                         price=2000,  category="drink",   stock=40),
                Menu(name="환타 포도맛",                     price=2000,  category="drink",   stock=40),
                Menu(name="생수 (1000원)",                   price=1000,  category="drink",   stock=50),
            ]
            db.add_all(sample_menus)

        # Setting: 1행만 존재
        if not db.query(Setting).filter_by(id=1).first():
            s = Setting(
                id=1,
                time_warning1=50,
                time_warning2=60,
                total_tables=12
            )
            db.add(s)

        db.commit()

def log_action(role, action, detail):
    with SessionLocal() as db:
        now_int = int(current_hhmmss())
        db.add(Log(time=now_int, role=role, action=action, detail=detail))
        db.commit()

def get_settings():
    with SessionLocal() as db:
        s = db.query(Setting).filter_by(id=1).first()
        if not s:
            s = Setting(id=1)
            db.add(s)
            db.commit()
            db.refresh(s)
        return s

def update_settings(form):
    with SessionLocal() as db:
        s = db.query(Setting).filter_by(id=1).first()
        # beer 관련 필드는 제거되었으므로 없음
        s.time_warning1  = int(form.get("timeWarning1","50") or 50)
        s.time_warning2  = int(form.get("timeWarning2","60") or 60)
        s.total_tables   = int(form.get("totalTables","12") or 12)
        db.commit()

# ─────────────────────────────────────────────────────────
# 50/60분 체크 쓰레드
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
                    now_str = current_hhmmss()
                    now_min = hhmmss_to_minutes(now_str)

                    orders = db.query(Order).filter(Order.status=="paid", Order.confirmedAt!=None).all()
                    for o in orders:
                        c_str = f"{o.confirmedAt:06d}"
                        confirm_min = hhmmss_to_minutes(c_str)
                        diff = now_min - confirm_min

                        # time_warning1
                        if o.alertTime1==0 and diff>=s.time_warning1:
                            o.alertTime1=1
                            db.add(Log(time=int(current_hhmmss()), role="system",
                                       action="TIME_WARNING1",
                                       detail=f"id={o.order_id}"))
                            db.commit()
                        # time_warning2
                        if o.alertTime2==0 and diff>=s.time_warning2:
                            o.alertTime2=1
                            db.add(Log(time=int(current_hhmmss()), role="system",
                                       action="TIME_WARNING2",
                                       detail=f"id={o.order_id}"))
                            db.commit()

            except Exception:
                traceback.print_exc()
    threading.Thread(target=runner, daemon=True).start()

# ─────────────────────────────────────────────────────────
# 에러 핸들러
# ─────────────────────────────────────────────────────────
@app.errorhandler(SQLAlchemyError)
def handle_db_error(e):
    traceback.print_exc()
    flash(f"DB 오류: {e}", "error")
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
# 테이블 empty / block
# ─────────────────────────────────────────────────────────
@app.route("/admin/empty_table/<table_num>", methods=["POST"])
@login_required
def admin_empty_table(table_num):
    with SessionLocal() as db:
        ts = db.query(TableState).filter_by(tableNumber=table_num).first()
        if ts:
            ts.usageStart = None
            # 비우는 것이므로 peopleCount=0 등 처리를 할 수도 있으나,
            # 주문 자체는 orders 테이블에 남아있음 (기록).
        db.commit()
    flash(f"{table_num}번 테이블이(가) 비워졌습니다.")
    log_action(session["role"], "EMPTY_TABLE", f"table={table_num}")
    return redirect(url_for("admin"))

@app.route("/admin/block_table/<table_num>", methods=["POST"])
@login_required
def admin_block_table(table_num):
    with SessionLocal() as db:
        ts = db.query(TableState).filter_by(tableNumber=table_num).first()
        if not ts:
            # 없는 경우 새로 생성
            ts = TableState(tableNumber=table_num, usageStart=None, blocked=False)
            db.add(ts)
            db.commit()
            db.refresh(ts)

        if ts.blocked:
            ts.blocked = False
            db.commit()
            flash(f"{table_num}번 테이블의 차단이 해제되었습니다.")
            log_action(session["role"], "UNBLOCK_TABLE", f"table={table_num}")
        else:
            ts.blocked = True
            db.commit()
            flash(f"{table_num}번 테이블을 차단했습니다.")
            log_action(session["role"], "BLOCK_TABLE", f"table={table_num}")

    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 주문하기
# ─────────────────────────────────────────────────────────
@app.route("/order", methods=["GET","POST"])
def order():
    with SessionLocal() as db:
        menu_list = db.query(Menu).all()
        settings  = db.query(Setting).filter_by(id=1).first()

        table_numbers = ["TAKEOUT"] + [str(i) for i in range(1, settings.total_tables+1)]

        if request.method=="POST":
            table_number   = request.form.get("tableNumber","")
            is_first_order = (request.form.get("isFirstOrder")=="true")
            people_count   = int(request.form.get("peopleCount","0") or 0)
            notice_checked = (request.form.get("noticeChecked")=="on")

            # TableState 가져오기 / 없는 경우 새로 생성
            ts = db.query(TableState).filter_by(tableNumber=table_number).first()
            if not ts:
                ts = TableState(tableNumber=table_number, usageStart=None, blocked=False)
                db.add(ts)
                db.commit()
                db.refresh(ts)

            if ts.blocked:
                flash("현재 차단된 테이블입니다. 주문 불가합니다.", "error")
                return redirect(url_for("order"))

            ordered_items = []
            for m in menu_list:
                qty_str = request.form.get(f"qty_{m.id}", "0")
                qty = int(qty_str or 0)
                if qty > 0:
                    if m.sold_out:
                        flash(f"품절된 메뉴[{m.name}]는 주문 불가합니다.", "error")
                        return redirect(url_for("order"))
                    ordered_items.append((m, qty))

            if not table_number:
                flash("테이블 번호를 선택해주세요.", "error")
                return redirect(url_for("order"))

            if is_first_order:
                # 주의사항 체크
                if not notice_checked:
                    flash("최초 주문 시 주의사항 확인이 필수입니다.", "error")
                    return redirect(url_for("order"))

                if people_count < 1:
                    flash("최초 주문 시 인원수는 1명 이상이어야 합니다.", "error")
                    return redirect(url_for("order"))

                # [새로운 제한사항] 2명당 Main+Side+Dessert 합쳐서 최소 1개, 그리고 Main Dish >= 1
                needed = people_count // 2
                if needed < 1:
                    needed = 1  # 최소 1개는 시켜야 한다고 해석 (1명일 때도)

                total_main_side_dessert = 0
                main_count = 0
                for (menu_obj, q) in ordered_items:
                    if menu_obj.category in ["main","side","dessert"]:
                        total_main_side_dessert += q
                    if menu_obj.category == "main":
                        main_count += q

                if total_main_side_dessert < needed:
                    flash(f"인원수 대비 (Main/Side/Dessert) 메뉴가 부족합니다. (필요: {needed}개 이상)", "error")
                    return redirect(url_for("order"))

                if main_count < 1:
                    flash(f"메인(Main Dish)은 최소 1개 이상 포함되어야 합니다.", "error")
                    return redirect(url_for("order"))
            else:
                # 추가 주문 시에는 별도의 제한 없음 (맥주 로직 등 제거됨)
                pass

            # 주문 생성
            new_order_id_str = current_hhmmss()
            total_price = sum(m.price*q for (m,q) in ordered_items)
            now_int = int(current_hhmmss())

            try:
                new_order = Order(
                    order_id=new_order_id_str,
                    tableNumber=table_number,
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

                for (m,q) in ordered_items:
                    oi = OrderItem(
                        order_id=new_order.id,
                        menu_id=m.id,
                        quantity=q,
                        doneQuantity=0,
                        deliveredQuantity=0
                    )
                    db.add(oi)

                db.commit()
                flash(f"주문이 접수되었습니다 (주문번호: {new_order_id_str}).")
                return render_template("order_result.html",
                                       total_price=total_price,
                                       order_id=new_order_id_str)
            except:
                db.rollback()
                flash("주문 처리 중 오류가 발생했습니다.", "error")
                return redirect(url_for("order"))

        return render_template("order_form.html",
                               menu_items=menu_list,
                               table_numbers=table_numbers,
                               settings=settings)

# ─────────────────────────────────────────────────────────
# 관리자 페이지
# ─────────────────────────────────────────────────────────
@app.route("/admin")
@login_required
def admin():
    sort_mode = request.args.get("sort","asc")
    if sort_mode not in ["asc","desc"]:
        sort_mode = "asc"

    with SessionLocal() as db:
        s = db.query(Setting).filter_by(id=1).first()
        total_tables = s.total_tables

        table_list = ["TAKEOUT"] + [str(i) for i in range(1, total_tables+1)]

        now_str = current_hhmmss()
        now_min = hhmmss_to_minutes(now_str)

        # 테이블 현황 표시용
        table_status_info = []
        for t in table_list:
            ts = db.query(TableState).filter_by(tableNumber=t).first()
            if ts:
                blocked = ts.blocked
                if ts.usageStart is not None:
                    c_str = f"{ts.usageStart:06d}"
                    c_min = hhmmss_to_minutes(c_str)
                    diff = now_min - c_min
                    color = ""
                    if diff >= s.time_warning2:
                        color = "red"
                    elif diff >= s.time_warning1:
                        color = "yellow"
                    else:
                        color = "normal"
                    table_status_info.append((t, f"{diff}분", color, blocked, False))
                else:
                    table_status_info.append((t, "-", "empty", blocked, True))
            else:
                # DB에 기록조차 없으면 => 아직 empty로 간주
                table_status_info.append((t, "-", "empty", False, True))

        if sort_mode=="asc":
            order_by_clause = Order.id.asc()
        else:
            order_by_clause = Order.id.desc()

        # pending
        pending_orders = []
        pending_q = db.query(Order).filter_by(status="pending").order_by(order_by_clause)
        for o in pending_q:
            items = [{"menuName": it.menu.name, "quantity": it.quantity} for it in o.items]
            # 최초 주문?
            is_first = (o.peopleCount > 0)
            # 최근 최초 주문 시각
            recent_first_order = db.query(Order)\
                .filter(Order.tableNumber==o.tableNumber, Order.peopleCount>0)\
                .order_by(Order.id.desc()).first()
            recent_first_time  = recent_first_order.order_id if recent_first_order else ""
            stock_negative_warning = any(it.menu.stock<0 for it in o.items)

            pending_orders.append({
                "id": o.id,
                "order_id": o.order_id,
                "tableNumber": o.tableNumber,
                "peopleCount": o.peopleCount,
                "totalPrice": o.totalPrice,
                "items": items,
                "is_first": is_first,
                "recent_first_time": recent_first_time,
                "stock_negative_warning": stock_negative_warning,
                "createdAt": o.createdAt
            })

        # paid
        paid_orders = []
        paid_q = db.query(Order).filter_by(status="paid").order_by(order_by_clause)
        for o in paid_q:
            items = []
            for it in o.items:
                items.append({
                    "menuName": it.menu.name,
                    "quantity": it.quantity,
                    "doneQuantity": it.doneQuantity,
                    "deliveredQuantity": it.deliveredQuantity
                })
            paid_orders.append({
                "id": o.id,
                "order_id": o.order_id,
                "tableNumber": o.tableNumber,
                "totalPrice": o.totalPrice,
                "items": items,
                "service": o.service,
                "createdAt": o.createdAt
            })

        # completed
        completed_orders = []
        completed_q = db.query(Order).filter_by(status="completed").order_by(order_by_clause)
        for o in completed_q:
            completed_orders.append({
                "id": o.id,
                "order_id": o.order_id,
                "tableNumber": o.tableNumber,
                "totalPrice": o.totalPrice,
                "service": o.service,
                "createdAt": o.createdAt
            })

        # rejected
        rejected_orders = []
        rejected_q = db.query(Order).filter_by(status="rejected").order_by(order_by_clause)
        for o in rejected_q:
            rejected_orders.append({
                "id": o.id,
                "order_id": o.order_id,
                "tableNumber": o.tableNumber,
                "createdAt": o.createdAt
            })

        menu_items = []
        all_menus = db.query(Menu).all()
        for m in all_menus:
            menu_items.append({
                "id": m.id,
                "name": m.name,
                "price": m.price,
                "category": m.category,
                "stock": m.stock,
                "soldOut": m.sold_out
            })

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
        sort_mode=sort_mode
    )

@app.route("/admin/confirm/<int:order_id>", methods=["POST"])
@login_required
def admin_confirm(order_id):
    with SessionLocal() as db:
        now_int = int(current_hhmmss())
        try:
            o = db.query(Order).filter_by(id=order_id).with_for_update().first()
            if not o or o.status!="pending":
                flash("해당 주문은 'pending' 상태가 아닙니다.")
                return redirect(url_for("admin"))

            o.status = "paid"
            o.confirmedAt = now_int

            # usageStart 설정
            if o.peopleCount > 0:
                # TableState 가져오기
                ts = db.query(TableState).filter_by(tableNumber=o.tableNumber).first()
                if ts and ts.usageStart is None:
                    ts.usageStart = now_int

            # 재고 차감
            for it in o.items:
                m = db.query(Menu).filter_by(id=it.menu_id).with_for_update().first()
                m.stock -= it.quantity
                # 음료류/주류 등은 doneQuantity = quantity로 표시(조리 불필요) ? 
                # 여기서는 별도 구분 없이 그대로 둡니다.

            db.commit()
            log_action(session["role"], "CONFIRM_ORDER", f"주문ID={order_id}")
            flash(f"주문 {order_id} 입금확인 완료!")
        except:
            db.rollback()
            flash("입금 확인 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/reject/<int:order_id>", methods=["POST"])
@login_required
def admin_reject(order_id):
    with SessionLocal() as db:
        try:
            o = db.query(Order).filter_by(id=order_id).with_for_update().first()
            if not o or o.status!="pending":
                flash("해당 주문은 'pending' 상태가 아닙니다.")
                return redirect(url_for("admin"))
            o.status = "rejected"
            db.commit()
            log_action(session["role"], "REJECT_ORDER", f"주문ID={order_id}")
            flash(f"주문 {order_id}를 거절 처리했습니다.")
        except:
            db.rollback()
            flash("주문 거절 처리 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/complete/<int:order_id>", methods=["POST"])
@login_required
def admin_complete(order_id):
    with SessionLocal() as db:
        try:
            o = db.query(Order).filter_by(id=order_id).with_for_update().first()
            if not o or o.status!="paid":
                flash("해당 주문은 'paid' 상태가 아닙니다.")
                return redirect(url_for("admin"))
            o.status = "completed"
            db.commit()
            log_action(session["role"], "COMPLETE_ORDER", f"주문ID={order_id}")
            flash(f"주문 {order_id} 최종 완료되었습니다!")
        except:
            db.rollback()
            flash("주문 완료 처리 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/deliver_item_count/<int:order_id>/<menu_name>", methods=["POST"])
@login_required
def admin_deliver_item_count(order_id, menu_name):
    """
    드롭다운으로 전달 수량을 받아서 처리
    """
    count_str = request.form.get("deliver_count", "0")
    try:
        count = int(count_str)
    except:
        count = 0

    with SessionLocal() as db:
        try:
            o = db.query(Order).filter_by(id=order_id).with_for_update().first()
            if not o or o.status not in ["paid","completed"]:
                flash("해당 주문 상태가 조리중이 아닙니다.", "error")
                return redirect(url_for("admin"))

            it = None
            for i in o.items:
                if i.menu.name == menu_name:
                    it = i
                    break
            if not it:
                flash("해당 메뉴가 주문에 없습니다.", "error")
                return redirect(url_for("admin"))

            left_deliver = it.doneQuantity - it.deliveredQuantity
            if left_deliver <= 0:
                flash("더 이상 전달할 수 없습니다.", "error")
                return redirect(url_for("admin"))

            if count < 1 or count > left_deliver:
                flash("잘못된 전달 수량입니다.", "error")
                return redirect(url_for("admin"))

            it.deliveredQuantity += count
            # 모든 아이템이 deliveredQuantity >= quantity 면 주문상태 completed
            all_delivered = True
            for x in o.items:
                if x.deliveredQuantity < x.quantity:
                    all_delivered = False
                    break
            if all_delivered:
                o.status = "completed"

            db.commit()
            flash(f"주문 {o.order_id} (ID={o.id}), [{menu_name}] {count}개 전달 완료!")
            log_action(session["role"], "ADMIN_DELIVER_ITEM", f"{order_id}/{menu_name}/{count}")
        except:
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
            log_action(session["role"], "SOLDOUT_TOGGLE", f"메뉴[{m.name}] => soldOut={m.sold_out}")
            flash(f"메뉴 [{m.name}] 품절상태 변경!")
        except:
            db.rollback()
            flash("품절상태 변경 중 오류가 발생했습니다.", "error")
    return redirect(url_for("admin"))

@app.route("/admin/log")
@login_required
def admin_log_page():
    role_filter = request.args.get("role","")
    action_filter = request.args.get("action","")
    detail_filter = request.args.get("detail","")
    time_start    = request.args.get("time_start","")
    time_end      = request.args.get("time_end","")

    with SessionLocal() as db:
        q = db.query(Log)
        if role_filter:
            q = q.filter(Log.role.ilike(f"%{role_filter}%"))
        if action_filter:
            q = q.filter(Log.action.ilike(f"%{action_filter}%"))
        if detail_filter:
            q = q.filter(Log.detail.ilike(f"%{detail_filter}%"))
        if time_start.isdigit() and len(time_start)==6:
            q = q.filter(Log.time >= int(time_start))
        if time_end.isdigit() and len(time_end)==6:
            q = q.filter(Log.time <= int(time_end))

        logs = []
        for l in q.order_by(Log.id.desc()):
            logs.append({
                "time": f"{l.time:06d}",
                "role": l.role,
                "action": l.action,
                "detail": l.detail
            })

    return render_template("admin_log.html", logs=logs,
                           role_filter=role_filter,
                           action_filter=action_filter,
                           detail_filter=detail_filter,
                           time_start=time_start,
                           time_end=time_end)

@app.route("/admin/service", methods=["POST"])
@login_required
def admin_service():
    table = request.form.get("serviceTable","")
    menu_name = request.form.get("serviceMenu","")
    qty = int(request.form.get("serviceQty","0") or 0)

    if not table or not menu_name or qty<1:
        flash("서비스 등록 실패: 테이블/메뉴/수량 확인 필요", "error")
        return redirect(url_for("admin"))

    with SessionLocal() as db:
        ts = db.query(TableState).filter_by(tableNumber=table).first()
        if not ts:
            ts = TableState(tableNumber=table, usageStart=None, blocked=False)
            db.add(ts)
            db.commit()
            db.refresh(ts)

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
                peopleCount=0,
                totalPrice=0,
                status="paid",
                createdAt=now_int,
                confirmedAt=now_int,
                service=True
            )
            db.add(new_order)
            db.flush()

            oi = OrderItem(order_id=new_order.id, menu_id=m.id,
                           quantity=qty, doneQuantity=0, deliveredQuantity=0)
            db.add(oi)
            m.stock -= qty

            db.commit()
            log_action(session["role"], "ADMIN_SERVICE",
                       f"주문ID={new_order.id}/메뉴:{menu_name}/{qty}")
            flash(f"0원 서비스 주문이 등록되었습니다. (order_id={now_str})")
        except:
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
    new_stock_str = request.form.get("new_stock","0")
    try:
        new_stock = int(new_stock_str)
    except:
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
        except:
            db.rollback()
            flash("재고 수정 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 주방 페이지
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
                if left>0:
                    item_count[it.menu.name] = item_count.get(it.menu.name, 0) + left

    return render_template("kitchen.html", kitchen_status=item_count)

@app.route("/kitchen/done-item/<menu_name>", methods=["POST"])
@login_required
def kitchen_done_item(menu_name):
    """조리 완료 수량을 드롭다운으로 전달받아 한 번에 처리"""
    count_str = request.form.get("done_count","0")
    try:
        count = int(count_str)
    except:
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
                        if left>0:
                            if left <= remaining:
                                it.doneQuantity += left
                                remaining -= left
                            else:
                                it.doneQuantity += remaining
                                remaining = 0
                            if remaining<=0:
                                break
                if remaining<=0:
                    break
            log_action(session["role"], "KITCHEN_DONE_ITEM", f"{menu_name} {count}개 조리완료")
            db.commit()
            flash(f"[{menu_name}] {count}개 조리 완료 처리.")
        except:
            db.rollback()
            flash("조리 완료 처리 중 오류가 발생했습니다.", "error")

    return redirect(url_for("kitchen"))

# ─────────────────────────────────────────────────────────
# 앱 시작
# ─────────────────────────────────────────────────────────
init_db()
start_time_checker()

if __name__=="__main__":
    port = int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
