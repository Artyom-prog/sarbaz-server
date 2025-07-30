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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///users.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(32).hex())

# Инициализация Firebase с переменной окружения
service_account = os.environ.get('FIREBASE_SERVICE_ACCOUNT')
if not service_account:
    logger.error("Переменная окружения FIREBASE_SERVICE_ACCOUNT не найдена")
    raise ValueError("Переменная окружения FIREBASE_SERVICE_ACCOUNT не настроена")

try:
    service_account_dict = json.loads(service_account)
    
    # 🔧 Преобразуем все `\\n` в настоящие переводы строк `\n` в private_key
    if "private_key" in service_account_dict:
        service_account_dict["private_key"] = service_account_dict["private_key"].replace("\\n", "\n")
    
    cred = credentials.Certificate(service_account_dict)
except Exception as e:
    logger.error(f"Ошибка парсинга Firebase учетных данных: {str(e)}")
    raise

firebase_admin.initialize_app(cred)

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

# Проверка JWT-токена (оставляем для других эндпоинтов)
def verify_jwt_token(token):
    try:
        data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return data['phone_number']
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# Эндпоинт для входа
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    phone_number = normalize_phone(data.get('phone_number', '').strip())
    password = data.get('password', '').strip()

    if not phone_number or not password:
        logger.warning('Отсутствует номер телефона или пароль')
        return jsonify({'success': False, 'error': 'Missing phone number or password'}), 400

    user = User.query.filter_by(phone_number=phone_number).first()
    if not user or not check_password_hash(user.password, password):
        logger.warning(f'Неверные учетные данные: {phone_number}')
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

# Эндпоинт для регистрации
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name', '').strip()
    phone_number = normalize_phone(data.get('phone_number', '').strip())
    password = data.get('password', '').strip()
    is_premium = data.get('is_premium', False)

    if not name or not phone_number or not password:
        logger.warning('Отсутствуют обязательные поля')
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400

    if User.query.filter_by(phone_number=phone_number).first():
        logger.warning(f'Номер телефона уже существует: {phone_number}')
        return jsonify({'success': False, 'error': 'Phone number already exists'}), 409

    try:
        user = User(
            name=name,
            phone_number=phone_number,
            password=generate_password_hash(password, method='pbkdf2:sha256'),
            time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            is_premium=is_premium
        )
        db.session.add(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при регистрации: {str(e)}')
        return jsonify({'success': False, 'error': 'Database error'}), 500

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

# Эндпоинт для сброса пароля с Firebase ID-токеном
@app.route('/api/reset_password', methods=['POST'])
def reset_password():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        logger.warning('Отсутствует или неверный токен для сброса пароля')
        return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401

    try:
        id_token = auth_header.split(' ')[1]
        decoded_token = auth.verify_id_token(id_token)  # Проверка Firebase ID-токена
        phone_number = decoded_token.get('phone_number')
        if not phone_number:
            logger.warning('Отсутствует номер телефона в Firebase токене')
            return jsonify({'success': False, 'error': 'Invalid token data'}), 401
    except Exception as e:
        logger.warning(f'Неверный Firebase токен: {str(e)}')
        return jsonify({'success': False, 'error': 'Invalid or expired token'}), 401

    data = request.get_json()
    requested_phone = normalize_phone(data.get('phone_number', '').strip())
    new_password = data.get('new_password', '').strip()

    if phone_number != requested_phone:
        logger.warning(f'Токен не соответствует номеру телефона: {requested_phone}')
        return jsonify({'success': False, 'error': 'Token does not match phone number'}), 403

    if not new_password:
        logger.warning('Отсутствует новый пароль')
        return jsonify({'success': False, 'error': 'Missing new password'}), 400

    if len(new_password) < 6:
        logger.warning('Пароль слишком короткий')
        return jsonify({'success': False, 'error': 'Password must be at least 6 characters'}), 400

    user = User.query.filter_by(phone_number=phone_number).first()
    if not user:
        logger.warning(f'Пользователь не найден: {phone_number}')
        return jsonify({'success': False, 'error': 'User not found'}), 404

    try:
        user.password = generate_password_hash(new_password, method='pbkdf2:sha256')
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при сбросе пароля: {str(e)}')
        return jsonify({'success': False, 'error': 'Database error'}), 500

    logger.info(f'Пароль обновлен для: {phone_number}')
    return jsonify({'success': True, 'status': 'Password updated successfully'}), 200

# Эндпоинт для выхода
@app.route('/api/logout', methods=['POST'])
def logout():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        logger.warning('Отсутствует или неверный токен для выхода')
        return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401

    token = auth_header.split(' ')[1]
    phone_number = verify_jwt_token(token)  # Используем JWT для logout
    if not phone_number:
        logger.warning('Неверный или истекший токен')
        return jsonify({'success': False, 'error': 'Invalid or expired token'}), 401

    logger.info(f'Выход выполнен: {phone_number}')
    return jsonify({'success': True, 'status': 'Logged out successfully'}), 200

# Эндпоинт для удаления аккаунта
@app.route('/api/delete_account', methods=['DELETE'])
def delete_account():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        logger.warning('Отсутствует или неверный токен для удаления аккаунта')
        return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401

    token = auth_header.split(' ')[1]
    phone_number = verify_jwt_token(token)  # Используем JWT для delete_account
    if not phone_number:
        logger.warning('Неверный или истекший токен')
        return jsonify({'success': False, 'error': 'Invalid or expired token'}), 401

    data = request.get_json()
    requested_phone = normalize_phone(data.get('phone_number', '').strip())
    if phone_number != requested_phone:
        logger.warning(f'Токен не соответствует номеру телефона: {requested_phone}')
        return jsonify({'success': False, 'error': 'Token does not match phone number'}), 403

    user = User.query.filter_by(phone_number=phone_number).first()
    if not user:
        logger.warning(f'Пользователь не найден: {phone_number}')
        return jsonify({'success': False, 'error': 'User not found'}), 404

    try:
        db.session.delete(user)
        db.session.commit()
        logger.info(f'Аккаунт удален: {phone_number}')
        return jsonify({'success': True, 'status': 'Account deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при удалении аккаунта: {str(e)}')
        return jsonify({'success': False, 'error': 'Database error'}), 500

# Эндпоинт для проверки сервера
@app.route('/api/ping', methods=['GET'])
def ping():
    logger.info('Проверка сервера')
    return jsonify({'success': True, 'status': 'Server is running'}), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
