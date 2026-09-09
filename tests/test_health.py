def test_app_factory_creates_app(app):
    assert app is not None
    assert app.config["TESTING"] is True


def test_health_endpoint_returns_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["status"] == "ok"


def test_health_endpoint_reports_db_status(client):
    response = client.get("/healthz")
    payload = response.get_json()
    assert "database" in payload
