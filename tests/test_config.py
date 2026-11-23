"""Конфигурация приложения: значения по умолчанию и fail-fast проверки прода."""

import importlib

import pytest
from flask import Flask


@pytest.fixture()
def reload_config(monkeypatch):
    """Перечитывает config.py с заданными переменными окружения.

    Значения в классах конфигурации вычисляются при импорте модуля, поэтому для
    проверки разбора переменных окружения модуль приходится перезагружать.
    После теста окружение и модуль возвращаются в исходное состояние."""
    import config

    def _reload(**env):
        for name, value in env.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        return importlib.reload(config)

    yield _reload
    monkeypatch.undo()
    importlib.reload(config)


class TestProdConfigInitApp:
    """Fail-fast инициализация продакшн-конфигурации."""

    def test_prod_init_app_raises_when_secret_key_missing(self, monkeypatch):
        from config import ProdConfig

        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h/db")

        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            ProdConfig.init_app(Flask(__name__))

    def test_prod_init_app_raises_when_database_url_missing(self, monkeypatch):
        from config import ProdConfig

        monkeypatch.setenv("SECRET_KEY", "real-secret")
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            ProdConfig.init_app(Flask(__name__))

    def test_prod_init_app_reports_every_missing_variable(self, monkeypatch):
        from config import ProdConfig

        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(RuntimeError) as error:
            ProdConfig.init_app(Flask(__name__))
        assert "SECRET_KEY" in str(error.value)
        assert "DATABASE_URL" in str(error.value)

    def test_prod_init_app_passes_when_both_env_vars_set(self, monkeypatch):
        from config import ProdConfig

        monkeypatch.setenv("SECRET_KEY", "real-secret")
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h/db")

        ProdConfig.init_app(Flask(__name__))  # не должно выбросить исключение


class TestConfigDefaults:
    def test_base_init_app_is_a_noop(self):
        from config import BaseConfig

        assert BaseConfig.init_app(Flask(__name__)) is None

    def test_dev_config_enables_debug(self):
        from config import DevConfig

        assert DevConfig.DEBUG is True

    def test_prod_config_disables_debug(self):
        from config import ProdConfig

        assert ProdConfig.DEBUG is False

    def test_cookies_are_httponly_and_lax(self):
        from config import BaseConfig

        assert BaseConfig.SESSION_COOKIE_HTTPONLY is True
        assert BaseConfig.SESSION_COOKIE_SAMESITE == "Lax"

    def test_prod_cookie_is_not_secure_by_default(self, reload_config):
        # За TLS обычно стоит прокси, поэтому secure-куки включаются только переменной окружения.
        module = reload_config(SESSION_COOKIE_SECURE=None)
        assert module.ProdConfig.SESSION_COOKIE_SECURE is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
    def test_prod_cookie_secure_can_be_enabled_by_env(self, reload_config, value):
        module = reload_config(SESSION_COOKIE_SECURE=value)
        assert module.ProdConfig.SESSION_COOKIE_SECURE is True

    def test_prod_cookie_secure_ignores_other_values(self, reload_config):
        module = reload_config(SESSION_COOKIE_SECURE="no")
        assert module.ProdConfig.SESSION_COOKIE_SECURE is False

    def test_admin_defaults(self, reload_config):
        module = reload_config(
            ADMIN_NAME=None,
            ADMIN_PHONE=None,
            ADMIN_PASSWORD=None,
            ADMIN_RESET_PASSWORD_ON_BOOT=None,
        )
        assert module.BaseConfig.ADMIN_NAME == "Администратор"
        assert module.BaseConfig.ADMIN_PHONE == "375290000000"
        assert module.BaseConfig.ADMIN_PASSWORD == "admin123"
        assert module.BaseConfig.ADMIN_RESET_PASSWORD_ON_BOOT is False

    @pytest.mark.parametrize("value", ["1", "true", "Yes"])
    def test_admin_password_reset_flag_parses_truthy_values(self, reload_config, value):
        module = reload_config(ADMIN_RESET_PASSWORD_ON_BOOT=value)
        assert module.BaseConfig.ADMIN_RESET_PASSWORD_ON_BOOT is True

    def test_env_overrides_secret_database_and_upload_settings(self, reload_config):
        module = reload_config(
            SECRET_KEY="from-env",
            DATABASE_URL="sqlite:///from-env.db",
            UPLOAD_FOLDER="/data/uploads",
            MAX_CONTENT_LENGTH="2048",
            APP_JSON_LOG_PATH="/data/app.log",
        )
        base = module.BaseConfig
        assert base.SECRET_KEY == "from-env"
        assert base.SQLALCHEMY_DATABASE_URI == "sqlite:///from-env.db"
        assert base.UPLOAD_FOLDER == "/data/uploads"
        assert base.MAX_CONTENT_LENGTH == 2048
        assert base.APP_JSON_LOG_PATH == "/data/app.log"

    def test_default_upload_limit_is_ten_megabytes(self, reload_config):
        module = reload_config(MAX_CONTENT_LENGTH=None)
        assert module.BaseConfig.MAX_CONTENT_LENGTH == 10 * 1024 * 1024
