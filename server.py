from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import json
import jwt
import logging
import firebase_admin
from firebase_admin import credentials, auth

app = Flask(__name__)

# -----------------------------
# 🔧 Логирование
# -----------------------------
# На Render запись в файл может быть недоступна/эфемерна — оставим и StreamHandler, и FileHandler.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# -----------------------------
# 🔧 Конфигурация приложения
# -----------------------------
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///users.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(32).hex())

# Путь к конфигу версий для /api/app-version
CONFIG_PATH = os.environ.get("CONFIG_PATH", "config/config.json")

# -----------------------------
# 🔥 Firebase инициализация
# -----------------------------
service_account = os.environ.get('FIREBASE_SERVICE_ACCOUNT')
if not service_account:
    logger.error("FIREBASE_SERVICE_ACCOUNT не найдена")
    raise ValueError("FIREBASE_SERVICE_ACCOUNT не настроена")

try:
    service_account_dict = json.loads(service_account)
    # ключ из ENV часто приходит с \n — нормализуем
    service_account_dict["private_key"] = service_account_dict["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(service_account_dict)
    firebase_admin.initialize_app(cred)
except Exception as e:
    logger.error(f"Ошибка инициализации Firebase: {e}")
    raise

# -----------------------------
# 📦 База данных
# -----------------------------
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    time = db.Column(db.String(30), nullable=False)
    is_premium = db.Column(db.Boolean, default=False)

# -----------------------------
# 🔧 Утилиты
# -----------------------------
def normalize_phone(phone: str) -> str:
    digits = ''.join(filter(str.isdigit, phone or ""))
    if not digits:
        return '+7'
    if digits.startswith('8'):
        digits = '7' + digits[1:]
    elif not digits.startswith('7'):
        digits = '7' + digits
    return f'+{digits}'

def verify_jwt_token(token: str):
    try:
        data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return data['phone_number']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

# -----------------------------
# 🔐 Эндпоинты аутентификации
# -----------------------------
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(force=True, silent=True) or {}
    phone_number = normalize_phone(data.get('phone_number', '').strip())
    password = (data.get('password') or '').strip()

    user = User.query.filter_by(phone_number=phone_number).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

    token = jwt.encode(
        {'phone_number': phone_number, 'exp': datetime.utcnow() + timedelta(hours=24)},
        app.config['SECRET_KEY'],
        algorithm='HS256'
    )

    logger.info(f'Вход выполнен: {phone_number}')
    return jsonify({
        'success': True,
        'token': token,
        'user': {'name': user.name, 'phone_number': phone_number, 'is_premium': user.is_premium}
    }), 200

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or '').strip()
    phone_number = normalize_phone((data.get('phone_number') or '').strip())
    password = (data.get('password') or '').strip()
    is_premium = bool(data.get('is_premium', False))

    if not name or not password:
        return jsonify({'success': False, 'error': 'Name and password are required'}), 400

    if User.query.filter_by(phone_number=phone_number).first():
        return jsonify({'success': False, 'error': 'Phone number already exists'}), 409

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

    logger.info(f'Зарегистрирован: {phone_number}')
    return jsonify({
        'success': True,
        'token': token,
        'user': {'name': name, 'phone_number': phone_number, 'is_premium': is_premium}
    }), 201

@app.route('/api/verify', methods=['POST'])
def verify():
    data = request.get_json(force=True, silent=True) or {}
    token = data.get('token')
    phone = data.get('phone')

    real_phone = verify_jwt_token(token or '')
    if real_phone == phone:
        logger.info(f'✅ Верификация успешна: {phone}')
        return jsonify({'success': True}), 200
    else:
        logger.warning(f'❌ Верификация не удалась: {phone}')
        return jsonify({'success': False, 'error': 'Invalid or expired token'}), 401

@app.route('/api/restore', methods=['POST'])
def restore():
    data = request.get_json(force=True, silent=True) or {}
    phone = normalize_phone(data.get('phone'))
    user = User.query.filter_by(phone_number=phone).first()

    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    token = jwt.encode(
        {'phone_number': phone, 'exp': datetime.utcnow() + timedelta(hours=24)},
        app.config['SECRET_KEY'],
        algorithm='HS256'
    )

    logger.info(f'🔁 Восстановление токена: {phone}')
    return jsonify({
        'success': True,
        'token': token,
        'user': {'name': user.name, 'phone_number': phone, 'is_premium': user.is_premium}
    }), 200

@app.route('/api/reset_password', methods=['POST'])
def reset_password():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'success': False, 'error': 'Missing token'}), 401

    id_token = auth_header.split(' ')[1]
    try:
        decoded = auth.verify_id_token(id_token)
        phone = normalize_phone(decoded.get('phone_number'))
    except Exception:
        return jsonify({'success': False, 'error': 'Invalid Firebase token'}), 401

    data = request.get_json(force=True, silent=True) or {}
    requested_phone = normalize_phone(data.get('phone_number'))
    new_password = (data.get('new_password') or '').strip()

    if phone != requested_phone:
        return jsonify({'success': False, 'error': 'Token does not match phone number'}), 403

    if not new_password:
        return jsonify({'success': False, 'error': 'New password required'}), 400

    user = User.query.filter_by(phone_number=phone).first()
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    user.password = generate_password_hash(new_password)
    db.session.commit()

    logger.info(f'Пароль обновлён: {phone}')
    return jsonify({'success': True}), 200

