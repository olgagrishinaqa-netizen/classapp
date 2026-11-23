"""Безопасность фронтенда: экранирование пользовательских данных в шаблонах (XSS),
CSRF-токены в формах и флаги сессионной cookie."""

from datetime import time

import pytest
from _testconfig import TestConfig
from bs4 import BeautifulSoup

from app import create_app
from app.models import (
    BellScheduleEntry,
    Expense,
    GeneralInfo,
    News,
    NewsImage,
    Payment,
    ScheduleEntry,
    Student,
    Task,
    User,
)

PAYLOAD = "<img src=x onerror=alert(1)>\"'<script>alert(2)</script>"
# Для колонок короче 40 символов (кабинет урока): PostgreSQL, в отличие от SQLite, обрезку не прощает.
SHORT_PAYLOAD = "<img src=x onerror=alert(1)>"
ATTR_PAYLOAD = '" onmouseover="alert(3)" x="'


def soup_of(response):
    return BeautifulSoup(response.get_data(as_text=True), "lxml")


def assert_no_injected_markup(response, where):
    """В ответе нет ни одного элемента/атрибута, внесённого пользовательским вводом."""
    raw = response.get_data(as_text=True)
    soup = BeautifulSoup(raw, "lxml")
    assert not soup.find("img", attrs={"onerror": True}), f"{where}: сработал <img onerror>"
    assert not soup.find(attrs={"onmouseover": True}), f"{where}: внедрён onmouseover"
    for script in soup.find_all("script"):
        body = script.get_text()
        assert "alert(1)" not in body and "alert(2)" not in body, f"{where}: код попал в <script>"
    assert "<script>alert(2)" not in raw, f"{where}: тег script не экранирован"


@pytest.fixture()
def hostile_data(db, wipe):
    """Строки с опасным содержимым во всех пользовательских полях."""
    wipe(
        Payment,
        Expense,
        Student,
        GeneralInfo,
        NewsImage,
        News,
        ScheduleEntry,
        BellScheduleEntry,
        Task,
    )
    student = Student(last_name=PAYLOAD, first_name=ATTR_PAYLOAD)
    db.session.add_all(
        [
            student,
            News(title=PAYLOAD, description=PAYLOAD + ATTR_PAYLOAD, status="published"),
            Task(title=PAYLOAD, description=PAYLOAD),
            ScheduleEntry(
                day_of_week=0,
                lesson_number=1,
                subject=PAYLOAD,
                teacher=ATTR_PAYLOAD,
                room=SHORT_PAYLOAD,
            ),
            BellScheduleEntry(lesson_number=1, start_time=time(8, 0), end_time=time(9, 0)),
            GeneralInfo(description=PAYLOAD, file_name=PAYLOAD, file_path="f.pdf"),
            Expense(title=PAYLOAD, amount=10, category=ATTR_PAYLOAD),
        ]
    )
    db.session.commit()
    db.session.add(Payment(student_id=student.id, amount=5))
    db.session.commit()


class TestOutputEscaping:
    @pytest.mark.parametrize(
        "url",
        ["/dashboard", "/news", "/tasks", "/schedule", "/info", "/expenses", "/admin/students"],
    )
    def test_user_content_is_escaped_for_admin(self, admin_client, hostile_data, url):
        assert_no_injected_markup(admin_client.get(url), url)

    @pytest.mark.parametrize("url", ["/news", "/tasks", "/schedule", "/info", "/expenses"])
    def test_user_content_is_escaped_for_parent(self, parent_client, hostile_data, url):
        assert_no_injected_markup(parent_client.get(url), url)

    def test_escaped_text_is_still_displayed_to_the_user(self, parent_client, hostile_data):
        page = soup_of(parent_client.get("/news")).get_text()
        assert "<img src=x onerror=alert(1)>" in page

    def test_confirm_message_attribute_cannot_be_broken_out_of(self, admin_client, db, wipe):
        wipe(NewsImage, News)
        db.session.add(News(title=ATTR_PAYLOAD, description="д", status="published"))
        db.session.commit()
        form = soup_of(admin_client.get("/news")).select_one("form.js-confirm-delete")
        assert ATTR_PAYLOAD in form["data-confirm-message"]
        assert not form.has_attr("onmouseover")

    def test_edit_forms_escape_current_values(self, admin_client, db, wipe):
        wipe(NewsImage, News)
        news = News(title=PAYLOAD, description=PAYLOAD, status="draft")
        db.session.add(news)
        db.session.commit()
        assert_no_injected_markup(admin_client.get(f"/news/{news.id}/edit"), "news edit")

    def test_user_names_are_escaped_in_the_users_page(self, admin_client, make_user):
        make_user(full_name=PAYLOAD)
        assert_no_injected_markup(admin_client.get("/users"), "/users")

    def test_search_query_cannot_break_out_of_inline_script(self, admin_client):
        response = admin_client.get("/admin/students?search=</script><script>alert(1)</script>")
        assert_no_injected_markup(response, "search")
        assert "</script><script>alert(1)" not in response.get_data(as_text=True)

    def test_search_query_is_escaped_in_the_input(self, admin_client):
        response = admin_client.get("/admin/students", query_string={"search": ATTR_PAYLOAD})
        assert_no_injected_markup(response, "search input")

    def test_flash_messages_are_escaped(self, admin_client, wipe):
        wipe(Payment, Student)
        admin_client.post("/admin/students", data={"last_name": PAYLOAD[:60], "first_name": "Имя"})
        assert_no_injected_markup(admin_client.get("/admin/students"), "flash")

    def test_login_log_escapes_client_supplied_headers(self, admin_client, client):
        client.post(
            "/login",
            data={"username": "375290000000", "password": "wrong"},
            headers={"X-Real-IP": PAYLOAD[:60], "User-Agent": PAYLOAD},
        )
        assert_no_injected_markup(admin_client.get("/admin/login-log"), "login log")

    def test_register_form_redisplays_input_escaped(self, client):
        response = client.post(
            "/register",
            data={"full_name": PAYLOAD, "username": "", "password": "1", "password_confirm": "2"},
        )
        assert_no_injected_markup(response, "register")


