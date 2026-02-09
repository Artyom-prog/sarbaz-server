from flask import Flask
from .config import Config
from .extensions import db

from .routes.auth import bp as auth_bp
from .routes.user import bp as user_bp
from .routes.system import bp as system_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(system_bp)

    return app