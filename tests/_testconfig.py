"""Конфигурация приложения для тестов (общая для conftest.py и отдельных тестов)."""

import os


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
    APP_JSON_LOG_PATH = "/tmp/classapp-test/app.json.log"
