"""Фабрика приложения: выбор конфигурации, bootstrap администратора, метрики,
обработчики ошибок и /healthz."""

import importlib
import io
import sys

import pytest
from flask import abort

import app as app_module
from app import create_app
from app.extensions import db
from app.models import User


def make_config(tmp_path, **extra):
    attrs = {
        "TESTING": True,
        "DEBUG": False,
        "SECRET_KEY": "factory-test",
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'factory.db'}",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "APP_JSON_LOG_PATH": str(tmp_path / "logs" / "app.json.log"),
        "ADMIN_PHONE": "375290000000",
        "ADMIN_NAME": "Администратор",
        "ADMIN_PASSWORD": "admin123",
    }
    attrs.update(extra)
    return type("FactoryConfig", (), attrs)


class TestConfigSelection:
    @pytest.fixture()
    def dev_config(self, tmp_path, monkeypatch):
        import config

        monkeypatch.setattr(
            config.DevConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{tmp_path / 'dev.db'}"
        )
        monkeypatch.setattr(config.DevConfig, "APP_JSON_LOG_PATH", str(tmp_path / "app.json.log"))
        return config.DevConfig

    def test_config_can_be_given_as_dotted_path(self, dev_config):
        application = create_app("config.DevConfig")
        assert application.config["DEBUG"] is True

    def test_config_is_taken_from_flask_config_env(self, dev_config, monkeypatch):
        monkeypatch.setenv("FLASK_CONFIG", "config.DevConfig")
        assert create_app().config["DEBUG"] is True

    def test_init_app_hook_is_called(self, tmp_path):
        calls = []

        class Hooked(make_config(tmp_path)):
            @staticmethod
            def init_app(application):
                calls.append(application)

        application = create_app(Hooked)
        assert calls == [application]

    def test_prod_config_fails_fast_without_secrets(self, tmp_path, monkeypatch):
        from config import ProdConfig

        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(ProdConfig, "APP_JSON_LOG_PATH", str(tmp_path / "app.json.log"))
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            create_app(ProdConfig)


class TestLogging:
    def test_log_file_is_created_and_receives_json(self, tmp_path):
        application = create_app(make_config(tmp_path))
        application.logger.info("hello from test")
        for handler in application.logger.handlers:
            handler.flush()
        content = (tmp_path / "logs" / "app.json.log").read_text()
        assert '"message": "hello from test"' in content
        assert '"level": "INFO"' in content

    def test_log_falls_back_to_instance_folder_when_path_is_not_writable(
        self, tmp_path, monkeypatch
    ):
        real_makedirs = app_module.os.makedirs

        def fake_makedirs(path, *args, **kwargs):
            if str(path) == str(tmp_path / "forbidden"):
                raise PermissionError(path)
            return real_makedirs(path, *args, **kwargs)

        monkeypatch.setattr(app_module.os, "makedirs", fake_makedirs)
        application = create_app(
            make_config(tmp_path, APP_JSON_LOG_PATH=str(tmp_path / "forbidden" / "app.json.log"))
        )
        assert application.config["APP_JSON_LOG_PATH"].endswith("app.json.log")
        assert "forbidden" not in application.config["APP_JSON_LOG_PATH"]


class TestAdminBootstrap:
    def test_admin_is_created_on_first_start(self, tmp_path):
        application = create_app(
            make_config(tmp_path, ADMIN_PHONE="375291110000", ADMIN_NAME="Босс")
        )
        with application.app_context():
            admin = User.query.filter_by(phone="375291110000").one()
            assert (admin.full_name, admin.role) == ("Босс", "admin")
            assert admin.check_password("admin123")

    def test_admin_without_password_gets_one(self, tmp_path):
        config = make_config(tmp_path)
        application = create_app(config)
        with application.app_context():
            User.query.filter_by(phone="375290000000").one().password_hash = ""
            db.session.commit()

        application = create_app(config)
        with application.app_context():
            assert User.query.filter_by(phone="375290000000").one().check_password("admin123")

    def test_name_and_role_are_restored_on_restart(self, tmp_path):
        config = make_config(tmp_path)
        with create_app(config).app_context():
            admin = User.query.filter_by(phone="375290000000").one()
            admin.full_name, admin.role = "Самозванец", "parent"
            db.session.commit()

        with create_app(config).app_context():
            admin = User.query.filter_by(phone="375290000000").one()
            assert (admin.full_name, admin.role) == ("Администратор", "admin")

    def test_phone_is_normalised(self, tmp_path):
        application = create_app(make_config(tmp_path, ADMIN_PHONE="+375 (29) 222-33-44"))
        with application.app_context():
            assert User.query.filter_by(phone="375292223344").count() == 1


