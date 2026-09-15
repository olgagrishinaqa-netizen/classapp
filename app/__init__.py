import os
import logging
import sys

from flask import Flask, jsonify
from pythonjsonlogger.json import JsonFormatter
from sqlalchemy import text
from werkzeug.utils import import_string
from werkzeug.exceptions import HTTPException

from .extensions import db
from .models import User

try:
    from prometheus_flask_exporter import PrometheusMetrics
except ImportError:
    PrometheusMetrics = None


def configure_json_logging(app):
    configured_log_path = app.config.get("APP_JSON_LOG_PATH", "/var/log/classapp/app.json.log")
    log_path = configured_log_path
    log_dir = os.path.dirname(log_path)
    try:
        os.makedirs(log_dir, exist_ok=True)
    except PermissionError:
        os.makedirs(app.instance_path, exist_ok=True)
        log_path = os.path.join(app.instance_path, "app.json.log")
        app.config["APP_JSON_LOG_PATH"] = log_path

    existing_handler = next(
        (
            handler
            for handler in app.logger.handlers
            if isinstance(handler, logging.FileHandler)
            and os.path.abspath(getattr(handler, "baseFilename", "")) == os.path.abspath(log_path)
        ),
        None,
    )
    if existing_handler is None:
        handler = logging.FileHandler(log_path)
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            JsonFormatter(
                "%(asctime)s %(levelname)s %(message)s %(pathname)s %(lineno)d",
                rename_fields={
                    "asctime": "timestamp",
                    "levelname": "level",
                    "pathname": "path",
                    "lineno": "line",
                },
            )
        )
        app.logger.addHandler(handler)

    app.logger.setLevel(logging.INFO)


def create_app(config_object=None):
    if not config_object:
        config_object = os.getenv("FLASK_CONFIG", "config.DevConfig")

    # Приводим строку конфигурации к реальному классу
    if isinstance(config_object, str):
        config_class = import_string(config_object)
    else:
        config_class = config_object

    app = Flask(__name__)
    app.config.from_object(config_class)
    configure_json_logging(app)

    # Fail-fast проверка секретов (вызов init_app на классе конфигурации)
    if hasattr(config_class, "init_app"):
        config_class.init_app(app)

    # Инициализация расширений
    db.init_app(app)

    with app.app_context():
        # In production schema changes are applied exclusively by Alembic before web starts.
        if app.config.get("AUTO_CREATE_SCHEMA", app.testing or app.debug):
            db.create_all()
        admin_phone = User.normalize_phone(app.config.get("ADMIN_PHONE", "79990000000"))
        admin_name = app.config.get("ADMIN_NAME", "Администратор")
        admin_password = app.config.get("ADMIN_PASSWORD", "admin123")
        admin = User.query.filter_by(phone=admin_phone).first()
        if admin is None:
            admin = User(
                full_name=admin_name,
                phone=admin_phone,
                role="admin",
            )
            db.session.add(admin)
        else:
            admin.full_name = admin_name
            admin.role = "admin"

        if not admin.password_hash or not admin.check_password(admin_password):
            admin.set_password(admin_password)

        db.session.commit()

    if PrometheusMetrics is not None:
        PrometheusMetrics(app)

    from .routes import bp

    app.register_blueprint(bp)

    @app.errorhandler(500)
    def internal_server_error(error):
        has_traceback = sys.exc_info()[0] is not None
        app.logger.error("Internal Server Error: %s", error, exc_info=has_traceback)
        return jsonify(error="Internal Server Error"), 500

    @app.errorhandler(Exception)
    def handle_exception(error):
        if isinstance(error, HTTPException):
            return error
        return internal_server_error(error)

    @app.get("/healthz")
    def healthz():
        """Liveness/readiness-проба для CI и Docker healthcheck."""
        db_status = "ok"
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            db_status = "error"

        status_code = 200 if db_status == "ok" else 503
        return jsonify(status="ok", database=db_status), status_code

    return app
