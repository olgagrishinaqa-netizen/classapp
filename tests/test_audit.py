import json


def _events(app):
    with open(app.config["APP_JSON_LOG_PATH"], encoding="utf-8") as log_file:
        entries = [json.loads(line) for line in log_file if line.strip()]
    return [entry for entry in entries if entry.get("event")]


def test_successful_login_is_audited_with_masked_phone(client, app):
    client.post("/login", data={"username": "79990000000", "password": "admin123"})
    event = [e for e in _events(app) if e["event"] == "login_success"][-1]
    assert event["phone"] == "***0000"
    assert event["user_id"]
    assert "admin123" not in json.dumps(event)
    assert "79990000000" not in json.dumps(event)


def test_failed_login_is_audited_with_reason(client, app):
    client.post("/login", data={"username": "79990000000", "password": "wrong-pass"})
    client.post("/login", data={"username": "79995550000", "password": "whatever"})
    failed = [e for e in _events(app) if e["event"] == "login_failed"][-2:]
    assert [e["reason"] for e in failed] == ["bad_password", "unknown_user"]
    assert "wrong-pass" not in json.dumps(failed)


def test_state_changing_action_is_audited(client, app):
    client.post("/login", data={"username": "79990000000", "password": "admin123"})
    client.post("/news", data={"title": "Аудит", "description": "т", "status": "published"})
    event = [e for e in _events(app) if e["event"] == "action"][-1]
    assert event["endpoint"] == "main.news_page"
    assert event["method"] == "POST"
    assert event["user_id"]
    assert event["role"] == "admin"


def test_logout_is_audited(client, app):
    client.post("/login", data={"username": "79990000000", "password": "admin123"})
    client.post("/logout")
    assert [e for e in _events(app) if e["event"] == "logout"][-1]["channel"] == "web"


def test_login_attempts_are_exposed_as_prometheus_metrics(client):
    client.post("/login", data={"username": "79990000000", "password": "nope-nope"})
    client.post("/login", data={"username": "79990000000", "password": "admin123"})
    metrics = client.get("/metrics").data.decode()
    assert 'classapp_login_attempts_total{channel="web",result="failure"}' in metrics
    assert 'classapp_login_attempts_total{channel="web",result="success"}' in metrics
