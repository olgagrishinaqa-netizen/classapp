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
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(os.getcwd(), "uploads"))

    @staticmethod
    def init_app(app):
        """Хук для проверок конфигурации при старте.
        В базовом классе — no-op, переопределяется там, где нужно."""
        pass


class DevConfig(BaseConfig):
    DEBUG = True


class ProdConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True  # cookie только по HTTPS

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