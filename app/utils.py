import jwt
from datetime import datetime, timedelta
from flask import current_app


def normalize_phone(phone: str) -> str:
    digits = ''.join(filter(str.isdigit, phone or ""))
    if not digits:
        return '+7'
    if digits.startswith('8'):
        digits = '7' + digits[1:]
    elif not digits.startswith('7'):
        digits = '7' + digits
    return f'+{digits}'


def create_token(phone: str):
    return jwt.encode(
        {'phone_number': phone, 'exp': datetime.utcnow() + timedelta(hours=24)},
        current_app.config['SECRET_KEY'],
        algorithm='HS256'
    )


def verify_token(token: str):
    try:
        data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
        return data['phone_number']
    except jwt.PyJWTError:
        return None