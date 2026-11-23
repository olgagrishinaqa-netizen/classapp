"""Страницы входа, регистрации, выхода, профиля и переключения роли."""

from datetime import datetime

from _credentials import ADMIN_PASSWORD, ADMIN_PHONE

from app.models import Expense, LoginEvent, News, Task, User


def text(response):
    return response.get_data(as_text=True)


def last_event(event):
    return LoginEvent.query.filter_by(event=event).order_by(LoginEvent.id.desc()).first()


class TestIndex:
    def test_anonymous_goes_to_login(self, client):
        response = client.get("/")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")

    def test_logged_in_goes_to_dashboard(self, admin_client):
        response = admin_client.get("/")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/dashboard")


class TestLoginPage:
    def test_form_is_shown(self, client):
        response = client.get("/login")
        assert response.status_code == 200
        assert 'name="username"' in text(response)
        assert 'name="password"' in text(response)

    def test_logged_in_user_is_redirected_away(self, admin_client):
        response = admin_client.get("/login")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/tasks")

    def test_admin_login_sets_session_and_last_login(self, client, db):
        response = client.post("/login", data={"username": ADMIN_PHONE, "password": ADMIN_PASSWORD})
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/dashboard")
        with client.session_transaction() as session:
            assert session["active_role"] == "admin"
            assert session["user_id"]
        admin = User.query.filter_by(phone=ADMIN_PHONE).one()
        assert admin.last_login is not None
        assert (datetime.now() - admin.last_login).total_seconds() < 60
        assert last_event("login_success").user_id == admin.id

    def test_parent_login_keeps_parent_role(self, app, make_user, login_as):
        user = make_user(role="parent")
        client = app.test_client()
        response = login_as(client, user.phone, user.plain_password)
        assert response.status_code == 302
        with client.session_transaction() as session:
            assert session["active_role"] == "parent"

    def test_phone_can_be_typed_with_mask(self, client):
        response = client.post(
            "/login", data={"username": "+375 (29) 000-00-00", "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 302

    def test_wrong_password_is_rejected_and_logged(self, client):
        response = client.post("/login", data={"username": ADMIN_PHONE, "password": "nope"})
        assert response.status_code == 200
        assert "Неверный номер телефона или пароль." in text(response)
        with client.session_transaction() as session:
            assert "user_id" not in session
        event = last_event("login_failed")
        assert event.reason == "bad_password"
        assert event.phone == "***0000"
        assert event.channel == "web"

    def test_unknown_phone_is_rejected_and_logged(self, client):
        response = client.post("/login", data={"username": "375001112233", "password": "x"})
        assert response.status_code == 200
        assert "Неверный номер телефона или пароль." in text(response)
        assert last_event("login_failed").reason == "unknown_user"

    def test_empty_fields_do_not_create_an_event(self, client):
        before = LoginEvent.query.count()
        response = client.post("/login", data={"username": "", "password": ""})
        assert response.status_code == 200
        assert LoginEvent.query.count() == before


class TestRegisterPage:
    def _register(self, client, **overrides):
        data = {
            "full_name": "Мария Новикова",
            "username": "+375 (44) 555-66-77",
            "password": "secret123",
            "password_confirm": "secret123",
        }
        data.update(overrides)
        return client.post("/register", data=data)

    def test_form_is_shown(self, client):
        response = client.get("/register")
        assert response.status_code == 200
        assert 'name="password_confirm"' in text(response)

    def test_logged_in_user_is_redirected_away(self, admin_client):
        response = admin_client.get("/register")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/tasks")

    def test_successful_registration_creates_a_parent(self, client, db):
        response = self._register(client, username="+375 (44) 100-00-01")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")
        user = User.query.filter_by(phone="375441000001").one()
        assert user.role == "parent"
        assert user.full_name == "Мария Новикова"
        assert user.check_password("secret123")
        assert last_event("register").user_id == user.id
        followed = client.get("/login")
        assert "Аккаунт создан. Теперь войдите в приложение." in text(followed)

    def test_registered_user_can_log_in(self, client, login_as, app):
        self._register(client, username="+375 (44) 100-00-02")
        fresh = app.test_client()
        assert login_as(fresh, "375441000002", "secret123").status_code == 302
        with fresh.session_transaction() as session:
            assert "user_id" in session

    def test_full_name_is_trimmed(self, client):
        self._register(client, username="375441000003", full_name="  Ольга  ")
        assert User.query.filter_by(phone="375441000003").one().full_name == "Ольга"

    def test_registration_cannot_pick_admin_role(self, client):
        self._register(client, username="375441000004", role="admin")
        assert User.query.filter_by(phone="375441000004").one().role == "parent"

    def test_duplicate_phone_is_rejected_and_logged(self, client):
        before = User.query.count()
        response = self._register(client, username=ADMIN_PHONE)
        assert response.status_code == 200
        assert "Этот номер телефона уже зарегистрирован." in text(response)
        assert User.query.count() == before
        assert last_event("register_rejected").reason == "phone_exists"

    def test_phone_without_digits_is_rejected(self, client):
        response = self._register(client, username="не номер")
        assert response.status_code == 200
        assert "Введите корректный номер телефона." in text(response)

    def test_password_mismatch_is_rejected(self, client):
        response = self._register(client, username="375441000005", password_confirm="other")
        assert response.status_code == 200
        assert "Пароли должны совпадать" in text(response)
        assert User.query.filter_by(phone="375441000005").count() == 0

    def test_short_password_is_rejected(self, client):
        response = self._register(
            client, username="375441000006", password="123", password_confirm="123"
        )
        assert response.status_code == 200
        assert User.query.filter_by(phone="375441000006").count() == 0

    def test_missing_name_is_rejected(self, client):
        response = self._register(client, username="375441000007", full_name="")
        assert response.status_code == 200
        assert User.query.filter_by(phone="375441000007").count() == 0


class TestLogout:
    def test_logout_clears_the_session(self, admin_client):
        response = admin_client.post("/logout")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")
        with admin_client.session_transaction() as session:
            assert "user_id" not in session
        assert admin_client.get("/dashboard").status_code == 302
        assert last_event("logout") is not None

    def test_logout_shows_a_message(self, admin_client):
        response = admin_client.post("/logout", follow_redirects=True)
        assert "Вы вышли из аккаунта." in text(response)

    def test_logout_requires_post(self, admin_client):
        assert admin_client.get("/logout").status_code == 405

    def test_logout_without_session_still_redirects(self, client):
        assert client.post("/logout").status_code == 302


class TestDashboard:
    def test_anonymous_is_redirected(self, client):
        response = client.get("/dashboard")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")

    def test_shows_counters_and_latest_published_news(self, admin_client, db, wipe):
        wipe(News, Task, Expense)
        db.session.add_all(
            [
                Task(title="Активная 1"),
                Task(title="Активная 2", status="in_progress"),
                Task(title="Готовая", status="done"),
                News(title="Черновик скрыт", description="d", status="draft"),
                News(title="Опубликованная новость", description="d", status="published"),
                Expense(title="Мел", amount=150, category="Общие"),
            ]
        )
        db.session.commit()

        page = text(admin_client.get("/dashboard"))

        assert "Опубликованная новость" in page
        assert "Черновик скрыт" not in page
        assert "150" in page

    def test_works_without_any_data(self, admin_client, wipe):
        wipe(News, Task, Expense)
        assert admin_client.get("/dashboard").status_code == 200

    def test_session_role_is_reset_when_user_is_not_admin(self, parent_client):
        with parent_client.session_transaction() as session:
            session["active_role"] = "admin"
        assert parent_client.get("/dashboard").status_code == 200
        with parent_client.session_transaction() as session:
            assert session["active_role"] == "parent"


class TestProfileAndRoleSwitch:
    def test_profile_requires_login(self, client):
        response = client.get("/profile")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")

    def test_admin_sees_role_testing_block(self, admin_client):
        page = text(admin_client.get("/profile"))
        assert "Тестирование ролей" in page
        assert "Пользователи" in page
        assert "Состав класса" in page

    def test_parent_does_not_see_admin_blocks(self, parent_client):
        page = text(parent_client.get("/profile"))
        assert "Тестирование ролей" not in page
        assert "Состав класса" not in page

    def test_change_role_requires_login(self, client):
        response = client.post("/change_role", data={"role": "parent"})
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")

    def test_admin_can_switch_to_parent_mode_and_back(self, admin_client):
        response = admin_client.post("/change_role", data={"role": "parent"}, follow_redirects=True)
        assert "Включен режим: Родитель." in text(response)
        with admin_client.session_transaction() as session:
            assert session["active_role"] == "parent"

        # В режиме родителя админские страницы закрыты.
        denied = admin_client.get("/users", follow_redirects=True)
        assert "Доступ к пользователям разрешен только администратору." in text(denied)

        back = admin_client.post("/change_role", data={"role": "admin"}, follow_redirects=True)
        assert "Включен режим: Админ." in text(back)
        assert admin_client.get("/users").status_code == 200

    def test_parent_cannot_become_admin(self, parent_client):
        response = parent_client.post("/change_role", data={"role": "admin"}, follow_redirects=True)
        assert "Режим администратора недоступен для этого аккаунта." in text(response)
        with parent_client.session_transaction() as session:
            assert session["active_role"] == "parent"

    def test_invalid_role_is_rejected(self, admin_client):
        response = admin_client.post("/change_role", data={"role": "hacker"}, follow_redirects=True)
        assert "Выберите корректную роль." in text(response)

    def test_missing_role_is_rejected(self, admin_client):
        response = admin_client.post("/change_role", data={}, follow_redirects=True)
        assert "Выберите корректную роль." in text(response)
