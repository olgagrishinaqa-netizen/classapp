"""Каждая страница открывается в браузере без JavaScript-ошибок.

Проверку ошибок консоли выполняет фикстура `page` (см. conftest.py) после каждого теста."""

import pytest
from playwright.sync_api import expect

from app.models import GeneralInfo, News, NewsImage, ScheduleEntry, Student, Task

pytestmark = pytest.mark.e2e

PUBLIC_PAGES = ["/login", "/register"]
ADMIN_PAGES = [
    "/dashboard",
    "/news",
    "/schedule",
    "/bell-schedule",
    "/info",
    "/tasks",
    "/expenses",
    "/profile",
    "/users",
    "/admin/students",
    "/admin/login-log",
]


@pytest.fixture()
def populated(seed):
    def create(db):
        db.session.add_all(
            [
                Student(last_name="Иванов", first_name="Пётр"),
                Task(title="Задача"),
                News(
                    title="Новость",
                    description="Текст",
                    status="published",
                    images=[NewsImage(path="missing.png", position=0)],
                ),
                GeneralInfo(description="Информация"),
                ScheduleEntry(day_of_week=0, lesson_number=1, subject="Математика"),
            ]
        )

    seed(create)


@pytest.mark.parametrize("url", PUBLIC_PAGES)
def test_public_page_opens_cleanly(page, url):
    response = page.goto(url)
    assert response.status == 200
    expect(page.get_by_role("heading", level=1)).to_have_count(1)


@pytest.mark.parametrize("url", ADMIN_PAGES)
def test_admin_page_opens_cleanly(admin_page, populated, url):
    response = admin_page.goto(url)
    assert response.status == 200
    expect(admin_page.get_by_role("heading", level=1)).to_have_count(1)
    assert admin_page.title().strip()


@pytest.mark.parametrize(
    "url", ["/dashboard", "/tasks", "/expenses", "/news", "/profile", "/schedule", "/info"]
)
def test_parent_page_opens_cleanly(page, login, seed, populated, url):
    from app.models import User

    def create(db):
        user = User(full_name="Родитель Тестовый", phone="375297770003", role="parent")
        user.set_password("secret123")
        db.session.add(user)

    seed(create)
    login("297770003", "secret123")
    page.wait_for_url("**/dashboard")
    assert page.goto(url).status == 200


def test_unknown_page_returns_404_without_js_errors(page):
    assert page.goto("/no-such-page").status == 404


def test_page_does_not_scroll_horizontally_on_a_phone(admin_page, populated):
    """Мобильная раскладка: без горизонтальной прокрутки (измеряется по размерам документа)."""
    overflowing = []
    for url in ("/dashboard", "/tasks", "/expenses", "/profile"):
        admin_page.goto(url)
        width = admin_page.evaluate("document.documentElement.scrollWidth")
        if width > 390:
            overflowing.append((url, width))
    assert not overflowing, overflowing