class TestMetrics:
    def test_gunicorn_metrics_are_used_when_multiproc_dir_is_set(self, tmp_path, monkeypatch):
        used = []
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
        monkeypatch.setattr(app_module, "GunicornInternalPrometheusMetrics", used.append)
        monkeypatch.setattr(
            app_module, "PrometheusMetrics", lambda application: used.append("plain")
        )
        application = create_app(make_config(tmp_path))
        assert used == [application]

    def test_plain_metrics_are_used_otherwise(self, tmp_path, monkeypatch):
        used = []
        monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
        monkeypatch.setattr(app_module, "PrometheusMetrics", used.append)
        application = create_app(make_config(tmp_path))
        assert used == [application]

    def test_app_starts_without_the_metrics_library(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, "PrometheusMetrics", None)
        application = create_app(make_config(tmp_path))
        assert application.test_client().get("/healthz").status_code == 200

    def test_missing_metrics_package_is_tolerated_at_import(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "prometheus_flask_exporter", None)
        monkeypatch.setitem(sys.modules, "prometheus_flask_exporter.multiprocess", None)
        try:
            importlib.reload(app_module)
            assert app_module.PrometheusMetrics is None
            assert app_module.GunicornInternalPrometheusMetrics is None
        finally:
            monkeypatch.undo()
            importlib.reload(app_module)
        assert app_module.PrometheusMetrics is not None


class TestErrorHandlers:
    @pytest.fixture()
    def failing_app(self, tmp_path):
        application = create_app(make_config(tmp_path))

        @application.get("/boom")
        def boom():
            raise RuntimeError("secret internal detail")

        @application.get("/forbidden")
        def forbidden():
            abort(403)

        @application.get("/teapot-500")
        def explicit_500():
            abort(500)

        return application

    def test_unhandled_exception_becomes_a_json_500(self, failing_app):
        response = failing_app.test_client().get("/boom")
        assert response.status_code == 500
        assert response.get_json() == {"error": "Internal Server Error"}
        assert b"secret internal detail" not in response.data

    def test_unhandled_exception_is_logged_with_traceback(self, failing_app, caplog):
        with caplog.at_level("ERROR", logger=failing_app.logger.name):
            failing_app.test_client().get("/boom")
        record = next(r for r in caplog.records if "Internal Server Error" in r.getMessage())
        assert record.exc_info is not None

    def test_explicit_abort_500_is_json_too(self, failing_app):
        response = failing_app.test_client().get("/teapot-500")
        assert response.status_code == 500
        assert response.get_json() == {"error": "Internal Server Error"}

    def test_http_exceptions_keep_their_status(self, failing_app):
        client = failing_app.test_client()
        assert client.get("/forbidden").status_code == 403
        assert client.get("/no-such-page").status_code == 404
        assert client.post("/healthz").status_code == 405

    def test_oversized_upload_is_rejected_with_413(self, tmp_path):
        application = create_app(make_config(tmp_path, MAX_CONTENT_LENGTH=200))
        client = application.test_client()
        client.post("/login", data={"username": "375290000000", "password": "admin123"})
        response = client.post(
            "/info",
            data={"description": "Большой файл", "file": (io.BytesIO(b"x" * 5000), "big.pdf")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 413


class TestHealthz:
    def test_ok(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok", "database": "ok"}

    def test_reports_database_failure(self, client, monkeypatch):
        def broken(*args, **kwargs):
            raise RuntimeError("database is down")

        monkeypatch.setattr(db.session, "execute", broken)
        response = client.get("/healthz")
        assert response.status_code == 503
        assert response.get_json()["database"] == "error"
