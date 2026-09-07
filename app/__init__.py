import os
from flask import Flask
from .extensions import db  # и др. ваши расширения: login_manager, csrf и т.д.

def create_app(config_object=None):
    if not config_object:
        config_object = os.getenv("FLASK_CONFIG", "config.DevConfig")

    app = Flask(__name__)
    app.config.from_object(config_object)

    # init extensions
    db.init_app(app)
    # login_manager.init_app(app), csrf.init_app(app), и т.д.

    # register blueprints
    # from .views.auth import bp as auth_bp
    # app.register_blueprint(auth_bp)
    # ... остальные

    return app
