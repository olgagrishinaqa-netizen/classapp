import os


def build_database_url(default="sqlite:///dev.db"):
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    postgres_host = os.getenv("POSTGRES_HOST")
    postgres_db = os.getenv("POSTGRES_DB")
    postgres_user = os.getenv("POSTGRES_USER")
    db_password = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")
    if postgres_host and postgres_db and postgres_user and db_password:
        return "postgresql://{}:{}@{}:5432/{}".format(
            postgres_user,
            db_password,
            postgres_host,
            postgres_db,
        )

    return default


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    SQLALCHEMY_DATABASE_URI = build_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    ADMIN_NAME = os.getenv("ADMIN_NAME", "Администратор")
    ADMIN_PHONE = os.getenv("ADMIN_PHONE", "79990000000")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(os.getcwd(), "uploads"))
    APP_JSON_LOG_PATH = os.getenv("APP_JSON_LOG_PATH", "/var/log/classapp/app.json.log")

    @staticmethod
    def init_app(app):
        """Хук для проверок конфигурации при старте.
        В базовом классе — no-op, переопределяется там, где нужно."""
        app.config["SQLALCHEMY_DATABASE_URI"] = build_database_url(
            default=app.config.get("SQLALCHEMY_DATABASE_URI", "sqlite:///dev.db")
        )


class DevConfig(BaseConfig):
    DEBUG = True


class ProdConfig(BaseConfig):
    DEBUG = False
    # By default do not force secure-only cookies unless explicitly configured.
    # In many deployments TLS is terminated by a reverse proxy; enable by env
    # var when TLS is present.
    _session_cookie_secure = os.getenv("SESSION_COOKIE_SECURE", "False").lower()
    SESSION_COOKIE_SECURE = _session_cookie_secure in ("1", "true", "yes")

    @staticmethod
    def init_app(app):
        BaseConfig.init_app(app)

        missing = []
        if os.getenv("SECRET_KEY") is None:
            missing.append("SECRET_KEY")
        has_database_url = os.getenv("DATABASE_URL") is not None
        db_password = os.getenv("DB_PASSWORD")
        postgres_password = os.getenv("POSTGRES_PASSWORD")
        has_database_password = db_password is not None or postgres_password is not None
        has_database_parts = (
            all(
                os.getenv(name) is not None
                for name in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER")
            )
            and has_database_password
        )
        if not has_database_url and not has_database_parts:
            missing.append("DATABASE_URL or POSTGRES_* with DB_PASSWORD")

        if missing:
            raise RuntimeError(
                "ProdConfig: отсутствуют обязательные переменные окружения: "
                f"{', '.join(missing)}. Приложение не может стартовать в проде "
                "с дефолтными значениями (SECRET_KEY='dev-secret', SQLite)."
            )
