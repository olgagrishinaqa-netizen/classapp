"""Ветки, где сохранение файла вернуло ошибку, и декоратор admin_required_page.

FileAllowed в формах отсекает неподходящие расширения раньше, поэтому ошибка от
_save_uploaded_file (например, нерабочее имя файла) подменяется напрямую."""

import io

import pytest
from _credentials import ADMIN_PHONE

from app import routes
from app.models import Expense, GeneralInfo


def text(response):
    return response.get_data(as_text=True)


@pytest.fixture()
def failing_save(monkeypatch):
    monkeypatch.setattr(
        routes, "_save_uploaded_file", lambda *args, **kwargs: (None, "Файл не удалось сохранить.")
    )


def upload(name="doc.pdf"):
    return (io.BytesIO(b"%PDF"), name)


def test_new_info_with_unsavable_file_is_not_created(admin_client, failing_save, wipe):
    wipe(GeneralInfo)
    response = admin_client.post(
        "/info",
        data={"description": "Описание", "file": upload()},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert "Файл не удалось сохранить." in text(response)
    assert GeneralInfo.query.count() == 0


def test_edited_info_with_unsavable_file_keeps_old_data(admin_client, failing_save, db, wipe):
    wipe(GeneralInfo)
    item = GeneralInfo(description="Старое", file_name="old.pdf", file_path="old_stored.pdf")
    db.session.add(item)
    db.session.commit()
    response = admin_client.post(
        f"/info/{item.id}/edit",
        data={"description": "Новое", "file": upload()},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert "Файл не удалось сохранить." in text(response)
    db.session.refresh(item)
    assert (item.description, item.file_path) == ("Старое", "old_stored.pdf")


def test_new_expense_with_unsavable_receipt_is_not_created(admin_client, failing_save, wipe):
    wipe(Expense)
    response = admin_client.post(
        "/expenses",
        data={
            "action": "add_expense",
            "title": "Маркеры",
            "amount": "10",
            "receipt": upload("c.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert "Файл не удалось сохранить." in text(response)
    assert Expense.query.count() == 0


def test_edited_expense_with_unsavable_receipt_keeps_old_data(admin_client, failing_save, db, wipe):
    wipe(Expense)
    expense = Expense(title="Было", amount=5, category="Общие", receipt_path="keep.png")
    db.session.add(expense)
    db.session.commit()
    response = admin_client.post(
        f"/expenses/edit/{expense.id}",
        data={"title": "Стало", "amount": "9", "receipt": upload("c.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert "Файл не удалось сохранить." in text(response)
    db.session.refresh(expense)
    assert (expense.title, expense.receipt_path) == ("Было", "keep.png")


class TestAdminRequiredPage:
    """Декоратор для HTML-страниц, доступных только администратору."""

    @staticmethod
    def _protected():
        @routes.admin_required_page
        def view():
            return "секретная страница"

        return view

    def test_anonymous_is_sent_to_login(self, app):
        with app.test_request_context("/x"):
            response = self._protected()()
        assert response.status_code == 302
        assert response.location.endswith("/login")

    def test_parent_is_sent_to_dashboard(self, app, make_user):
        user = make_user(role="parent")
        with app.test_request_context("/x"):
            from flask import session

            session["user_id"] = user.id
            response = self._protected()()
        assert response.status_code == 302
        assert response.location.endswith("/dashboard")

    def test_admin_gets_the_view(self, app):
        from app.models import User

        admin = User.query.filter_by(phone=ADMIN_PHONE).one()
        with app.test_request_context("/x"):
            from flask import session

            session["user_id"] = admin.id
            assert self._protected()() == "секретная страница"
