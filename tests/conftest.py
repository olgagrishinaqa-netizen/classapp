import os

import pytest

from app import create_app
from app.extensions import db as _db


class TestConfig:
    """Конфиг только для тестов — не трогает существующий config.py."""

    TESTING = True
    DEBUG = False
    SECRET_KEY = "test-secret-key"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL",
        "sqlite:///test_classapp.db",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False


@pytest.fixture(scope="session")
def app():
    application = create_app(config_object=TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    return _db


class TestProdConfigInitApp:
    """Тесты fail-fast инициализации продакшн-конфигурации для диплома."""

    def test_prod_init_app_raises_when_secret_key_missing(self, monkeypatch):
        from flask import Flask
        from config import ProdConfig

        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h/db")

        app = Flask(__name__)
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            ProdConfig.init_app(app)

    def test_prod_init_app_raises_when_database_url_missing(self, monkeypatch):
        from flask import Flask
        from config import ProdConfig

        monkeypatch.setenv("SECRET_KEY", "real-secret")
        monkeypatch.delenv("DATABASE_URL", raising=False)

        app = Flask(__name__)
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            ProdConfig.init_app(app)

    def test_prod_init_app_passes_when_both_env_vars_set(self, monkeypatch):
        from flask import Flask
        from config import ProdConfig

        monkeypatch.setenv("SECRET_KEY", "real-secret")
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h/db")

        app = Flask(__name__)
        ProdConfig.init_app(app)  # Не должно выбросить исключение

    def test_prod_config_session_cookie_secure_is_true(self):
        from config import ProdConfig

        assert ProdConfig.SESSION_COOKIE_SECURE is True
