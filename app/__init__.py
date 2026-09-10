import os

from flask import Flask, jsonify
from sqlalchemy import text
from werkzeug.utils import import_string

from .extensions import db
from .models import User

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

    with app.app_context():
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

    @app.errorhandler(Exception)
    def handle_exception(e):
        # Логируем полную трассировку для дальнейшей диагностики
        import traceback

        tb = traceback.format_exc()
        app.logger.error("Unhandled exception:\n%s", tb)
        # Всегда возвращаем JSON для API-запросов — это удобнее для фронтенда и логирования
        from flask import request

        if request.path.startswith("/api/"):
            return jsonify(error="Internal Server Error"), 500
        # Для обычных страниц возвращаем тот же ответ в виде JSON (без утечки подробностей)
        return jsonify(error="Internal Server Error"), 500

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
