"""Страница входа: маска телефона, показ пароля, вход и ошибки."""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

HIDDEN = re.compile(r"\bhidden\b")


def phone_input(page):
    return page.locator("#phone-input")


def paste(page, text):
    """Имитирует вставку текста в поле телефона (событие beforeinput/insertFromPaste)."""
    page.evaluate(
        """(text) => {
            const input = document.getElementById('phone-input');
            input.dispatchEvent(new InputEvent('beforeinput', {
                inputType: 'insertFromPaste', data: text, bubbles: true, cancelable: true,
            }));
        }""",
        text,
    )


class TestPhoneMask:
    def test_starts_with_fixed_country_code(self, page):
        page.goto("/login")
        expect(phone_input(page)).to_have_value("+375")

    @pytest.mark.parametrize(
        ("typed", "shown"),
        [
            ("2", "+375 (2"),
            ("29", "+375 (29)"),
            ("291", "+375 (29) 1"),
            ("29123", "+375 (29) 123"),
            ("291234", "+375 (29) 123-4"),
            ("2912345", "+375 (29) 123-45"),
            ("29123456", "+375 (29) 123-45-6"),
            ("291234567", "+375 (29) 123-45-67"),
        ],
    )
    def test_number_is_formatted_while_typing(self, page, typed, shown):
        page.goto("/login")
        phone_input(page).press_sequentially(typed)
        expect(phone_input(page)).to_have_value(shown)

    def test_extra_digits_are_ignored(self, page):
        page.goto("/login")
        phone_input(page).press_sequentially("29123456799999")
        expect(phone_input(page)).to_have_value("+375 (29) 123-45-67")

    def test_letters_and_symbols_are_ignored(self, page):
        page.goto("/login")
        phone_input(page).press_sequentially("2a9-b1")
        expect(phone_input(page)).to_have_value("+375 (29) 1")

    def test_backspace_removes_the_last_digit(self, page):
        page.goto("/login")
        phone_input(page).press_sequentially("2912")
        phone_input(page).press("Backspace")
        expect(phone_input(page)).to_have_value("+375 (29) 1")
        for _ in range(3):
            phone_input(page).press("Backspace")
        expect(phone_input(page)).to_have_value("+375")

    def test_country_code_cannot_be_deleted(self, page):
        page.goto("/login")
        for _ in range(5):
            phone_input(page).press("Backspace")
        expect(phone_input(page)).to_have_value("+375")

    def test_pasted_number_with_country_code_replaces_everything(self, page):
        page.goto("/login")
        phone_input(page).press_sequentially("11")
        phone_input(page).press("Control+A")
        paste(page, "+375 29 123-45-67")
        expect(phone_input(page)).to_have_value("+375 (29) 123-45-67")

    def test_pasted_number_starting_with_eight_zero(self, page):
        page.goto("/login")
        phone_input(page).press("Control+A")
        paste(page, "8 029 123 45 67")
        expect(phone_input(page)).to_have_value("+375 (29) 123-45-67")

    def test_restores_the_value_after_a_failed_login(self, page, login):
        login("291234567", "wrong-password")
        expect(page.get_by_role("alert")).to_contain_text("Неверный номер телефона или пароль.")
        expect(phone_input(page)).to_have_value("+375 (29) 123-45-67")


class TestPasswordToggle:
    def test_password_is_hidden_by_default(self, page):
        page.goto("/login")
        expect(page.locator("#password-input")).to_have_attribute("type", "password")
        expect(page.locator("#password-toggle")).to_have_attribute("aria-pressed", "false")
        expect(page.locator("#password-toggle")).to_have_attribute("aria-label", "Показать пароль")

    def test_toggle_reveals_and_hides_the_password(self, page):
        page.goto("/login")
        page.locator("#password-input").fill("секрет")
        page.locator("#password-toggle").click()
        expect(page.locator("#password-input")).to_have_attribute("type", "text")
        expect(page.locator("#password-input")).to_have_value("секрет")
        expect(page.locator("#password-toggle")).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#password-toggle")).to_have_attribute("aria-label", "Скрыть пароль")
        expect(page.locator("#password-toggle-icon-show")).to_have_class(HIDDEN)
        expect(page.locator("#password-toggle-icon-hide")).not_to_have_class(HIDDEN)

        page.locator("#password-toggle").click()
        expect(page.locator("#password-input")).to_have_attribute("type", "password")
        expect(page.locator("#password-toggle")).to_have_attribute("aria-pressed", "false")
        expect(page.locator("#password-toggle-icon-hide")).to_have_class(HIDDEN)


class TestLogin:
    def test_admin_logs_in_and_sees_the_dashboard(self, page, login):
        login()
        page.wait_for_url("**/dashboard")
        expect(page.get_by_role("heading", level=1)).to_have_text("Администратор")
        expect(page.get_by_role("navigation", name="Основная навигация")).to_be_visible()

    def test_wrong_password_stays_on_the_login_page(self, page, login):
        login(password="nope")
        expect(page.get_by_role("alert")).to_contain_text("Неверный номер телефона или пароль.")
        assert page.url.endswith("/login")

    def test_empty_form_does_not_log_in(self, page):
        page.goto("/login")
        page.get_by_role("button", name="Войти").click()
        assert page.url.endswith("/login")

    def test_logged_in_user_is_redirected_from_the_login_page(self, admin_page):
        admin_page.goto("/login")
        admin_page.wait_for_url("**/tasks")

    def test_protected_page_redirects_anonymous_visitors(self, page):
        page.goto("/users")
        page.wait_for_url("**/login")
