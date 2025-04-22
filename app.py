import os
import time
import threading
import math
import traceback
from flask import (
    Flask, request, render_template, redirect,
    url_for, flash, session, g
)
from dotenv import load_dotenv
from sqlalchemy import (
    create_engine, Column, Integer, String,
    Boolean, ForeignKey, text
)
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

app = Flask(__name__, static_folder="static")
app.secret_key = os.urandom(24)

# ─────────────────────────────────────────────────────────
# AWS MySQL 접속 정보 & 관리자/주방 계정
# ─────────────────────────────────────────────────────────
ADMIN_ID   = os.getenv("ADMIN_ID", "admin")
ADMIN_PW   = os.getenv("ADMIN_PW", "admin123")
KITCHEN_ID = os.getenv("KITCHEN_ID", "kitchen")
KITCHEN_PW = os.getenv("KITCHEN_PW", "kitchen123")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "mydatabase")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "password")

DB_URL = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

engine = create_engine(
    DB_URL,
    pool_size=10,
    max_overflow=5,
    pool_timeout=30,
    pool_recycle=1800,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db_session():
    if "db_session" not in g:
        g.db_session = SessionLocal()
    return g.db_session

@app.teardown_appcontext
def remove_session(exception=None):
    db_session = g.pop("db_session", None)
    if db_session is not None:
        db_session.close()

# ─────────────────────────────────────────────────────────
# DB 모델
# ─────────────────────────────────────────────────────────
class Menu(Base):
    __tablename__ = "menu"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    name     = Column(String(100), nullable=False)
    price    = Column(Integer, nullable=False)
    category = Column(String(50), nullable=False)
    stock    = Column(Integer, nullable=False, default=0)
    sold_out = Column(Boolean, default=False)

class Order(Base):
    __tablename__ = "orders"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    order_id      = Column(String(50), nullable=False)
    tableNumber   = Column(String(50), nullable=False)
    peopleCount   = Column(Integer, nullable=False)
    totalPrice    = Column(Integer, nullable=False)
    status        = Column(String(20), nullable=False)
    createdAt     = Column(Integer, nullable=False)
    confirmedAt   = Column(Integer)
    alertTime1    = Column(Integer, nullable=False, default=0)
    alertTime2    = Column(Integer, nullable=False, default=0)
    service       = Column(Boolean, nullable=False, default=False)

    items = relationship("OrderItem", back_populates="order")

class OrderItem(Base):
    __tablename__ = "order_items"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    order_id         = Column(Integer, ForeignKey("orders.id"), nullable=False)
    menu_id          = Column(Integer, ForeignKey("menu.id"), nullable=False)
    quantity         = Column(Integer, nullable=False)
    doneQuantity     = Column(Integer, nullable=False, default=0)
    deliveredQuantity= Column(Integer, nullable=False, default=0)

    order = relationship("Order", back_populates="items")
    menu  = relationship("Menu")

class Log(Base):
    __tablename__ = "logs"
    id     = Column(Integer, primary_key=True, autoincrement=True)
    time   = Column(Integer, nullable=False)
    role   = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
    detail = Column(String(200), nullable=False)

class Setting(Base):
    __tablename__ = "settings"
    id                    = Column(Integer, primary_key=True)
    main_required_enabled = Column(Boolean, default=True)
    main_anju_ratio       = Column(Integer, default=3)
    beer_limit_enabled    = Column(Boolean, default=True)
    beer_limit_count      = Column(Integer, default=1)
    time_warning1         = Column(Integer, default=50)
    time_warning2         = Column(Integer, default=60)

# ─────────────────────────────────────────────────────────
# DB 초기화 및 로그 함수
# ─────────────────────────────────────────────────────────
def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Menu).count() == 0:
            sample_menu = [
                Menu(name="메인안주A", price=12000, category="main", stock=10, sold_out=False),
                Menu(name="메인안주B", price=15000, category="main", stock=7,  sold_out=False),
                Menu(name="소주",     price=4000,  category="soju", stock=100, sold_out=False),
                Menu(name="맥주(1L)", price=8000,  category="beer", stock=50,  sold_out=False),
                Menu(name="콜라",     price=2000,  category="drink",stock=40,  sold_out=False),
                Menu(name="사이다",   price=2000,  category="drink",stock=40,  sold_out=False),
                Menu(name="생수",     price=1000,  category="drink",stock=50,  sold_out=False),
            ]
            db.add_all(sample_menu)
        s = db.query(Setting).filter_by(id=1).first()
        if not s:
            db.add(Setting(
                id=1,
                main_required_enabled=True,
                main_anju_ratio=3,
                beer_limit_enabled=True,
                beer_limit_count=1,
                time_warning1=50,
                time_warning2=60
            ))
        db.commit()
    finally:
        db.close()

