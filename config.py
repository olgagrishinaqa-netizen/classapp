"""Конфигурация Flask-приложения: значения по умолчанию для dev и жёсткие
fail-fast проверки обязательных секретов для прода."""

import os


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    ADMIN_NAME = os.getenv("ADMIN_NAME", "Администратор")
    ADMIN_PHONE = os.getenv("ADMIN_PHONE", "79990000000")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    ADMIN_RESET_PASSWORD_ON_BOOT = str(os.getenv("ADMIN_RESET_PASSWORD_ON_BOOT", "False")).lower() in (
        "1",
        "true",
        "yes",
    )
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(os.getcwd(), "uploads"))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(10 * 1024 * 1024)))
    APP_JSON_LOG_PATH = os.getenv("APP_JSON_LOG_PATH", "/var/log/classapp/app.json.log")

    @staticmethod
    def init_app(app):
        """Хук для проверок конфигурации при старте.
        В базовом классе — no-op, переопределяется там, где нужно."""
        pass


class DevConfig(BaseConfig):
    """Локальная разработка: DEBUG включён, допустимы дефолтные секреты/SQLite."""

    DEBUG = True


class ProdConfig(BaseConfig):
    """Продакшен: требует явных SECRET_KEY/DATABASE_URL, см. init_app."""

    DEBUG = False
    # By default do not force secure-only cookies unless explicitly configured.
    # In many deployments TLS is terminated by a reverse proxy; enable by env var when TLS is present.
    SESSION_COOKIE_SECURE = str(os.getenv("SESSION_COOKIE_SECURE", "False")).lower() in ("1", "true", "yes")

    @staticmethod
    def init_app(app):
        BaseConfig.init_app(app)

        missing = []
        if os.getenv("SECRET_KEY") is None:
            missing.append("SECRET_KEY")
        if os.getenv("DATABASE_URL") is None:
            missing.append("DATABASE_URL")

        if missing:
            raise RuntimeError(
                "ProdConfig: отсутствуют обязательные переменные окружения: "
                f"{', '.join(missing)}. Приложение не может стартовать в проде "
                "с дефолтными значениями (SECRET_KEY='dev-secret', SQLite)."
            )