import os

from flask import Flask, jsonify
from sqlalchemy import text

from .extensions import db  # и др. ваши расширения: login_manager, csrf и т.д.

try:
    from prometheus_flask_exporter import PrometheusMetrics
except ImportError:  # пакет опционален для локальной разр без мониторинга
    PrometheusMetrics = None


def create_app(config_object=None):
    if not config_object:
        config_object = os.getenv("FLASK_CONFIG", "config.DevConfig")

    app = Flask(__name__)
    app.config.from_object(config_object)

    # init extensions
    db.init_app(app)
    # login_manager.init_app(app), csrf.init_app(app), и т.д.

    if PrometheusMetrics is not None:
        # Автоматически публикует GET /metrics для сбора Prometheus'ом
        PrometheusMetrics(app)

    @app.get("/healthz")
    def healthz():
        """Liveness/readiness-проба: испол-я и тестами CI,
         и Docker healthcheck'ом."""
        db_status = "ok"
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            db_status = "error"

        status_code = 200 if db_status == "ok" else 503
        return jsonify(status="ok", database=db_status), status_code

    # register blueprints
    # from .views.auth import bp as auth_bp
    # app.register_blueprint(auth_bp)
    # ... остальные

    return app
