from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)

# 🔐 Подключение к PostgreSQL через Render
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 🔧 Модель пользователя
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    rank = db.Column(db.String(100), nullable=False)
    phoneNumber = db.Column(db.String(20), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)  # Хешированный пароль
    time = db.Column(db.String(30), nullable=False)
    isPremium = db.Column(db.Boolean, default=False)

# ✅ Создание таблиц (только в отладочном режиме)
@app.route('/init_db')
def init_db():
    if not app.debug:
        return jsonify({'error': 'Forbidden'}), 403

    with app.app_context():
        db.drop_all()
        db.create_all()
    return '✅ База данных пересоздана'

# ✅ Регистрация пользователя
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()

    name = data.get('name')
    rank = data.get('rank')
    phone = data.get('phoneNumber')
    password = data.get('password')
    isPremium = data.get('isPremium', False)
    time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not name or not rank or not phone or not password:
        return jsonify({'error': 'Missing required fields'}), 400

    existing = User.query.filter_by(phoneNumber=phone).first()
    if existing:
        return jsonify({'error': 'User with this phone already exists'}), 409

    hashed_password = generate_password_hash(password)

    user = User(
        name=name,
        rank=rank,
        phoneNumber=phone,
        password=hashed_password,
        time=time,
        isPremium=isPremium
    )
    db.session.add(user)
    db.session.commit()

    print(f"[{time}] Зарегистрирован пользователь: {phone}")
    return jsonify({'status': 'ok'}), 201

# 🔐 Удалён открытый маршрут /users — небезопасно для продакшена

# ▶️ Запуск
if __name__ == '__main__':
    app.run(debug=True)
