from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
from pathlib import Path

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
    password = db.Column(db.String(100), nullable=False)
    time = db.Column(db.String(30), nullable=False)

# ✅ Ручной маршрут для создания таблиц в Render
@app.route('/init_db')
def init_db():
    with app.app_context():
        db.drop_all()  # ❗ Удаляет старую таблицу — используй только во время разработки
        db.create_all()
    return '✅ Таблицы успешно созданы'

# ✅ Регистрация пользователя
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()

    name = data.get('name')
    rank = data.get('rank')
    phone = data.get('phoneNumber')
    password = data.get('password')
    time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Проверка обязательных полей
    if not name or not rank or not phone or not password:
        return jsonify({'error': 'Missing required fields'}), 400

    # Проверка: существует ли уже такой пользователь
    existing = User.query.filter_by(phoneNumber=phone).first()
    if existing:
        return jsonify({'error': 'User with this phone already exists'}), 409

    # Сохраняем нового пользователя
    user = User(name=name, rank=rank, phoneNumber=phone, password=password, time=time)
    db.session.add(user)
    db.session.commit()

    # ⬇️ Пишем в файл на рабочем столе (если возможно)
    try:
        desktop = Path.home() / "Desktop"
        log_file = desktop / "sarbaz_registrations.txt"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{time} | {name} | {rank} | {phone}\n")
    except Exception as e:
        print("❗ Не удалось записать в файл:", e)

    print(f"[{time}] Зарегистрирован: {name} | {rank} | {phone}")
    return jsonify({'status': 'ok'}), 201

# 📄 Получение списка пользователей (для отладки)
@app.route('/users', methods=['GET'])
def get_users():
    users = User.query.all()
    result = [
        {
            'name': u.name,
            'rank': u.rank,
            'phone': u.phoneNumber,
            'time': u.time
        } for u in users
    ]
    return jsonify(result)

# ▶️ Запуск (если локально)
if __name__ == '__main__':
    app.run()
