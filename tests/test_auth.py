from sqlalchemy import inspect

from app import create_app
from app.models import Expense, ExpenseReport, News, Payment, Task, User


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
    assert login.headers["Location"].endswith("/dashboard")

    task = Task(title="Проверить план", description="На этой неделе")
    report = ExpenseReport(
        income=1000,
        expense_items=[{"title": "Бумага", "amount": 250, "category": "Канцтовары"}],
    )
    db.session.add_all([task, report])
    db.session.commit()

    assert client.get("/tasks").status_code == 200
    assert client.get("/expenses").status_code == 200

    expenses_before = Expense.query.count()
    create_expense = client.post(
        "/expenses",
        data={"action": "add_expense", "title": "Маркер", "amount": "125.50", "category": "Канцтовары"},
        follow_redirects=False,
    )
    assert create_expense.status_code == 302
    assert Expense.query.count() == expenses_before + 1


def test_admin_can_record_payment_and_expense(client, db):
    client.post("/login", data={"username": "79990000000", "password": "admin123"})
    parent = User(full_name="Плательщик", phone="79991234562", role="parent")
    parent.set_password("secure-pass")
    db.session.add(parent)
    db.session.commit()

    payment = client.post(
        "/expenses",
        data={"action": "add_payment", "user_id": parent.id, "amount": "1000.00"},
        follow_redirects=False,
    )
    expense = client.post(
        "/expenses",
        data={"action": "add_expense", "title": "Тетради", "amount": "350.00", "category": "Учеба"},
        follow_redirects=False,
    )

    assert payment.status_code == 302
    assert expense.status_code == 302
    assert float(Payment.query.filter_by(user_id=parent.id).one().amount) == 1000
    assert float(Expense.query.filter_by(title="Тетради").one().amount) == 350
    page = client.get("/expenses")
    expected_balance = sum(float(item.amount) for item in Payment.query.all()) - sum(
        float(item.amount) for item in Expense.query.all()
    )
    assert f"{expected_balance:.2f}".encode() in page.data


def test_finance_records_can_be_edited_only_by_an_administrator(client, db):
    client.post("/login", data={"username": "79990000000", "password": "admin123"})
    parent = User(full_name="Родитель взноса", phone="79991234563", role="parent")
    parent.set_password("secure-pass")
    payment = Payment(user=parent, amount=100)
    expense = Expense(title="Старое название", amount=30, category="Общие")
    db.session.add_all([parent, payment, expense])
    db.session.commit()

    edit_payment = client.post(
        f"/payments/edit/{payment.id}",
        data={"user_id": parent.id, "amount": "150.00"},
        follow_redirects=False,
    )
    edit_expense = client.post(
        f"/expenses/edit/{expense.id}",
        data={"title": "Новое название", "amount": "45.00", "category": "Учеба"},
        follow_redirects=False,
    )
    assert edit_payment.status_code == 302
    assert edit_expense.status_code == 302
    assert float(db.session.get(Payment, payment.id).amount) == 150
    assert db.session.get(Expense, expense.id).title == "Новое название"

    client.post("/logout")
    client.post("/login", data={"username": parent.phone, "password": "secure-pass"})
    forbidden_edit = client.post(
        f"/expenses/edit/{expense.id}",
        data={"title": "Недопустимое изменение", "amount": "1.00", "category": "Общие"},
        follow_redirects=False,
    )
    assert forbidden_edit.status_code == 302
    assert db.session.get(Expense, expense.id).title == "Новое название"
    read_only_page = client.get("/expenses")
    assert b"+ \xd0\x92\xd0\xb7\xd0\xbd\xd0\xbe\xd1\x81" not in read_only_page.data
    assert b"add_expense" not in read_only_page.data


