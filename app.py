#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Alcohol-Is-Free  주문/관리 백엔드
(Flask + SQLAlchemy + MySQL)
"""

import os
import time
import threading
import traceback
import pytz
import datetime
import math

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

DB_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASS}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)

# ─────────────────────────────────────────────────────────
# 1) Flask & SQLAlchemy
# ─────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static")
app.secret_key = os.urandom(24)

engine = create_engine(
    DB_URL,
    pool_size=10, max_overflow=5,
    pool_timeout=30, pool_recycle=1800,
    echo=False
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# ─────────────────────────────────────────────────────────
# 2) 시간 유틸
# ─────────────────────────────────────────────────────────
def current_hhmmss() -> str:
    """한국시간 HHMMSS 문자열 반환"""
    now = datetime.datetime.now(pytz.timezone("Asia/Seoul"))
    return now.strftime("%H%M%S")

def hhmmss_to_minutes(hhmmss_str: str) -> int:
    """HHMMSS → 하루 기준 분 단위(0–1439)"""
    h, m, s = int(hhmmss_str[:2]), int(hhmmss_str[2:4]), int(hhmmss_str[4:6])
    return (h * 3600 + m * 60 + s) // 60

# ─────────────────────────────────────────────────────────
# 3) DB 모델
# ─────────────────────────────────────────────────────────
class Menu(Base):
    __tablename__ = "menu"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    name     = Column(String(100), nullable=False)
    price    = Column(Integer, nullable=False)
    category = Column(String(50), nullable=False)   # set, main, side, dessert, etc, drink
    stock    = Column(Integer, nullable=False, default=0)
    sold_out = Column(Boolean, default=False)

class Order(Base):
    __tablename__ = "orders"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    order_id    = Column(String(50), nullable=False)
    tableNumber = Column(String(50), nullable=False)
    peopleCount = Column(Integer, nullable=False)
    phoneNumber = Column(String(50))                       # TAKEOUT 전화번호
    totalPrice  = Column(Integer, nullable=False)
    status      = Column(String(20), nullable=False)       # pending, paid, completed, rejected
    createdAt   = Column(Integer, nullable=False)          # HHMMSS
    confirmedAt = Column(Integer)                          # HHMMSS
    alertTime1  = Column(Integer, default=0)
    alertTime2  = Column(Integer, default=0)
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
    id                = Column(Integer, primary_key=True)
    time_warning1     = Column(Integer, default=50)   # 분
    time_warning2     = Column(Integer, default=60)   # 분
    total_tables      = Column(Integer, default=23)
    min_items_per_two = Column(Integer, default=1)    # 2명당 최소 주문 항목
    require_main      = Column(Boolean, default=True) # Main Dish 필수 여부

class TableState(Base):
    __tablename__ = "table_state"
    tableNumber = Column(String(50), primary_key=True)  # 'TAKEOUT' or '1'~'23'
    usageStart  = Column(Integer)                       # HHMMSS
    blocked     = Column(Boolean, default=False)

# ─────────────────────────────────────────────────────────
# 4) 초기화
# ─────────────────────────────────────────────────────────
def init_db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.query(Menu).count() == 0:
            db.add_all([
                Menu(name="안톤이고's best pick", price=29000, category="set", stock=40),
                # Main
                Menu(name="목살 (Grilled Pork), 떡말이가 아닌 베이컨 구이로 제공", price=18000, category="main", stock=50),
                Menu(name="특급 볶음김치 (Grilled Kimchi)",        price=14000, category="main", stock=60),
                # Side
                Menu(name="베이컨 구이 (Grilled Bacon), 양 더 드림",       price=11000, category="side", stock=70),
                Menu(name="그랑 포와송 (Grand Poisson)", price=8000,  category="side", stock=70),
                # Dessert
                Menu(name="스모어 (Le S'more)",          price=6000,  category="dessert", stock=80),
                # Options
                Menu(name="빵 2pcs 추가 (baguette)",          price=1500, category="etc", stock=100),
                Menu(name="숙취해소제 2pcs (condition baton)", price=5000, category="etc", stock=100),
                # Drink
                Menu(name="사이다 (Cidre)",                price=2000, category="drink", stock=200),
                Menu(name="환타 포도 (Fanta au Raisin)",    price=2000, category="drink", stock=200),
                Menu(name="생수 (eau minérale)",            price=1000, category="drink", stock=200),
            ])
        if not db.query(Setting).filter_by(id=1).first():
            db.add(Setting(id=1, time_warning1=50, time_warning2=60,
                           total_tables=23, min_items_per_two=1, require_main=True))
        db.commit()

# ─────────────────────────────────────────────────────────
# 5) 헬퍼
# ─────────────────────────────────────────────────────────
def log_action(role, action, detail):
    with SessionLocal() as db:
        db.add(Log(time=int(current_hhmmss()), role=role,
                   action=action, detail=detail))
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
        s.time_warning1     = int(form.get("timeWarning1", 50) or 50)
        s.time_warning2     = int(form.get("timeWarning2", 60) or 60)
        s.total_tables      = int(form.get("totalTables", 23) or 23)
        s.min_items_per_two = int(form.get("minItemsPerTwo", 1) or 1)
        s.require_main      = (form.get("requireMain") == "on")
        db.commit()

# ─────────────────────────────────────────────────────────
# 6) 50/60분 경과 체크 쓰레드
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
                    s   = db.query(Setting).filter_by(id=1).first()
                    now = hhmmss_to_minutes(current_hhmmss())
                    for o in db.query(Order).filter(
                        Order.status=="paid", Order.confirmedAt!=None
                    ).all():
                        diff = now - hhmmss_to_minutes(f"{o.confirmedAt:06d}")
                        if o.alertTime1==0 and diff>=s.time_warning1:
                            o.alertTime1 = 1
                            db.add(Log(time=int(current_hhmmss()),
                                       role="system", action="TIME_WARNING1",
                                       detail=f"id={o.order_id}"))
                        if o.alertTime2==0 and diff>=s.time_warning2:
                            o.alertTime2 = 1
                            db.add(Log(time=int(current_hhmmss()),
                                       role="system", action="TIME_WARNING2",
                                       detail=f"id={o.order_id}"))
                    db.commit()
            except Exception:
                traceback.print_exc()

    threading.Thread(target=runner, daemon=True).start()

# ─────────────────────────────────────────────────────────
# 7) 에러핸들러
# ─────────────────────────────────────────────────────────
@app.errorhandler(SQLAlchemyError)
def handle_db_error(e):
    traceback.print_exc()
    flash(f"DB 오류: {e}", "error")
    return redirect(url_for("index"))

# ─────────────────────────────────────────────────────────
# 8) 인증
# ─────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        uid = request.form.get("userid")
        pw  = request.form.get("userpw")
        if uid==ADMIN_ID and pw==ADMIN_PW:
            session["role"] = "admin"
            flash("관리자 로그인되었습니다.")
            return redirect(url_for("admin"))
        if uid==KITCHEN_ID and pw==KITCHEN_PW:
            session["role"] = "kitchen"
            flash("주방 로그인되었습니다.")
            return redirect(url_for("kitchen"))
        flash("로그인 실패: 아이디/비밀번호를 확인하세요.")
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
# 9) 메인
# ─────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

# ─────────────────────────────────────────────────────────
# 10) 주문
# ─────────────────────────────────────────────────────────
@app.route("/order", methods=["GET", "POST"])
def order():
    with SessionLocal() as db:
        menu_list = db.query(Menu).all()
        settings  = db.query(Setting).filter_by(id=1).first()
        table_numbers = ["TAKEOUT"] + [str(i) for i in range(1, settings.total_tables+1)]

        if request.method == "POST":
            table_number   = request.form.get("tableNumber", "")
            is_first_order = (request.form.get("isFirstOrder") == "true")
            people_count   = int(request.form.get("peopleCount", 0) or 0)
            notice_checked = (request.form.get("noticeChecked") == "on")
            phone_number   = request.form.get("phoneNumber", "").strip()

            # 테이블 상태 객체
            ts = db.query(TableState).filter_by(tableNumber=table_number).first()
            if not ts:
                ts = TableState(tableNumber=table_number)
                db.add(ts)
                db.commit()
                db.refresh(ts)

            # 차단 확인
            if ts.blocked:
                flash("현재 차단된 테이블입니다. 주문 불가합니다.", "error")
                return redirect(url_for("order"))

            # 주문 항목 파싱
            ordered_items = []
            for m in menu_list:
                qty = int(request.form.get(f"qty_{m.id}", "0") or 0)
                if qty > 0:
                    if m.sold_out:
                        flash(f"품절된 메뉴[{m.name}]는 주문 불가합니다.", "error")
                        return redirect(url_for("order"))
                    ordered_items.append((m, qty))

            # 공통 검증
            if not table_number:
                flash("테이블 번호를 선택해주세요.", "error")
                return redirect(url_for("order"))
            if table_number == "TAKEOUT" and not phone_number:
                flash("TAKEOUT 주문 시 휴대전화번호 입력이 필요합니다.", "error")
                return redirect(url_for("order"))
            if not ordered_items:
                flash("한 개 이상의 메뉴를 선택해주세요.", "error")
                return redirect(url_for("order"))

            # 최초 주문 규칙
            if is_first_order:
                if not notice_checked:
                    flash("최초 주문 시 주의사항 확인이 필수입니다.", "error")
                    return redirect(url_for("order"))
                if people_count < 1:
                    flash("최초 주문 시 인원수는 1명 이상이어야 합니다.", "error")
                    return redirect(url_for("order"))

                needed = math.ceil(people_count / 2) * settings.min_items_per_two
                total_msd = 0   # main/side/dessert equivalent
                main_cnt  = 0

                for m, q in ordered_items:
                    if m.category in ["main", "side", "dessert"]:
                        total_msd += q
                        if m.category == "main":
                            main_cnt += q
                    elif m.category == "set":
                        total_msd += 2 * q   # 세트 1 → main 1 + side 1
                        main_cnt  += q       # 세트 1 → main 1

                if total_msd < needed:
                    flash(f"인원수 대비 (Main/Side/Dessert) 메뉴가 부족합니다. (필요: {needed}개 이상)", "error")
                    return redirect(url_for("order"))
                if settings.require_main and main_cnt < 1:
                    flash("최초 주문에는 Main Dish가 최소 1개 이상 포함되어야 합니다.", "error")
                    return redirect(url_for("order"))

            # 주문 DB 반영
            now_hhmmss = current_hhmmss()
            total_price = sum(m.price * q for m, q in ordered_items)

            try:
                new_order = Order(
                    order_id=now_hhmmss,
                    tableNumber=table_number,
                    peopleCount=people_count,
                    phoneNumber=phone_number,
                    totalPrice=total_price,
                    status="pending",
                    createdAt=int(now_hhmmss)
                )
                db.add(new_order)
                db.flush()

                for m, q in ordered_items:
                    db.add(OrderItem(order_id=new_order.id, menu_id=m.id, quantity=q))

                db.commit()
                flash(f"주문이 접수되었습니다 (주문번호: {now_hhmmss}).")
                return render_template("order_result.html",
                                       total_price=total_price,
                                       order_id=now_hhmmss)
            except:
                db.rollback()
                flash("주문 처리 중 오류가 발생했습니다.", "error")
                return redirect(url_for("order"))

        return render_template(
            "order_form.html",
            menu_items=menu_list,
            table_numbers=table_numbers,
            settings=settings
        )

# ─────────────────────────────────────────────────────────
# 11) 관리자 페이지
# ─────────────────────────────────────────────────────────
@app.route("/admin")
@login_required
def admin():
    sort_mode = request.args.get("sort", "asc")
    if sort_mode not in ["asc", "desc"]:
        sort_mode = "asc"

    with SessionLocal() as db:
        s = db.query(Setting).filter_by(id=1).first()
        total_tables = s.total_tables
        table_list = ["TAKEOUT"] + [str(i) for i in range(1, total_tables + 1)]

        now_min = hhmmss_to_minutes(current_hhmmss())

        # 테이블 현황
        table_status_info = []
        for t in table_list:
            ts = db.query(TableState).filter_by(tableNumber=t).first()
            if ts:
                blocked = ts.blocked
                if ts.usageStart is not None:
                    diff = now_min - hhmmss_to_minutes(f"{ts.usageStart:06d}")
                    color = "red" if diff >= s.time_warning2 else (
                            "yellow" if diff >= s.time_warning1 else "normal")
                    table_status_info.append((t, f"{diff}분", color, blocked, False))
                else:
                    table_status_info.append((t, "-", "empty", blocked, True))
            else:
                table_status_info.append((t, "-", "empty", False, True))

        order_by_clause = Order.id.asc() if sort_mode == "asc" else Order.id.desc()

        # pending
        pending_orders = []
        for o in db.query(Order).filter_by(status="pending").order_by(order_by_clause):
            items = [{"menuName": it.menu.name, "quantity": it.quantity} for it in o.items]
            first_flag = (o.peopleCount > 0)
            recent_first = db.query(Order).filter(
                Order.tableNumber == o.tableNumber,
                Order.peopleCount > 0
            ).order_by(Order.id.desc()).first()
            pending_orders.append({
                "id": o.id, "order_id": o.order_id,
                "tableNumber": o.tableNumber,
                "peopleCount": o.peopleCount,
                "phoneNumber": o.phoneNumber,
                "totalPrice": o.totalPrice,
                "items": items,
                "is_first": first_flag,
                "recent_first_time": recent_first.order_id if recent_first else "",
                "stock_negative_warning": any(it.menu.stock < 0 for it in o.items),
                "createdAt": o.createdAt
            })

        # paid
        paid_orders = []
        for o in db.query(Order).filter_by(status="paid").order_by(order_by_clause):
            items = [{
                "menuName": it.menu.name,
                "quantity": it.quantity,
                "doneQuantity": it.doneQuantity,
                "deliveredQuantity": it.deliveredQuantity
            } for it in o.items]
            paid_orders.append({
                "id": o.id, "order_id": o.order_id,
                "tableNumber": o.tableNumber,
                "totalPrice": o.totalPrice,
                "items": items,
                "service": o.service,
                "phoneNumber": o.phoneNumber,
                "createdAt": o.createdAt
            })

        # completed
        completed_orders = []
        for o in db.query(Order).filter_by(status="completed").order_by(order_by_clause):
            completed_orders.append({
                "id": o.id, "order_id": o.order_id,
                "tableNumber": o.tableNumber,
                "totalPrice": o.totalPrice,
                "service": o.service,
                "phoneNumber": o.phoneNumber,
                "createdAt": o.createdAt
            })

        # rejected
        rejected_orders = []
        for o in db.query(Order).filter_by(status="rejected").order_by(order_by_clause):
            rejected_orders.append({
                "id": o.id, "order_id": o.order_id,
                "tableNumber": o.tableNumber,
                "phoneNumber": o.phoneNumber,
                "createdAt": o.createdAt
            })

        # 메뉴
        menu_items = [{
            "id": m.id, "name": m.name,
            "price": m.price, "category": m.category,
            "stock": m.stock, "soldOut": m.sold_out
        } for m in db.query(Menu).all()]

        sales_sum = db.query(
            func.coalesce(func.sum(Order.totalPrice), 0)
        ).filter(
            Order.service == False,
            or_(Order.status == "paid", Order.status == "completed")
        ).scalar()

    return render_template(
        "admin.html",
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

# ─────────────────────────────────────────────────────────
# 11-1) 테이블 empty / block 토글
# ─────────────────────────────────────────────────────────
@app.route("/admin/empty_table/<table_num>", methods=["POST"])
@login_required
def admin_empty_table(table_num):
    with SessionLocal() as db:
        ts = db.query(TableState).filter_by(tableNumber=table_num).first()
        if ts:
            ts.usageStart = None
        db.commit()
    log_action(session["role"], "EMPTY_TABLE", f"table={table_num}")
    flash(f"{table_num}번 테이블이(가) 비워졌습니다.")
    return redirect(url_for("admin"))

@app.route("/admin/block_table/<table_num>", methods=["POST"])
@login_required
def admin_block_table(table_num):
    with SessionLocal() as db:
        ts = db.query(TableState).filter_by(tableNumber=table_num).first()
        if not ts:
            ts = TableState(tableNumber=table_num)
            db.add(ts)
            db.commit()
            db.refresh(ts)
        ts.blocked = not ts.blocked
        db.commit()
    log_action(session["role"], "BLOCK_TOGGLE", f"table={table_num} blocked={ts.blocked}")
    flash(f"{table_num}번 테이블 차단 상태가 변경되었습니다.")
    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 11-2) pending → paid  (세트 메뉴 재고 연쇄 차감)
# ─────────────────────────────────────────────────────────
@app.route("/admin/confirm/<int:order_id>", methods=["POST"])
@login_required
def admin_confirm(order_id):
    with SessionLocal() as db:
        try:
            o = db.query(Order).filter_by(id=order_id).with_for_update().first()
            if not o or o.status != "pending":
                flash("해당 주문은 'pending' 상태가 아닙니다.")
                return redirect(url_for("admin"))

            # 상태 변경
            o.status      = "paid"
            o.confirmedAt = int(current_hhmmss())

            # 테이블 사용 시작
            if o.peopleCount > 0:
                ts = db.query(TableState).filter_by(tableNumber=o.tableNumber).first()
                if ts and ts.usageStart is None:
                    ts.usageStart = o.confirmedAt

            # 세트메뉴 연쇄 차감용 메뉴 객체
            pork  = db.query(Menu).filter_by(name="포크 앙 투움바 (Pork en Toowoomba)").with_for_update().first()
            roule = db.query(Menu).filter_by(name="떡 롤레 (Tteok Roulé)").with_for_update().first()

            # 재고 차감
            for it in o.items:
                m = db.query(Menu).filter_by(id=it.menu_id).with_for_update().first()
                m.stock -= it.quantity
                # set 메뉴면 각 구성 품목도 차감
                if m.category == "set":
                    pork.stock  -= it.quantity
                    roule.stock -= it.quantity

            db.commit()
            log_action(session["role"], "CONFIRM_ORDER", f"주문ID={order_id}")
            flash(f"주문 {order_id} 입금확인 완료!")
        except:
            db.rollback()
            traceback.print_exc()
            flash("입금 확인 중 오류가 발생했습니다.", "error")

    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 11-3) 주문 거절
# ─────────────────────────────────────────────────────────
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
        except:
            db.rollback()
            traceback.print_exc()
            flash("주문 거절 처리 중 오류가 발생했습니다.", "error")
    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 11-4) paid → completed
# ─────────────────────────────────────────────────────────
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
        except:
            db.rollback()
            traceback.print_exc()
            flash("주문 완료 처리 중 오류가 발생했습니다.", "error")
    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 11-5) 전달 수량 처리
# ─────────────────────────────────────────────────────────
@app.route("/admin/deliver_item_count/<int:order_id>/<menu_name>", methods=["POST"])
@login_required
def admin_deliver_item_count(order_id, menu_name):
    try:
        count = int(request.form.get("deliver_count", "0"))
    except ValueError:
        count = 0
    if count < 1:
        flash("잘못된 전달 수량입니다.", "error")
        return redirect(url_for("admin"))

    with SessionLocal() as db:
        try:
            o  = db.query(Order).filter_by(id=order_id).with_for_update().first()
            if not o or o.status not in ["paid", "completed"]:
                flash("해당 주문 상태가 조리중이 아닙니다.", "error")
                return redirect(url_for("admin"))

            it = next((i for i in o.items if i.menu.name == menu_name), None)
            if not it:
                flash("해당 메뉴가 주문에 없습니다.", "error")
                return redirect(url_for("admin"))

            left = it.doneQuantity - it.deliveredQuantity
            if left < count:
                flash("전달 수량 초과입니다.", "error")
                return redirect(url_for("admin"))

            it.deliveredQuantity += count

            # 전체 전달 완료 검사
            all_delivered = all(x.deliveredQuantity >= x.quantity for x in o.items)
            if all_delivered:
                o.status = "completed"

            db.commit()
            log_action(session["role"], "DELIVER_ITEM",
                       f"{o.order_id}/{menu_name}/{count}")
            flash(f"[{menu_name}] {count}개 전달 완료!")
        except:
            db.rollback()
            traceback.print_exc()
            flash("전달 처리 중 오류가 발생했습니다.", "error")
    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 11-6) 품절 토글
# ─────────────────────────────────────────────────────────
@app.route("/admin/soldout/<int:menu_id>", methods=["POST"])
@login_required
def admin_soldout(menu_id):
    with SessionLocal() as db:
        try:
            m = db.query(Menu).filter_by(id=menu_id).first()
            m.sold_out = not m.sold_out
            db.commit()
            log_action(session["role"], "SOLDOUT_TOGGLE", f"{m.name}={m.sold_out}")
            flash(f"메뉴 [{m.name}] 품절상태 변경!")
        except:
            db.rollback()
            traceback.print_exc()
            flash("품절상태 변경 중 오류가 발생했습니다.", "error")
    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 11-7) 재고 수정
# ─────────────────────────────────────────────────────────
@app.route("/admin/update_stock/<int:menu_id>", methods=["POST"])
@login_required
def admin_update_stock(menu_id):
    try:
        new_stock = int(request.form.get("new_stock", "0"))
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
                       f"{m.name}: {old_stock}→{new_stock}")
            flash(f"[{m.name}] 재고가 {new_stock} 으로 수정되었습니다.")
        except:
            db.rollback()
            traceback.print_exc()
            flash("재고 수정 중 오류가 발생했습니다.", "error")
    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 11-8) 옵션/제약 설정 저장
# ─────────────────────────────────────────────────────────
@app.route("/admin/update-settings", methods=["POST"])
@login_required
def admin_update_settings():
    update_settings(request.form)
    log_action(session["role"], "UPDATE_SETTINGS", "옵션 수정")
    flash("설정이 업데이트되었습니다.")
    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 11-9) 0원 서비스 등록
# ─────────────────────────────────────────────────────────
@app.route("/admin/service", methods=["POST"])
@login_required
def admin_service():
    table      = request.form.get("serviceTable", "")
    menu_name  = request.form.get("serviceMenu", "")
    qty        = int(request.form.get("serviceQty", "0") or 0)

    if not table or not menu_name or qty < 1:
        flash("서비스 등록 실패: 테이블/메뉴/수량 확인 필요", "error")
        return redirect(url_for("admin"))

    with SessionLocal() as db:
        ts = db.query(TableState).filter_by(tableNumber=table).first()
        if not ts:
            ts = TableState(tableNumber=table)
            db.add(ts)
            db.commit()
            db.refresh(ts)

        if ts.blocked:
            flash("차단된 테이블에는 서비스를 등록할 수 없습니다.", "error")
            return redirect(url_for("admin"))

        m = db.query(Menu).filter_by(name=menu_name).with_for_update().first()
        if not m or m.sold_out:
            flash("해당 메뉴가 없거나 품절입니다.", "error")
            return redirect(url_for("admin"))

        now_str = current_hhmmss()
        try:
            new_order = Order(
                order_id=now_str,
                tableNumber=table,
                peopleCount=0,
                phoneNumber="",
                totalPrice=0,
                status="paid",
                createdAt=int(now_str),
                confirmedAt=int(now_str),
                service=True
            )
            db.add(new_order)
            db.flush()
            db.add(OrderItem(order_id=new_order.id, menu_id=m.id,
                             quantity=qty))
            m.stock -= qty
            db.commit()
            log_action(session["role"], "ADMIN_SERVICE",
                       f"{table}/{menu_name}/{qty}")
            flash("0원 서비스 주문이 등록되었습니다.")
        except:
            db.rollback()
            traceback.print_exc()
            flash("서비스 등록 중 오류가 발생했습니다.", "error")
    return redirect(url_for("admin"))

# ─────────────────────────────────────────────────────────
# 11-10) 로그 페이지
# ─────────────────────────────────────────────────────────
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

    return render_template("admin_log.html",
                           logs=logs,
                           role_filter=role_filter,
                           action_filter=action_filter,
                           detail_filter=detail_filter,
                           time_start=time_start,
                           time_end=time_end)

# ─────────────────────────────────────────────────────────
# 12) 주방 페이지
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
    try:
        count = int(request.form.get("done_count", "0"))
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
                    if it.menu.name == menu_name and remaining > 0:
                        todo = it.quantity - it.doneQuantity
                        if todo > 0:
                            delta = min(todo, remaining)
                            it.doneQuantity += delta
                            remaining -= delta
                if remaining <= 0:
                    break
            db.commit()
            log_action(session["role"], "KITCHEN_DONE_ITEM", f"{menu_name}/{count}")
            flash(f"[{menu_name}] {count}개 조리 완료 처리.")
        except:
            db.rollback()
            traceback.print_exc()
            flash("조리 완료 처리 중 오류가 발생했습니다.", "error")
    return redirect(url_for("kitchen"))

# ─────────────────────────────────────────────────────────
# 13) 실행
# ─────────────────────────────────────────────────────────
init_db()
start_time_checker()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