def log_action(role, action, detail):
    db = get_db_session()
    now = int(time.time())
    db.add(Log(time=now, role=role, action=action, detail=detail))
    db.commit()

def get_settings():
    db = get_db_session()
    s = db.query(Setting).filter_by(id=1).first()
    if not s:
        s = Setting(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s

def update_settings(form_data):
    db = get_db_session()
    s = db.query(Setting).filter_by(id=1).first()
    if not s:
        s = Setting(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)
    s.main_required_enabled = (form_data.get("mainRequiredEnabled") == "1")
    s.beer_limit_enabled    = (form_data.get("beerLimitEnabled") == "1")
    s.main_anju_ratio        = int(form_data.get("mainAnjuRatio",  "3") or 3)
    s.beer_limit_count       = int(form_data.get("beerLimitCount", "1") or 1)
    s.time_warning1          = int(form_data.get("timeWarning1",   "50") or 50)
    s.time_warning2          = int(form_data.get("timeWarning2",   "60") or 60)
    db.commit()

# ─────────────────────────────────────────────────────────
# time_checker 쓰레드
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
            time.sleep(60)
            try:
                db = SessionLocal()
                s = db.query(Setting).filter_by(id=1).first()
                if not s:
                    db.close()
                    continue

                now_sec = int(time.time())
                paid_orders = db.query(Order).filter(Order.status=="paid", Order.confirmedAt!=None).all()
                for o in paid_orders:
                    diff_min = (now_sec - o.confirmedAt)//60
                    if o.alertTime1==0 and diff_min>=s.time_warning1:
                        o.alertTime1=1; db.add(o); db.commit()
                        db.add(Log(time=int(time.time()), role="system",
                                   action="TIME_WARNING1", detail=f"order_id={o.order_id}"))
                        db.commit()
                    if o.alertTime2==0 and diff_min>=s.time_warning2:
                        o.alertTime2=1; db.add(o); db.commit()
                        db.add(Log(time=int(time.time()), role="system",
                                   action="TIME_WARNING2", detail=f"order_id={o.order_id}"))
                        db.commit()
                db.close()
            except Exception as ex:
                print("[time_checker] 예외 발생:")
                traceback.print_exc()

# ─────────────────────────────────────────────────────────
# 에러 핸들러 (변경된 부분)
# ─────────────────────────────────────────────────────────
@app.errorhandler(SQLAlchemyError)
def handle_sqlalchemy_error(e):
    # 1) 콘솔(로그)에 전체 스택 트레이스 찍기
    print("=== SQLAlchemyError 발생 ===")
    traceback.print_exc()
    # 2) 사용자에게도 예외 메시지 노출 (디버깅용)
    flash(f"DB 오류: {str(e)}", "error")
    return redirect(url_for("index"))

# ─────────────────────────────────────────────────────────
# ... 이하 기존 로그인/주문/관리자/주방 라우트들 동일 ...
# (생략하지 않고 그대로 유지해야 합니다)
# ─────────────────────────────────────────────────────────
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
# 주문하기
# ─────────────────────────────────────────────────────────
@app.route("/order", methods=["GET","POST"])
def order():
    db = get_db_session()
    menu_list = db.query(Menu).all()
    settings  = get_settings()

    if request.method=="POST":
        table_number   = request.form.get("tableNumber","")
        is_first_order = (request.form.get("isFirstOrder")=="true")
        people_count   = int(request.form.get("peopleCount","0") or 0)
        notice_checked = (request.form.get("noticeChecked")=="on")

        ordered_items = []
        for m in menu_list:
            qty_str = request.form.get(f"qty_{m.id}", "0")
            qty = int(qty_str or 0)
            if qty>0:
                if m.sold_out:
                    flash(f"품절된 메뉴[{m.name}]는 주문 불가합니다.", "error")
                    return redirect(url_for("order"))
                ordered_items.append((m, qty))

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

            if settings.main_required_enabled:
                needed = people_count // settings.main_anju_ratio
                main_qty = sum(q for (menu_obj, q) in ordered_items if menu_obj.category=="main")
                if needed>0 and main_qty<needed:
                    flash(f"인원수 대비 메인안주가 부족합니다. (필요: {needed}개)", "error")
                    return redirect(url_for("order"))

            if settings.beer_limit_enabled:
                beer_count = sum(q for (menu_obj, q) in ordered_items if menu_obj.category=="beer")
                if beer_count > settings.beer_limit_count:
                    flash(f"최초 주문 시 맥주는 최대 {settings.beer_limit_count}병까지만 가능합니다.", "error")
                    return redirect(url_for("order"))
        else:
            if settings.beer_limit_enabled:
                for (menu_obj, q) in ordered_items:
                    if menu_obj.category=="beer" and q>0:
                        flash("추가 주문에서는 맥주를 주문할 수 없습니다.", "error")
                        return redirect(url_for("order"))

        new_order_id_str = str(int(time.time()))
        total_price = sum(m.price*q for (m,q) in ordered_items)
        now_sec = int(time.time())

        try:
            new_order = Order(
                order_id=new_order_id_str,
                tableNumber=table_number,
                peopleCount=people_count,
                totalPrice=total_price,
                status="pending",
                createdAt=now_sec,
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

    return render_template("order_form.html", menu_items=menu_list)

# ─────────────────────────────────────────────────────────
# 관리자 페이지
# ─────────────────────────────────────────────────────────
@app.route("/admin")
@login_required
def admin():
    db = get_db_session()

    # pending
    pending_orders_raw = db.query(Order).filter_by(status="pending").order_by(Order.id.desc()).all()
    pending_orders = []
    for o in pending_orders_raw:
        # items
        item_list = []
        for it in o.items:
            mname = it.menu.name if it.menu else "?"
            item_list.append({
                "menuName": mname,
                "quantity": it.quantity
            })
        pending_orders.append({
            "id": o.id,
            "order_id": o.order_id,
            "tableNumber": o.tableNumber,
            "peopleCount": o.peopleCount,
            "totalPrice": o.totalPrice,
            # "items" 키 그대로, 템플릿에선 o["items"] 로 접근
            "items": item_list
        })

    # paid
    paid_raw = db.query(Order).filter_by(status="paid").order_by(Order.id.desc()).all()
    paid_orders = []
    for o in paid_raw:
        it_list = []
        for it in o.items:
            mname = it.menu.name if it.menu else "?"
            it_list.append({
                "menuName": mname,
                "quantity": it.quantity,
                "doneQuantity": it.doneQuantity,
                "deliveredQuantity": it.deliveredQuantity
            })
        paid_orders.append({
            "id": o.id,
            "order_id": o.order_id,
            "tableNumber": o.tableNumber,
            "totalPrice": o.totalPrice,
            "items": it_list,
            "service": o.service
        })

    # completed
    comp_raw = db.query(Order).filter_by(status="completed").order_by(Order.id.desc()).all()
    completed_orders = []
    for o in comp_raw:
        completed_orders.append({
            "id": o.id,
            "order_id": o.order_id,
            "tableNumber": o.tableNumber,
            "totalPrice": o.totalPrice,
            "service": o.service
        })

    # 메뉴 목록
    menu_list = db.query(Menu).all()
    menu_items = []
    for m in menu_list:
        menu_items.append({
            "id": m.id,
            "name": m.name,
            "price": m.price,
            "category": m.category,
            "stock": m.stock,
            "soldOut": m.sold_out
        })

    # 매출
    sales_sum = db.query(
        text("SUM(totalPrice)")
    ).filter(text("service=0 AND (status='paid' OR status='completed')")).scalar()
    if not sales_sum:
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
    db = get_db_session()
    now_sec = int(time.time())
    try:
        o = db.query(Order).filter_by(id=order_id).with_for_update().first()
        if not o or o.status!="pending":
            flash("해당 주문은 'pending' 상태가 아닙니다.")
            return redirect(url_for("admin"))

        o.status = "paid"
        o.confirmedAt = now_sec
        db.add(o)
        db.flush()

        for it in o.items:
            menu_row = db.query(Menu).filter_by(id=it.menu_id).with_for_update().first()
            if not menu_row:
                flash("메뉴 정보가 없습니다.", "error")
                db.rollback()
                return redirect(url_for("admin"))

            menu_row.stock -= it.quantity
            if menu_row.stock<0:
                db.rollback()
                flash("재고 부족으로 인한 주문 확정 실패(동시 주문 문제).", "error")
                return redirect(url_for("admin"))

            if menu_row.category in ["soju","beer","drink"]:
                it.doneQuantity = it.quantity

            db.add(menu_row)
            db.add(it)

        db.commit()
        log_action(session["role"], "CONFIRM_ORDER", f"주문ID={order_id}")
        flash(f"주문 {order_id} 입금확인 완료!")
    except SQLAlchemyError:
        db.rollback()
        flash("입금 확인 중 오류가 발생했습니다.", "error")
    return redirect(url_for("admin"))

@app.route("/admin/complete/<int:order_id>", methods=["POST"])
@login_required
def admin_complete(order_id):
    db = get_db_session()
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

@app.route("/admin/deliver/<int:order_id>/<menu_name>", methods=["POST"])
@login_required
def admin_deliver_item(order_id, menu_name):
    db = get_db_session()
    try:
        o = db.query(Order).filter_by(id=order_id).with_for_update().first()
        if not o or o.status not in ["paid","completed"]:
            return redirect(url_for("admin"))

        deliver_item = None
        for it in o.items:
            if it.menu and it.menu.name==menu_name:
                deliver_item = it
                break
        if not deliver_item:
            db.rollback()
            flash("해당 메뉴가 주문에 없습니다.")
            return redirect(url_for("admin"))

        if deliver_item.deliveredQuantity < deliver_item.doneQuantity:
            deliver_item.deliveredQuantity += 1

        # 모두 전달완료?
        all_ok = True
        for it in o.items:
            if it.deliveredQuantity < it.quantity:
                all_ok=False
                break
        if all_ok:
            o.status="completed"

        db.commit()
        log_action(session["role"], "ADMIN_DELIVER_ITEM", f"{order_id}/{menu_name}")
        flash(f"주문 {order_id}, 메뉴 [{menu_name}] 1개 전달!")
    except:
        db.rollback()
        flash("전달 처리 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

@app.route("/admin/soldout/<int:menu_id>", methods=["POST"])
@login_required
def admin_soldout(menu_id):
    db = get_db_session()
    try:
        m = db.query(Menu).filter_by(id=menu_id).first()
        if not m:
            flash("해당 메뉴가 존재하지 않습니다.")
            return redirect(url_for("admin"))
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
    db = get_db_session()
    logs_raw = db.query(Log).order_by(Log.id.desc()).all()
    logs = []
    for lr in logs_raw:
        logs.append({
            "time": lr.time,
            "role": lr.role,
            "action": lr.action,
            "detail": lr.detail
        })
    return render_template("admin_log.html", logs=logs)

@app.route("/admin/service", methods=["POST"])
@login_required
def admin_service():
    db = get_db_session()
    service_table = request.form.get("serviceTable","")
    service_menu  = request.form.get("serviceMenu","")
    service_qty   = int(request.form.get("serviceQty","0") or 0)

    if not service_table or not service_menu or service_qty<1:
        flash("서비스 등록 실패: 테이블/메뉴/수량 확인 필요", "error")
        return redirect(url_for("admin"))

    mm = db.query(Menu).filter_by(name=service_menu).with_for_update().first()
    if not mm:
        flash("해당 메뉴를 찾을 수 없습니다.", "error")
        return redirect(url_for("admin"))
    if mm.sold_out:
        flash("해당 메뉴는 품절 처리된 상태입니다.", "error")
        return redirect(url_for("admin"))

    now_sec = int(time.time())
    order_id_str = str(now_sec)

    try:
        new_order = Order(
            order_id=order_id_str,
            tableNumber=service_table,
            peopleCount=0,
            totalPrice=0,
            status="paid",
            createdAt=now_sec,
            confirmedAt=now_sec,
            alertTime1=0,
            alertTime2=0,
            service=True
        )
        db.add(new_order)
        db.flush()

        new_item = OrderItem(
            order_id=new_order.id,
            menu_id=mm.id,
            quantity=service_qty,
            doneQuantity=0,
            deliveredQuantity=0
        )
        db.add(new_item)

        mm.stock -= service_qty
        if mm.stock<0:
            db.rollback()
            flash("재고 부족으로 서비스 등록 실패.", "error")
            return redirect(url_for("admin"))

        if mm.category in ["soju","beer","drink"]:
            new_item.doneQuantity = service_qty

        db.commit()
        log_action(session["role"], "ADMIN_SERVICE", f"주문ID={new_order.id} /메뉴:{service_menu}/{service_qty}")
        flash(f"0원 서비스 주문이 등록되었습니다. (주문 DB ID {new_order.id}, order_id={order_id_str})")
    except:
        db.rollback()
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
    db = get_db_session()
    paid_list = db.query(Order).filter_by(status="paid").order_by(Order.confirmedAt.asc()).all()

    paid_orders = []
    item_count  = {}
    for o in paid_list:
        it_list = []
        for it in o.items:
            m = it.menu
            mname = m.name if m else "?"
            done  = it.doneQuantity
            qty   = it.quantity
            delv  = it.deliveredQuantity
            it_list.append({
                "menuName": mname,
                "quantity": qty,
                "doneQuantity": done,
                "deliveredQuantity": delv
            })
            left = qty - done
            if left>0:
                item_count[mname] = item_count.get(mname, 0) + left

        paid_orders.append({
            "id": o.id,
            "order_id": o.order_id,
            "tableNumber": o.tableNumber,
            "items": it_list
        })

    return render_template("kitchen.html",
                           paid_orders=paid_orders,
                           kitchen_status=item_count)

@app.route("/kitchen/done-item/<int:order_id>/<menu_name>", methods=["POST"])
@login_required
def kitchen_done_item(order_id, menu_name):
    db = get_db_session()
    try:
        o = db.query(Order).filter_by(id=order_id).with_for_update().first()
        if not o or o.status!="paid":
            flash("해당 주문이 'paid' 상태가 아닙니다.", "error")
            db.rollback()
            return redirect(url_for("kitchen"))

        tgt_item = None
        for it in o.items:
            if it.menu and it.menu.name==menu_name:
                tgt_item = it
                break
        if not tgt_item:
            flash("해당 메뉴 항목이 없습니다.", "error")
            db.rollback()
            return redirect(url_for("kitchen"))

        if tgt_item.doneQuantity < tgt_item.quantity:
            tgt_item.doneQuantity += 1

        db.commit()
        log_action(session["role"], "KITCHEN_DONE_ITEM", f"{order_id}/{menu_name}")
    except:
        db.rollback()
        flash("조리 완료 처리 중 오류가 발생했습니다.", "error")

    return redirect(url_for("kitchen"))

# ─────────────────────────────────────────────────────────
# 앱 실행
# (Flask 3.1 → before_first_request 대신, 여기서 init_db/start_time_checker)
# ─────────────────────────────────────────────────────────
if __name__=="__main__":
    init_db()             # DB 테이블 생성 & 기본 데이터
    start_time_checker()  # 1분마다 50분/60분 알림
    port = int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