def test_dashboard_news_users_and_profile_role_mode(client, db):
    login = client.post(
        "/login",
        data={"username": "79990000000", "password": "admin123"},
        follow_redirects=False,
    )
    assert login.status_code == 302

    news_item = News(title="Собрание", description="В пятницу в 18:00", status="published")
    member = User(full_name="Родитель Тест", phone="79991234561", role="parent")
    member.set_password("secure-pass")
    db.session.add_all([news_item, member])
    db.session.commit()

    dashboard = client.get("/dashboard")
    news_page = client.get("/news")
    users_page = client.get("/users")
    profile = client.get("/profile")
    assert dashboard.status_code == 200
    assert b"\xd0\x90\xd0\xb4\xd0\xbc\xd0\xb8\xd0\xbd" in dashboard.data
    assert b"\xd0\xa1\xd0\xbe\xd0\xb1\xd1\x80\xd0\xb0\xd0\xbd\xd0\xb8\xd0\xb5" in news_page.data
    assert b"\xd0\xa0\xd0\xbe\xd0\xb4\xd0\xb8\xd1\x82\xd0\xb5\xd0\xbb\xd1\x8c \xd0\xa2\xd0\xb5\xd1\x81\xd1\x82" in users_page.data
    assert b"/change_role" in profile.data

    change_role = client.post("/change_role", data={"role": "parent"}, follow_redirects=False)
    assert change_role.status_code == 302
    parent_dashboard = client.get("/dashboard")
    assert b"\xd0\xa0\xd0\xbe\xd0\xb4\xd0\xb8\xd1\x82\xd0\xb5\xd0\xbb\xd1\x8c" in parent_dashboard.data
    assert client.get("/users").headers["Location"].endswith("/dashboard")


def test_user_management_creates_sorts_filters_edits_and_deletes_users(client, db):
    client.post("/login", data={"username": "79990000000", "password": "admin123"})

    create_student = client.post(
        "/users",
        data={
            "action": "create_user",
            "last_name": "Яковлев",
            "first_name": "Антон",
            "middle_name": "",
            "phone": "+375 (29) 123-45-67",
            "role": "student",
            "password": "secure-pass",
        },
        follow_redirects=False,
    )
    create_parent = client.post(
        "/users",
        data={
            "action": "create_user",
            "last_name": "Алексеева",
            "first_name": "Мария",
            "middle_name": "Ивановна",
            "phone": "+375 (33) 123-45-67",
            "role": "parent",
            "password": "secure-pass",
        },
        follow_redirects=False,
    )
    assert create_student.status_code == 302
    assert create_parent.status_code == 302

    student = User.query.filter_by(phone="375291234567").one()
    parent = User.query.filter_by(phone="375331234567").one()
    page = client.get("/users")
    page_text = page.data.decode()
    assert page_text.index("Администратор") < page_text.index("Алексеева Мария Ивановна")
    assert page_text.index("Алексеева Мария Ивановна") < page_text.index("Яковлев Антон")
    assert "Яковлев Антон" not in client.get("/users?role_filter=parent").data.decode()

    edit = client.post(
        f"/users/edit/{student.id}",
        data={
            "last_name": "Яковлев",
            "first_name": "Антон",
            "middle_name": "Петрович",
            "phone": "+375 (29) 123-45-67",
            "role": "parent",
            "password": "",
        },
        follow_redirects=False,
    )
    delete = client.post(f"/users/delete/{parent.id}", follow_redirects=False)
    assert edit.status_code == 302
    assert delete.status_code == 302
    assert User.query.filter_by(id=student.id).one().full_name == "Яковлев Антон Петрович"
    assert db.session.get(User, parent.id) is None


def test_login_updates_last_login(client, db):
    admin = User.query.filter_by(phone="79990000000").one()
    admin.last_login = None
    db.session.commit()

    response = client.post("/api/login", json={"phone": "79990000000", "password": "admin123"})

    assert response.status_code == 200
    assert db.session.get(User, admin.id).last_login is not None


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


def test_admin_password_is_not_reset_on_bootstrap_by_default(tmp_path):
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
        assert admin.check_password("wrong-password")


def test_admin_password_can_be_reset_on_bootstrap_when_enabled(tmp_path):
    db_path = tmp_path / "bootstrap-admin-reset.db"

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
        ADMIN_RESET_PASSWORD_ON_BOOT = True

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


def test_admin_bootstrap_is_skipped_when_user_table_does_not_exist(tmp_path):
    db_path = tmp_path / "bootstrap-no-user-table.db"

    class BootstrapConfig:
        TESTING = True
        DEBUG = False
        SECRET_KEY = "bootstrap-secret"
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        AUTO_CREATE_SCHEMA = False
        ADMIN_PHONE = "79990000000"
        ADMIN_NAME = "Администратор"
        ADMIN_PASSWORD = "admin123"

    app = create_app(config_object=BootstrapConfig)
    with app.app_context():
        from app.extensions import db

        assert not inspect(db.engine).has_table("user")
