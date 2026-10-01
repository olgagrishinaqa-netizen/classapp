from app.audit import describe_device
from app.models import LoginEvent, User


def _login_admin(client):
    client.post("/login", data={"username": "79990000000", "password": "admin123"})


def test_login_events_are_stored_in_database(client, db):
    LoginEvent.query.delete()
    db.session.commit()
    client.post("/login", data={"username": "79990000000", "password": "wrong-pass"})
    client.post("/login", data={"username": "79990000000", "password": "admin123"})
    client.post("/logout")

    events = [e.event for e in LoginEvent.query.order_by(LoginEvent.id)]
    assert events == ["login_failed", "login_success", "logout"]
    failed, success, _ = LoginEvent.query.order_by(LoginEvent.id).all()
    assert failed.reason == "bad_password"
    assert failed.user_id is None
    assert success.user_id is not None
    assert success.phone == "***0000"
    assert "admin123" not in repr([vars(e) for e in (failed, success)])


def test_admin_sees_login_log_with_names(client, db):
    LoginEvent.query.delete()
    db.session.commit()
    _login_admin(client)
    admin = User.query.filter_by(phone="79990000000").one()

    page = client.get("/admin/login-log")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert admin.full_name in html
    assert "Вход" in html
    assert "***0000" in html
    assert "79990000000" not in html


def test_login_log_filter_shows_only_failed(client, db):
    LoginEvent.query.delete()
    db.session.commit()
    client.post("/login", data={"username": "79990000000", "password": "wrong-pass"})
    client.post("/login", data={"username": "79990000000", "password": "admin123"})

    html = client.get("/admin/login-log?filter=failed").get_data(as_text=True)
    assert "Неудачный вход" in html
    assert "неверный пароль" in html
    assert 'class="badge-medium shrink-0">Вход<' not in html


def test_login_log_requires_login_and_admin_role(client, db):
    anonymous = client.get("/admin/login-log", follow_redirects=False)
    assert anonymous.status_code == 302
    assert "/login" in anonymous.headers["Location"]

    parent = User.query.filter_by(phone="79991112233").first()
    if parent is None:
        parent = User(full_name="Родитель", phone="79991112233", role="parent")
        parent.set_password("parent123")
        db.session.add(parent)
        db.session.commit()
    client.post("/login", data={"username": "79991112233", "password": "parent123"})
    denied = client.get("/admin/login-log", follow_redirects=False)
    assert denied.status_code == 302
    assert "/dashboard" in denied.headers["Location"]


def test_describe_device():
    ua = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Mobile Safari/537.36"
    assert describe_device(ua) == "Android · Chrome"
    assert describe_device("") == "Неизвестное устройство"
