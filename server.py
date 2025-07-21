from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import jwt

app = Flask(__name__)

# 🔐 Конфигурация
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'supersecretkey')  # можно вынести в Render env

db = SQLAlchemy(app)

# 🔧 Модель пользователя
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    time = db.Column(db.String(30), nullable=False)
    is_premium = db.Column(db.Boolean, default=False)

# ✅ JWT генерация токена
def generate_token(user):
    payload = {
        'user_id': user.id,
        'phone_number': user.phone_number,
        'exp': datetime.utcnow() + timedelta(days=30)
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')

# ✅ Регистрация пользователя
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()

    name = data.get('name', '').strip()
    phone_number = data.get('phone_number', '').strip()
    password = data.get('password', '').strip()
    is_premium = data.get('is_premium', False)
    time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not name or not phone_number or not password:
        return jsonify({'error': 'Missing required fields'}), 400

    if User.query.filter_by(phone_number=phone_number).first():
        return jsonify({'error': 'User with this phone number already exists'}), 409

    hashed_password = generate_password_hash(password)

    user = User(
        name=name,
        phone_number=phone_number,
        password=hashed_password,
        time=time,
        is_premium=is_premium
    )
    db.session.add(user)
    db.session.commit()

    token = generate_token(user)

    print(f"[{time}] Зарегистрирован пользователь: {phone_number}")
    return jsonify({'status': 'ok', 'token': token, 'user': {
        'id': user.id,
        'name': user.name,
        'phoneNumber': user.phone_number,
        'isPremium': user.is_premium,
        'time': user.time
    }}), 201

# ✅ Вход пользователя
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    phone_number = data.get('phone_number', '').strip()
    password = data.get('password', '').strip()

    if not phone_number or not password:
        return jsonify({'error': 'Missing phone number or password'}), 400

    user = User.query.filter_by(phone_number=phone_number).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({'error': 'Invalid credentials'}), 401

    token = generate_token(user)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Успешный вход: {phone_number}")
    return jsonify({'status': 'ok', 'token': token, 'user': {
        'id': user.id,
        'name': user.name,
        'phoneNumber': user.phone_number,
        'isPremium': user.is_premium,
        'time': user.time
    }}), 200

# 🔁 Сброс пароля
@app.route('/api/reset_password', methods=['POST'])
def reset_password():
    data = request.get_json()
    phone_number = data.get('phone_number', '').strip()
    new_password = data.get('new_password', '').strip()

    if not phone_number or not new_password:
        return jsonify({'error': 'Missing phone number or new password'}), 400

    user = User.query.filter_by(phone_number=phone_number).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404

    user.password = generate_password_hash(new_password)
    db.session.commit()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Обновлён пароль для: {phone_number}")
    return jsonify({'status': 'Password updated successfully'}), 200

# ▶️ Тестовый эндпоинт (опционально)
@app.route('/api/ping')
def ping():
    return jsonify({'status': 'pong'}), 200

# ▶️ Запуск
if __name__ == '__main__':
    app.run(debug=True)
