"""Диалог подтверждения удаления (base.html): отмена, Esc и подтверждение."""

import re
from datetime import time

import pytest
from playwright.sync_api import expect

from app.models import BellScheduleEntry, GeneralInfo, News, ScheduleEntry, Student

pytestmark = pytest.mark.e2e


def dialog(page):
    return page.locator("#confirm-dialog")


@pytest.fixture()
def two_news(seed):
    def create(db):
        db.session.add_all(
            [
                News(title="Первая новость", description="д", status="published"),
                News(title="Вторая новость", description="д", status="published"),
            ]
        )

    seed(create)


def delete_button(page, title):
    return page.locator("article", has_text=title).get_by_role("button", name="Удалить")


class TestConfirmDialog:
    def test_dialog_is_closed_initially(self, admin_page, two_news):
        admin_page.goto("/news")
        expect(dialog(admin_page)).not_to_be_visible()

    def test_delete_button_opens_dialog_with_the_item_name(self, admin_page, two_news):
        admin_page.goto("/news")
        delete_button(admin_page, "Вторая новость").click()
        expect(dialog(admin_page)).to_be_visible()
        expect(admin_page.locator("#confirm-dialog-message")).to_have_text(
            "Удалить новость «Вторая новость»?"
        )
        # Пока нет подтверждения, запрос не отправляется.
        assert admin_page.url.endswith("/news")

    def test_cancel_keeps_the_item(self, admin_page, two_news):
        admin_page.goto("/news")
        delete_button(admin_page, "Первая новость").click()
        admin_page.locator("#confirm-dialog-cancel").click()
        expect(dialog(admin_page)).not_to_be_visible()
        expect(admin_page.get_by_role("heading", name="Первая новость")).to_be_visible()
        expect(admin_page.get_by_role("alert")).to_have_count(0)

    def test_escape_closes_without_deleting(self, admin_page, two_news):
        admin_page.goto("/news")
        delete_button(admin_page, "Первая новость").click()
        expect(dialog(admin_page)).to_be_visible()
        admin_page.keyboard.press("Escape")
        expect(dialog(admin_page)).not_to_be_visible()
        expect(admin_page.get_by_role("heading", name="Первая новость")).to_be_visible()

    def test_accept_deletes_only_the_chosen_item(self, admin_page, two_news):
        admin_page.goto("/news")
        delete_button(admin_page, "Вторая новость").click()
        admin_page.locator("#confirm-dialog-accept").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Новость удалена.")
        expect(admin_page.get_by_role("heading", name="Вторая новость")).to_have_count(0)
        expect(admin_page.get_by_role("heading", name="Первая новость")).to_be_visible()

    def test_cancelled_item_can_be_deleted_afterwards(self, admin_page, two_news):
        admin_page.goto("/news")
        delete_button(admin_page, "Первая новость").click()
        admin_page.locator("#confirm-dialog-cancel").click()
        delete_button(admin_page, "Первая новость").click()
        expect(admin_page.locator("#confirm-dialog-message")).to_contain_text("Первая новость")
        admin_page.locator("#confirm-dialog-accept").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Новость удалена.")
        expect(admin_page.get_by_role("heading", name="Первая новость")).to_have_count(0)

    def test_choosing_another_item_after_cancel_uses_its_own_message(self, admin_page, two_news):
        admin_page.goto("/news")
        delete_button(admin_page, "Первая новость").click()
        admin_page.locator("#confirm-dialog-cancel").click()
        delete_button(admin_page, "Вторая новость").click()
        expect(admin_page.locator("#confirm-dialog-message")).to_have_text(
            "Удалить новость «Вторая новость»?"
        )


class TestOtherPages:
    def test_delete_a_lesson(self, admin_page, seed):
        seed(
            lambda db: db.session.add(
                ScheduleEntry(day_of_week=0, lesson_number=1, subject="Химия")
            )
        )
        admin_page.goto("/schedule")
        admin_page.get_by_label("Удалить").click()
        expect(admin_page.locator("#confirm-dialog-message")).to_have_text("Удалить урок «Химия»?")
        admin_page.locator("#confirm-dialog-accept").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Урок удалён из расписания.")
        expect(admin_page.get_by_role("heading", name="Химия")).to_have_count(0)

    def test_delete_a_bell(self, admin_page, seed):
        seed(
            lambda db: db.session.add(
                BellScheduleEntry(lesson_number=4, start_time=time(11, 0), end_time=time(11, 45))
            )
        )
        admin_page.goto("/bell-schedule")
        admin_page.get_by_label("Удалить").click()
        expect(admin_page.locator("#confirm-dialog-message")).to_contain_text("№4")
        admin_page.locator("#confirm-dialog-accept").click()
        expect(admin_page.get_by_role("alert")).to_contain_text(
            "Строка расписания звонков удалена."
        )

    def test_delete_a_student(self, admin_page, seed):
        seed(lambda db: db.session.add(Student(last_name="Орлов", first_name="Иван")))
        admin_page.goto("/admin/students")
        admin_page.get_by_role("button", name="Удалить").click()
        expect(admin_page.locator("#confirm-dialog-message")).to_contain_text("Орлов Иван")
        admin_page.locator("#confirm-dialog-accept").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("удалён из состава класса")
        expect(admin_page.get_by_text("В классе пока нет учеников.")).to_be_visible()

    def test_delete_an_info_record(self, admin_page, seed):
        seed(lambda db: db.session.add(GeneralInfo(description="Правила класса")))
        admin_page.goto("/info")
        admin_page.get_by_role("button", name="Удалить").click()
        expect(admin_page.locator("#confirm-dialog-message")).to_have_text("Удалить эту запись?")
        admin_page.locator("#confirm-dialog-accept").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Запись удалена.")

    def test_delete_a_user(self, admin_page, seed):
        from app.models import User

        def create(db):
            user = User(full_name="Удаляемый Пользователь", phone="375297770001", role="parent")
            user.set_password("secret123")
            db.session.add(user)

        seed(create)
        admin_page.goto("/users")
        card = admin_page.locator("article", has_text="Удаляемый Пользователь")
        card.get_by_role("button", name=re.compile("Удалить")).click()
        expect(admin_page.locator("#confirm-dialog-message")).to_contain_text(
            "Удаляемый Пользователь"
        )
        admin_page.locator("#confirm-dialog-accept").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Пользователь удален.")
