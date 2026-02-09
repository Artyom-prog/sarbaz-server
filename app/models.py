from datetime import datetime
from .extensions import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    time = db.Column(db.String(30), nullable=False,
                     default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    is_premium = db.Column(db.Boolean, default=False)