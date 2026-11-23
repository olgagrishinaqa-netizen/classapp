"""Сквозные сценарии: регистрация, выход, смена роли, тема, навигация."""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

DARK = re.compile(r"\bdark\b")


class TestRegistration:
    def test_new_parent_registers_and_logs_in(self, page, login):
        page.goto("/register")
        page.get_by_label("Имя и фамилия").fill("Мария Новикова")
        page.get_by_label("Номер телефона").fill("375447000001")
        page.get_by_label("Пароль", exact=True).fill("secret123")
        page.get_by_label("Повторите пароль").fill("secret123")
        page.get_by_role("button", name="Создать аккаунт").click()

        page.wait_for_url("**/login")
        expect(page.get_by_role("alert")).to_contain_text(
            "Аккаунт создан. Теперь войдите в приложение."
        )

        login("447000001", "secret123")
        page.wait_for_url("**/dashboard")
        expect(page.get_by_role("heading", level=1)).to_have_text("Мария Новикова")
        expect(page.get_by_text("Родитель", exact=True)).to_be_visible()
        nav = page.get_by_role("navigation", name="Основная навигация")
        expect(nav.get_by_role("link")).to_have_count(4)
        expect(nav.get_by_role("link", name="Класс")).to_have_count(0)

    def test_password_mismatch_shows_an_error(self, page):
        page.goto("/register")
        page.get_by_label("Имя и фамилия").fill("Иван")
        page.get_by_label("Номер телефона").fill("375447000002")
        page.get_by_label("Пароль", exact=True).fill("secret123")
        page.get_by_label("Повторите пароль").fill("другой-пароль")
        page.get_by_role("button", name="Создать аккаунт").click()
        expect(page.get_by_text("Пароли должны совпадать")).to_be_visible()
        assert page.url.endswith("/register")

    def test_taken_phone_shows_an_error(self, page):
        page.goto("/register")
        page.get_by_label("Имя и фамилия").fill("Двойник")
        page.get_by_label("Номер телефона").fill("375290000000")
        page.get_by_label("Пароль", exact=True).fill("secret123")
        page.get_by_label("Повторите пароль").fill("secret123")
        page.get_by_role("button", name="Создать аккаунт").click()
        expect(page.get_by_text("Этот номер телефона уже зарегистрирован.")).to_be_visible()


class TestLogout:
    def test_logout_returns_to_login_and_closes_access(self, admin_page):
        admin_page.goto("/profile")
        admin_page.get_by_role("button", name="Выйти из аккаунта").click()
        admin_page.wait_for_url("**/login")
        expect(admin_page.get_by_role("alert")).to_contain_text("Вы вышли из аккаунта.")
        admin_page.goto("/dashboard")
        admin_page.wait_for_url("**/login")


class TestNavigation:
    def test_admin_navigation_leads_to_each_section(self, admin_page):
        nav = admin_page.get_by_role("navigation", name="Основная навигация")
        expect(nav.get_by_role("link")).to_have_count(5)
        for label, path in [
            ("Квесты", "/tasks"),
            ("Баланс", "/expenses"),
            ("Класс", "/admin/students"),
            ("Профиль", "/profile"),
            ("Хаб", "/dashboard"),
        ]:
            nav.get_by_role("link", name=label).click()
            admin_page.wait_for_url(f"**{path}")
            expect(nav.get_by_role("link", name=label)).to_have_class(re.compile("text-cyan-700"))

    def test_dashboard_cards_open_sections(self, admin_page):
        admin_page.get_by_role(
            "link", name=re.compile("Расписание уроков|Расписание")
        ).first.click()
        admin_page.wait_for_url(re.compile(r".*/(schedule|bell-schedule)$"))


class TestRoleSwitching:
    def test_admin_can_preview_the_parent_interface(self, admin_page):
        admin_page.goto("/news")
        expect(admin_page.locator("form#news-form")).to_be_visible()

        admin_page.goto("/profile")
        admin_page.locator("select[name=role]").select_option(label="Родитель")
        admin_page.get_by_role("button", name="Применить").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Включен режим: Родитель.")

        admin_page.goto("/news")
        expect(admin_page.locator("form#news-form")).to_have_count(0)
        admin_page.goto("/users")
        expect(admin_page.get_by_role("alert")).to_contain_text(
            "Доступ к пользователям разрешен только администратору."
        )

        admin_page.goto("/profile")
        admin_page.locator("select[name=role]").select_option(label="Администратор")
        admin_page.get_by_role("button", name="Применить").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Включен режим: Админ.")
        admin_page.goto("/news")
        expect(admin_page.locator("form#news-form")).to_be_visible()


class TestTheme:
    def test_light_theme_is_the_default(self, page):
        page.goto("/login")
        expect(page.locator("html")).not_to_have_class(DARK)

    def test_system_dark_preference_does_not_force_dark_theme(self, page):
        page.emulate_media(color_scheme="dark")
        page.goto("/login")
        expect(page.locator("html")).not_to_have_class(DARK)

    def test_dark_theme_is_chosen_applied_and_remembered(self, admin_page):
        admin_page.goto("/profile")
        light, dark = admin_page.locator("#theme-choice-light"), admin_page.locator(
            "#theme-choice-dark"
        )
        expect(light).to_have_attribute("aria-checked", "true")
        expect(dark).to_have_attribute("aria-checked", "false")

        dark.click()
        expect(admin_page.locator("html")).to_have_class(DARK)
        expect(dark).to_have_attribute("aria-checked", "true")
        expect(light).to_have_attribute("aria-checked", "false")
        assert admin_page.evaluate("localStorage.theme") == "dark"

        admin_page.reload()
        expect(admin_page.locator("html")).to_have_class(DARK)
        expect(admin_page.locator("#theme-choice-dark")).to_have_attribute("aria-checked", "true")

        admin_page.goto("/tasks")
        expect(admin_page.locator("html")).to_have_class(DARK)

    def test_switching_back_to_light_removes_the_dark_class(self, admin_page):
        admin_page.goto("/profile")
        admin_page.locator("#theme-choice-dark").click()
        admin_page.locator("#theme-choice-light").click()
        expect(admin_page.locator("html")).not_to_have_class(DARK)
        assert admin_page.evaluate("localStorage.theme") == "light"

    def test_theme_is_applied_before_first_paint(self, admin_page):
        admin_page.goto("/profile")
        admin_page.locator("#theme-choice-dark").click()
        admin_page.goto("/dashboard", wait_until="commit")
        # Класс ставится встроенным скриптом из <head>, ещё до подключения Tailwind.
        admin_page.wait_for_selector("html.dark", state="attached")
