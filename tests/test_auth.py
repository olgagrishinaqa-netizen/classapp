from app import create_app
from app.models import ExpenseReport, Task, User


def test_login_accepts_common_phone_formats(client):
    for phone in ["79990000000", "+7 (999) 000-00-00", "89990000000"]:
        response = client.post(
            "/api/login",
            json={"phone": phone, "password": "admin123"},
        )
        assert response.status_code == 200, phone
        payload = response.get_json()
        assert payload["user"]["phone"] == "79990000000"


def test_mobile_pages_render_and_use_server_forms(client, db):
    login_page = client.get("/login")
    assert login_page.status_code == 200
    assert b"maximum-scale=1.0, user-scalable=no" in login_page.data
    assert b'name="username"' in login_page.data

    login = client.post(
        "/login",
        data={"username": "+7 (999) 000-00-00", "password": "admin123"},
        follow_redirects=False,
    )
    assert login.status_code == 302
    assert login.headers["Location"].endswith("/tasks")

    task = Task(title="Проверить план", description="На этой неделе")
    report = ExpenseReport(
        income=1000,
        expense_items=[{"title": "Бумага", "amount": 250, "category": "Канцтовары"}],
    )
    db.session.add_all([task, report])
    db.session.commit()

    assert client.get("/tasks").status_code == 200
    assert client.get("/expenses").status_code == 200

    reports_before = ExpenseReport.query.count()
    create_expense = client.post(
        "/expenses",
        data={"title": "Маркер", "amount": "125.50", "category": "Канцтовары"},
        follow_redirects=False,
    )
    assert create_expense.status_code == 302
    assert ExpenseReport.query.count() == reports_before + 1


def test_user_creation_normalizes_phone(db):
    user = User(full_name="Иван Иванов", phone="+7 (999) 123-45-67", role="parent")
    user.set_password("secure-pass")
    db.session.add(user)
    db.session.commit()

    assert user.phone == "79991234567"
    assert User.query.filter_by(phone="79991234567").count() == 1


def test_admin_can_create_parent_from_user_form(client, db):
    login = client.post(
        "/api/login",
        json={"phone": "79990000000", "password": "admin123"},
    )
    assert login.status_code == 200

    response = client.post(
        "/api/users",
        data={
            "full_name": "Иван Иванов",
            "phone": "+7 (999) 123-45-70",
            "role": "parent",
            "password": "secure-pass",
        },
    )

    assert response.status_code == 201
    assert response.get_json()["user"]["role"] == "parent"
    assert User.query.filter_by(phone="79991234570").one().full_name == "Иван Иванов"


def test_admin_can_create_parent_with_russian_role_name(client, db):
    login = client.post(
        "/api/login",
        json={"phone": "79990000000", "password": "admin123"},
    )
    assert login.status_code == 200

    response = client.post(
        "/api/users",
        data={
            "full_name": "Елена Смирнова",
            "phone": "+7 (999) 123-45-71",
            "role": "Родитель",
            "password": "secure-pass",
        },
    )

    assert response.status_code == 201
    assert response.get_json()["user"]["role"] == "parent"
    assert User.query.filter_by(phone="79991234571").one().full_name == "Елена Смирнова"


def test_login_rejects_invalid_password_hash_without_server_error(client, db):
    user = User(full_name="Поврежденный пользователь", phone="79991234568", role="parent", password_hash="legacy")
    db.session.add(user)
    db.session.commit()

    response = client.post(
        "/api/login",
        json={"phone": "79991234568", "password": "secure-pass"},
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "Неверный телефон или пароль"


def test_login_returns_users_with_unknown_legacy_role(client, db):
    user = User(full_name="Старый пользователь", phone="79991234569", role="teacher")
    user.set_password("secure-pass")
    db.session.add(user)
    db.session.commit()

    response = client.post(
        "/api/login",
        json={"phone": "79991234569", "password": "secure-pass"},
    )

    assert response.status_code == 200
    assert response.get_json()["user"]["role_label"] == "teacher"


def test_admin_password_is_reset_to_default_on_bootstrap(tmp_path):
    db_path = tmp_path / "bootstrap-admin.db"

    class BootstrapConfig:
        TESTING = True
        DEBUG = False
        SECRET_KEY = "bootstrap-secret"
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        ADMIN_PHONE = "79990000000"
        ADMIN_NAME = "Администратор"
        ADMIN_PASSWORD = "admin123"

    app = create_app(config_object=BootstrapConfig)
    with app.app_context():
        admin = User.query.filter_by(phone="79990000000").first()
        admin.set_password("wrong-password")
        from app.extensions import db

        db.session.commit()

    app = create_app(config_object=BootstrapConfig)
    with app.app_context():
        admin = User.query.filter_by(phone="79990000000").first()
        assert admin is not None
        assert admin.check_password("admin123")