@app.route('/api/delete_account', methods=['DELETE'])
def delete_account():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'success': False, 'error': 'Missing token'}), 401

    token = auth_header.split(' ')[1]
    phone = verify_jwt_token(token)
    if not phone:
        return jsonify({'success': False, 'error': 'Invalid token'}), 401

    data = request.get_json(force=True, silent=True) or {}
    requested_phone = normalize_phone(data.get('phone_number'))

    if requested_phone != phone:
        return jsonify({'success': False, 'error': 'Token mismatch'}), 403

    user = User.query.filter_by(phone_number=phone).first()
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    db.session.delete(user)
    db.session.commit()
    logger.info(f'Удалён аккаунт: {phone}')
    return jsonify({'success': True}), 200

# -----------------------------
# 🔎 Healthcheck
# -----------------------------
@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({'success': True, 'status': 'Server is running'}), 200

# -----------------------------
# 🆕 Версии приложения
# -----------------------------
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import json
import jwt
import logging
import firebase_admin
from firebase_admin import credentials, auth

app = Flask(__name__)

# -----------------------------
# 🔧 Логирование
# -----------------------------
# На Render запись в файл может быть недоступна/эфемерна — оставим и StreamHandler, и FileHandler.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# -----------------------------
# 🔧 Конфигурация приложения
# -----------------------------
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///users.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(32).hex())

# Путь к конфигу версий для /api/app-version
CONFIG_PATH = os.environ.get("CONFIG_PATH", "config/config.json")

# -----------------------------
# 🔥 Firebase инициализация
# -----------------------------
service_account = os.environ.get('FIREBASE_SERVICE_ACCOUNT')
if not service_account:
    logger.error("FIREBASE_SERVICE_ACCOUNT не найдена")
    raise ValueError("FIREBASE_SERVICE_ACCOUNT не настроена")

try:
    service_account_dict = json.loads(service_account)
    # ключ из ENV часто приходит с \n — нормализуем
    service_account_dict["private_key"] = service_account_dict["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(service_account_dict)
    firebase_admin.initialize_app(cred)
except Exception as e:
    logger.error(f"Ошибка инициализации Firebase: {e}")
    raise

# -----------------------------
# 📦 База данных
# -----------------------------
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    time = db.Column(db.String(30), nullable=False)
    is_premium = db.Column(db.Boolean, default=False)

# -----------------------------
# 🔧 Утилиты
# -----------------------------
def normalize_phone(phone: str) -> str:
    digits = ''.join(filter(str.isdigit, phone or ""))
    if not digits:
        return '+7'
    if digits.startswith('8'):
        digits = '7' + digits[1:]
    elif not digits.startswith('7'):
        digits = '7' + digits
    return f'+{digits}'

def verify_jwt_token(token: str):
    try:
        data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return data['phone_number']
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

# -----------------------------
# 🔐 Эндпоинты аутентификации
# -----------------------------
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(force=True, silent=True) or {}
    phone_number = normalize_phone(data.get('phone_number', '').strip())
    password = (data.get('password') or '').strip()

    user = User.query.filter_by(phone_number=phone_number).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

    token = jwt.encode(
        {'phone_number': phone_number, 'exp': datetime.utcnow() + timedelta(hours=24)},
        app.config['SECRET_KEY'],
        algorithm='HS256'
    )

    logger.info(f'Вход выполнен: {phone_number}')
    return jsonify({
        'success': True,
        'token': token,
        'user': {'name': user.name, 'phone_number': phone_number, 'is_premium': user.is_premium}
    }), 200

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or '').strip()
    phone_number = normalize_phone((data.get('phone_number') or '').strip())
    password = (data.get('password') or '').strip()
    is_premium = bool(data.get('is_premium', False))

    if not name or not password:
        return jsonify({'success': False, 'error': 'Name and password are required'}), 400

    if User.query.filter_by(phone_number=phone_number).first():
        return jsonify({'success': False, 'error': 'Phone number already exists'}), 409

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

    logger.info(f'Зарегистрирован: {phone_number}')
    return jsonify({
        'success': True,
        'token': token,
        'user': {'name': name, 'phone_number': phone_number, 'is_premium': is_premium}
    }), 201

@app.route('/api/verify', methods=['POST'])
def verify():
    data = request.get_json(force=True, silent=True) or {}
    token = data.get('token')
    phone = data.get('phone')

    real_phone = verify_jwt_token(token or '')
    if real_phone == phone:
        logger.info(f'✅ Верификация успешна: {phone}')
        return jsonify({'success': True}), 200
    else:
        logger.warning(f'❌ Верификация не удалась: {phone}')
        return jsonify({'success': False, 'error': 'Invalid or expired token'}), 401

