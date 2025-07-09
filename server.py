from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

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

# 🛠 Создаём таблицы (один раз при запуске)
with app.app_context():
    db.create_all()

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name')
    phone = data.get('phone')
    time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    user = User(name=name, phone=phone, time=time)
    db.session.add(user)
    db.session.commit()

    print(f"[{time}] {name} - {phone}")
    return jsonify({'status': 'ok'}), 200

@app.route('/users', methods=['GET'])
def get_users():
    users = User.query.all()
    result = [{'name': u.name, 'phone': u.phone, 'time': u.time} for u in users]
    return jsonify(result)

if __name__ == '__main__':
    app.run()
