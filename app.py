import os
from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change_this_secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///restaurant.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Models -------------------------------------

class User(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    role     = db.Column(db.String(16), nullable=False)  # 'admin' or 'kitchen'

class Order(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    table_number = db.Column(db.String(16), nullable=False)
    total_price  = db.Column(db.Integer, nullable=False)
    status       = db.Column(db.String(16), nullable=False, default='pending')
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    items        = db.relationship('OrderItem', backref='order', lazy=True)

class OrderItem(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    order_id  = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    menu_name = db.Column(db.String(64), nullable=False)
    quantity  = db.Column(db.Integer, default=1)
    status    = db.Column(db.String(16), nullable=False, default='pending')  
               # 'pending', 'cooked', 'served'

# --- 로그인 체크 ----------------------------------

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapper

# --- 라우팅 ---------------------------------------

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    error = None
    if request.method == 'POST':
        user = User.query.filter_by(
            username=request.form['username'],
            password=request.form['password']
        ).first()
        if user:
            session['user_id'] = user.id
            session['role']    = user.role
            return redirect(url_for('admin'))
        else:
            error = '아이디 또는 비밀번호가 잘못되었습니다.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/order', methods=['GET','POST'])
@login_required
def order():
    # (간략) 고객 주문 페이지
    if request.method == 'POST':
        table = request.form.get('table')
        items = []
        total = 0
        # form으로 받은 메뉴명·가격 리스트 순회
        for name, price_str in zip(request.form.getlist('menu_name'),
                                    request.form.getlist('price')):
            price = int(price_str)
            qty   = int(request.form.get(f'quantity_{name}', 1))
            if qty > 0:
                total += price * qty
                items.append({'menu_name': name, 'quantity': qty})
        if items:
            o = Order(table_number=table, total_price=total)
            db.session.add(o); db.session.flush()
            for it in items:
                db.session.add(OrderItem(
                    order_id=o.id,
                    menu_name=it['menu_name'],
                    quantity=it['quantity']
                ))
            db.session.commit()
            return render_template('order_success.html', order=o)

    menus = [
        {'name':'아메리카노','price':4000},
        {'name':'카페라떼','price':4500},
        # … 필요에 따라 추가
    ]
    return render_template('order_form.html', menus=menus)

@app.route('/admin')
@login_required
def admin():
    pending    = Order.query.filter_by(status='pending').all()
    confirmed  = Order.query.filter_by(status='confirmed').all()
    preparing  = Order.query.filter_by(status='preparing').all()
    served     = Order.query.filter_by(status='served').all()
    return render_template('admin.html',
        pending_orders= pending,
        confirmed_orders=confirmed,
        preparing_orders=preparing,
        served_orders=   served
    )

@app.route('/admin_confirm/<int:order_id>', methods=['POST'])
@login_required
def admin_confirm(order_id):
    o = Order.query.get_or_404(order_id)
    o.status = 'confirmed'
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin_ready/<int:order_id>', methods=['POST'])
@login_required
def admin_ready(order_id):
    o = Order.query.get_or_404(order_id)
    o.status = 'preparing'
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin_serve_item/<int:item_id>')
@login_required
def admin_serve_item(item_id):
    it = OrderItem.query.get_or_404(item_id)
    it.status = 'served'
    # 주문 전체 상태 업데이트
    parent = it.order
    if all(x.status=='served' for x in parent.items):
        parent.status = 'served'
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin_log')
@login_required
def admin_log():
    # 로그 화면 구현 영역
    return render_template('admin_log.html')

@app.route('/kitchen')
@login_required
def kitchen():
    # confirmed 또는 preparing 상태의 주문만 조회
    orders = Order.query.filter(Order.status.in_(['confirmed','preparing'])).all()
    return render_template('kitchen.html', orders=orders)

@app.route('/kitchen_done/<int:item_id>')
@login_required
def kitchen_done(item_id):
    it = OrderItem.query.get_or_404(item_id)
    it.status = 'cooked'
    parent = it.order
    if parent.status == 'confirmed':
        parent.status = 'preparing'
    db.session.commit()
    return redirect(url_for('kitchen'))

if __name__ == '__main__':
    db.create_all()
    app.run(debug=True, host='0.0.0.0')