@app.route('/api/restore', methods=['POST'])
def restore():
    data = request.get_json(force=True, silent=True) or {}
    phone = normalize_phone(data.get('phone'))
    user = User.query.filter_by(phone_number=phone).first()

    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    token = jwt.encode(
        {'phone_number': phone, 'exp': datetime.utcnow() + timedelta(hours=24)},
        app.config['SECRET_KEY'],
        algorithm='HS256'
    )

    logger.info(f'🔁 Восстановление токена: {phone}')
    return jsonify({
        'success': True,
        'token': token,
        'user': {'name': user.name, 'phone_number': phone, 'is_premium': user.is_premium}
    }), 200

@app.route('/api/reset_password', methods=['POST'])
def reset_password():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'success': False, 'error': 'Missing token'}), 401

    id_token = auth_header.split(' ')[1]
    try:
        decoded = auth.verify_id_token(id_token)
        phone = normalize_phone(decoded.get('phone_number'))
    except Exception:
        return jsonify({'success': False, 'error': 'Invalid Firebase token'}), 401

    data = request.get_json(force=True, silent=True) or {}
    requested_phone = normalize_phone(data.get('phone_number'))
    new_password = (data.get('new_password') or '').strip()

    if phone != requested_phone:
        return jsonify({'success': False, 'error': 'Token does not match phone number'}), 403

    if not new_password:
        return jsonify({'success': False, 'error': 'New password required'}), 400

    user = User.query.filter_by(phone_number=phone).first()
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    user.password = generate_password_hash(new_password)
    db.session.commit()

    logger.info(f'Пароль обновлён: {phone}')
    return jsonify({'success': True}), 200

@app.route('/api/delete_account', methods=['DELETE'])
def delete_account():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'success': False, 'error': 'Missing token'}), 401

    token = auth_header.split(' ')[1]
    phone = verify_jwt_token(token)
    if not phone:
        return jsonify({'success': False, 'error': 'Invalid token'}), 401

    data = request.get_json(force=True, silent=True) or {}
    requested_phone = normalize_phone(data.get('phone_number'))

    if requested_phone != phone:
        return jsonify({'success': False, 'error': 'Token mismatch'}), 403

    user = User.query.filter_by(phone_number=phone).first()
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    db.session.delete(user)
    db.session.commit()
    logger.info(f'Удалён аккаунт: {phone}')
    return jsonify({'success': True}), 200

# -----------------------------
# 🔎 Healthcheck
# -----------------------------
@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({'success': True, 'status': 'Server is running'}), 200

# -----------------------------
# 🆕 Версии приложения
# -----------------------------
@app.route('/api/app-version', methods=['GET'])
def app_version():
    """
    Отдаёт содержимое config/config.json:
    {
      "latestVersion": "1.0.1",
      "minSupportedVersion": "1.0.1"
    }
    """
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        latest = str(data.get("latestVersion", "")).strip()
        if not latest:
            return jsonify({"error": "config.latestVersion is required"}), 500

        resp = {
            "latestVersion": latest,
            "minSupportedVersion": (str(data.get("minSupportedVersion")).strip()
                                    if data.get("minSupportedVersion") else None)
        }
        # Для аналитики можно логировать клиента (необязательно)
        client_v = request.args.get("v") or request.headers.get("X-App-Version")
        client_b = request.args.get("b") or request.headers.get("X-App-Build")
        client_platform = request.args.get("platform") or request.headers.get("X-Platform")
        client_pkg = request.args.get("pkg") or request.headers.get("X-Package-Id")
        logger.info(f"[update-check] platform={client_platform} pkg={client_pkg} v={client_v} b={client_b} ip={request.remote_addr}")

        return jsonify(resp), 200
    except FileNotFoundError:
        return jsonify({"error": f"config not found at {CONFIG_PATH}"}), 500
    except Exception as e:
        logger.exception("app-version error")
        return jsonify({"error": str(e)}), 500

# -----------------------------
# 🚀 Запуск
# -----------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # На Render лучше debug=False
    app.run(host='0.0.0.0', port=5000, debug=True)

        # Для аналитики можно логировать клиента (необязательно)
        client_v = request.args.get("v") or request.headers.get("X-App-Version")
        client_b = request.args.get("b") or request.headers.get("X-App-Build")
        client_platform = request.args.get("platform") or request.headers.get("X-Platform")
        client_pkg = request.args.get("pkg") or request.headers.get("X-Package-Id")
        logger.info(f"[update-check] platform={client_platform} pkg={client_pkg} v={client_v} b={client_b} ip={request.remote_addr}")

        return jsonify(resp), 200
    except FileNotFoundError:
        return jsonify({"error": f"config not found at {CONFIG_PATH}"}), 500
    except Exception as e:
        logger.exception("app-version error")
        return jsonify({"error": str(e)}), 500
