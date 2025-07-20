from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash
from datetime import datetime
import os

app = Flask(__name__)

# 🔐 Подключение к PostgreSQL через Render
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 🔧 Обновлённая модель пользователя (без поля rank)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)  # Хешированный пароль
    time = db.Column(db.String(30), nullable=False)
    is_premium = db.Column(db.Boolean, default=False)

# ✅ Пересоздание таблиц (временно без ограничения debug)
@app.route('/init_db')
def init_db():
    with app.app_context():
        db.drop_all()
        db.create_all()
    return '✅ База данных пересоздана'

# ✅ Регистрация пользователя (без rank)
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()

    name = data.get('name')
    phone_number = data.get('phone_number')
    password = data.get('password')
    is_premium = data.get('is_premium', False)
    time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not name or not phone_number or not password:
        return jsonify({'error': 'Missing required fields'}), 400

    existing = User.query.filter_by(phone_number=phone_number).first()
    if existing:
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

    print(f"[{time}] Зарегистрирован пользователь: {phone_number}")
    return jsonify({'status': 'ok'}), 201

# 🔁 Сброс пароля по номеру телефона
@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json()
    phone_number = data.get('phone_number')
    new_password = data.get('new_password')

    if not phone_number or not new_password:
        return jsonify({'error': 'Missing phone number or new password'}), 400

    user = User.query.filter_by(phone_number=phone_number).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404

    user.password = generate_password_hash(new_password)
    db.session.commit()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Обновлён пароль для: {phone_number}")
    return jsonify({'status': 'Password updated successfully'}), 200

# ▶️ Запуск
if __name__ == '__main__':
    app.run(debug=True)
