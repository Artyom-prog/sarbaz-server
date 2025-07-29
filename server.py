from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import jwt

app = Flask(__name__)

# Конфигурация
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'supersecretkey')

db = SQLAlchemy(app)

# Модель пользователя
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    time = db.Column(db.String(30), nullable=False)
    is_premium = db.Column(db.Boolean, default=False)

# Нормализация телефона
def normalize_phone(phone):
    digits = ''.join(filter(str.isdigit, phone))
    if digits.startswith('8'):
        digits = '7' + digits[1:]
    elif not digits.startswith('7'):
        digits = '7' + digits
    return f'+{digits}'

# Эндпоинт для сброса пароля
@app.route('/api/reset_password', methods=['POST'])
def reset_password():
    data = request.get_json()
    phone_number = normalize_phone(data.get('phone_number', '').strip())
    new_password = data.get('new_password', '').strip()

    if not phone_number or not new_password:
        return jsonify({'error': 'Missing phone number or new password'}), 400

    if len(new_password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    user = User.query.filter_by(phone_number=phone_number).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404

    user.password = generate_password_hash(new_password)
    db.session.commit()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Обновлён пароль для: {phone_number}")
    return jsonify({'status': 'Password updated successfully'}), 200

# Эндпоинт для регистрации
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name', '').strip()
    phone_number = normalize_phone(data.get('phone_number', '').strip())
    password = data.get('password', '').strip()
    is_premium = data.get('is_premium', False)

    if not name or not phone_number or not password:
        return jsonify({'error': 'Missing required fields'}), 400

    if User.query.filter_by(phone_number=phone_number).first():
        return jsonify({'error': 'Phone number already exists'}), 409

    user = User(
        name=name,
        phone_number=phone_number,
        password=generate_password_hash(password),
        time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        is_premium=is_premium
    )
    db.session.add(user)
    db.session.commit()

    token = jwt.encode(
        {'phone_number': phone_number, 'exp': datetime.utcnow() + timedelta(hours=24)},
        app.config['SECRET_KEY'],
        algorithm='HS256'
    )

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Зарегистрирован: {phone_number}")
    return jsonify({'token': token, 'user': {'name': name, 'phone_number': phone_number, 'is_premium': is_premium}}), 201

# Эндпоинт для входа
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    phone_number = normalize_phone(data.get('phone_number', '').strip())
    password = data.get('password', '').strip()

    if not phone_number or not password:
        return jsonify({'error': 'Missing phone number or password'}), 400

    user = User.query.filter_by(phone_number=phone_number).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({'error': 'Invalid credentials'}), 401

    token = jwt.encode(
        {'phone_number': phone_number, 'exp': datetime.utcnow() + timedelta(hours=24)},
        app.config['SECRET_KEY'],
        algorithm='HS256'
    )

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Вход выполнен: {phone_number}")
    return jsonify({'token': token, 'user': {'name': user.name, 'phone_number': phone_number, 'is_premium': user.is_premium}}), 200

# Эндпоинт для проверки сервера
@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({'status': 'Server is running'}), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
