import os

from flask import Flask, jsonify
from sqlalchemy import text
from werkzeug.utils import import_string

from .extensions import db

try:
    from prometheus_flask_exporter import PrometheusMetrics
except ImportError:
    PrometheusMetrics = None


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

    # Fail-fast проверка секретов (вызов init_app на классе конфигурации)
    if hasattr(config_class, "init_app"):
        config_class.init_app(app)

    # Инициализация расширений
    db.init_app(app)

    if PrometheusMetrics is not None:
        PrometheusMetrics(app)

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
