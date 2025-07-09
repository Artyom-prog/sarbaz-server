from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
from pathlib import Path

app = Flask(__name__)

# 🔐 Подключение к PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 🔧 Модель пользователя
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    time = db.Column(db.String(30), nullable=False)

# 🛠 Создаём таблицы
with app.app_context():
    db.create_all()

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name')
    phone = data.get('phone')
    time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Сохраняем в БД
    user = User(name=name, phone=phone, time=time)
    db.session.add(user)
    db.session.commit()

    # 🔽 Сохраняем в txt на рабочем столе (если локально)
    try:
        desktop = Path.home() / "Desktop"
        log_file = desktop / "sarbaz_registrations.txt"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{time} | {name} | {phone}\n")
    except Exception as e:
        print("❗ Не удалось записать в файл:", e)

    print(f"[{time}] {name} - {phone}")
    return jsonify({'status': 'ok'}), 200

@app.route('/users', methods=['GET'])
def get_users():
    users = User.query.all()
    result = [{'name': u.name, 'phone': u.phone, 'time': u.time} for u in users]
    return jsonify(result)

if __name__ == '__main__':
    app.run()
