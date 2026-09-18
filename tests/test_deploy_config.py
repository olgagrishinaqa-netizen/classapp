from pathlib import Path

import yaml

from config import build_database_url

ROOT = Path(__file__).resolve().parents[1]


def load_yaml_documents(relative_path):
    return list(yaml.safe_load_all((ROOT / relative_path).read_text()))


def container_env(manifest, container_name):
    for container in manifest["spec"]["template"]["spec"]["containers"]:
        if container["name"] == container_name:
            return {entry["name"]: entry for entry in container.get("env", [])}
    raise AssertionError(f"Container {container_name} not found")


def test_build_database_url_from_postgres_parts(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "classapp-db-master")
    monkeypatch.setenv("POSTGRES_DB", "classapp")
    monkeypatch.setenv("POSTGRES_USER", "postgres")
    monkeypatch.setenv("DB_PASSWORD", "super-secret")

    database_url = build_database_url()

    assert database_url.startswith("postgresql://")
    assert "super-secret" in database_url
    assert database_url.endswith("@classapp-db-master:5432/classapp")


def test_prod_config_accepts_component_database_settings(monkeypatch):
    from flask import Flask

    from config import ProdConfig

    monkeypatch.setenv("SECRET_KEY", "real-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "classapp-db-master")
    monkeypatch.setenv("POSTGRES_DB", "classapp")
    monkeypatch.setenv("POSTGRES_USER", "postgres")
    monkeypatch.setenv("DB_PASSWORD", "super-secret")

    app = Flask(__name__)
    app.config.from_object(ProdConfig)

    ProdConfig.init_app(app)

    database_url = app.config["SQLALCHEMY_DATABASE_URI"]

    assert database_url.startswith("postgresql://")
    assert "super-secret" in database_url
    assert database_url.endswith("@classapp-db-master:5432/classapp")


def test_kubernetes_manifests_use_component_database_env():
    web_manifest = load_yaml_documents("k8s/classapp-web.yaml")[0]
    migrate_manifest = load_yaml_documents("k8s/migrate-job.yaml")[0]

    web_env = container_env(web_manifest, "classapp-web")
    migrate_env = container_env(migrate_manifest, "classapp-migrate")

    assert "DATABASE_URL" not in web_env
    assert "DATABASE_URL" not in migrate_env
    assert web_env["POSTGRES_HOST"]["value"] == "classapp-db-master"
    assert migrate_env["POSTGRES_HOST"]["value"] == "classapp-db-master"


def test_deploy_workflow_waits_for_db_master_endpoints():
    workflow_text = (ROOT / ".github/workflows/deploy.yml").read_text()

    assert "get endpoints classapp-db-master" in workflow_text
    assert "Ожидание появления endpoint у сервиса classapp-db-master" in workflow_text