class TestUserContentNeverBecomesMarkupViaApi:
    def test_api_returns_json_not_html(self, admin_client, hostile_data):
        response = admin_client.get("/api/tasks")
        assert response.mimetype == "application/json"
        assert PAYLOAD in response.get_json()["tasks"][0]["title"]

    def test_json_errors_are_not_html(self, client):
        response = client.get("/api/users")
        assert response.mimetype == "application/json"


@pytest.fixture()
def csrf_client(tmp_path):
    """Клиент приложения с включённой CSRF-защитой (как в проде)."""

    class CsrfConfig(TestConfig):
        WTF_CSRF_ENABLED = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'csrf.db'}"
        APP_JSON_LOG_PATH = str(tmp_path / "app.json.log")

    application = create_app(CsrfConfig)
    return application.test_client()


def csrf_token(client, url="/login"):
    page = soup_of(client.get(url))
    field = page.find("input", attrs={"name": "csrf_token"})
    assert field is not None, f"на {url} нет csrf_token"
    return field["value"]


class TestCsrfProtection:
    def test_login_without_token_is_rejected(self, csrf_client):
        response = csrf_client.post(
            "/login", data={"username": "375290000000", "password": "admin123"}
        )
        assert response.status_code == 200
        with csrf_client.session_transaction() as session:
            assert "user_id" not in session

    def test_login_with_a_valid_token_succeeds(self, csrf_client):
        token = csrf_token(csrf_client)
        response = csrf_client.post(
            "/login",
            data={"username": "375290000000", "password": "admin123", "csrf_token": token},
        )
        assert response.status_code == 302

    def test_login_with_a_forged_token_is_rejected(self, csrf_client):
        csrf_token(csrf_client)
        response = csrf_client.post(
            "/login",
            data={"username": "375290000000", "password": "admin123", "csrf_token": "forged"},
        )
        assert response.status_code == 200
        with csrf_client.session_transaction() as session:
            assert "user_id" not in session

    def test_registration_without_token_creates_nothing(self, csrf_client):
        response = csrf_client.post(
            "/register",
            data={
                "full_name": "Хакер",
                "username": "375298888888",
                "password": "secret123",
                "password_confirm": "secret123",
            },
        )
        assert response.status_code == 200
        assert User.query.filter_by(phone="375298888888").count() == 0

    def test_admin_form_without_token_changes_nothing(self, csrf_client, wipe):
        token = csrf_token(csrf_client)
        csrf_client.post(
            "/login",
            data={"username": "375290000000", "password": "admin123", "csrf_token": token},
        )
        wipe(Task)
        response = csrf_client.post("/tasks", data={"title": "Без токена"})
        assert response.status_code == 200
        assert Task.query.count() == 0

    @pytest.mark.parametrize(
        ("url", "form_selector"),
        [
            ("/login", "form"),
            ("/register", "form"),
            ("/news", "form#news-form"),
            ("/info", "form#info-form"),
            ("/tasks", "dialog#create-task-dialog form"),
            ("/expenses", "dialog#expense-dialog form"),
            ("/expenses", "dialog#payment-dialog form"),
            ("/schedule", "dialog#create-schedule-dialog form"),
            ("/bell-schedule", "dialog#create-bell-dialog form"),
            ("/users", "dialog#create-user-dialog form"),
            ("/admin/students", "dialog#create-student-dialog form"),
            ("/profile", 'form[action="/change_role"]'),
        ],
    )
    def test_wtforms_forms_carry_a_csrf_token(self, csrf_client, url, form_selector):
        if url not in ("/login", "/register"):
            csrf_client.post(
                "/login",
                data={
                    "username": "375290000000",
                    "password": "admin123",
                    "csrf_token": csrf_token(csrf_client),
                },
            )
        form = soup_of(csrf_client.get(url)).select_one(form_selector)
        assert form is not None, f"{url}: форма {form_selector} не найдена"
        token = form.find("input", attrs={"name": "csrf_token", "type": "hidden"})
        assert token is not None and token["value"], f"{url}: в форме нет csrf_token"


class TestSessionCookie:
    @pytest.fixture()
    def real_config_client(self, tmp_path):
        """Приложение с настоящим BaseConfig (в TestConfig флаги cookie не заданы)."""
        from config import BaseConfig

        class RealCookieConfig(BaseConfig):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'cookie.db'}"
            APP_JSON_LOG_PATH = str(tmp_path / "app.json.log")
            WTF_CSRF_ENABLED = False

        return create_app(RealCookieConfig).test_client()

    def test_cookie_is_httponly_and_samesite_lax(self, real_config_client):
        response = real_config_client.post(
            "/login", data={"username": "375290000000", "password": "admin123"}
        )
        cookie = response.headers.get("Set-Cookie", "")
        assert "HttpOnly" in cookie
        assert "SameSite=Lax" in cookie

    def test_session_does_not_contain_the_password(self, client):
        client.post("/login", data={"username": "375290000000", "password": "admin123"})
        with client.session_transaction() as session:
            assert "admin123" not in repr(dict(session))
