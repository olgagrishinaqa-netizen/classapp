"""Модели: нормализация телефона, пароли, вычисляемые свойства."""

from decimal import Decimal

import pytest

from app.models import (
    Expense,
    ExpenseReport,
    GeneralInfo,
    News,
    NewsImage,
    Payment,
    Student,
    User,
)


class TestNormalizePhone:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, ""),
            ("", ""),
            ("abc", ""),
            ("+375 (29) 000-00-00", "375290000000"),
            ("375 29 000 00 00", "375290000000"),
            ("8 (916) 123-45-67", "79161234567"),
            ("89161234567", "79161234567"),
            # Восьмёрка заменяется только у номера из 11 цифр.
            ("8123", "8123"),
            (375290000000, "375290000000"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert User.normalize_phone(raw) == expected

    def test_phone_is_normalized_on_assignment(self):
        user = User(full_name="Иван", phone="+375 (29) 111-22-33")
        assert user.phone == "375291112233"


class TestUserPassword:
    def test_password_is_hashed_and_checked(self):
        user = User(full_name="Иван", phone="375291112233")
        user.set_password("secret123")
        assert user.password_hash != "secret123"
        assert user.check_password("secret123") is True
        assert user.check_password("wrong") is False

    def test_empty_hash_behaves_like_wrong_password(self):
        user = User(full_name="Иван", phone="375291112233", password_hash="")
        assert user.check_password("anything") is False

    def test_broken_hash_behaves_like_wrong_password(self):
        user = User(
            full_name="Иван",
            phone="375291112233",
            password_hash="pbkdf2:no-such-algorithm$salt$digest",
        )
        assert user.check_password("anything") is False

    @pytest.mark.parametrize(("role", "expected"), [("admin", True), ("parent", False)])
    def test_is_admin(self, role, expected):
        assert User(role=role).is_admin is expected


class TestExpenseReport:
    def test_totals_and_balance(self):
        report = ExpenseReport(
            income=Decimal("1000"),
            expense_items=[{"title": "Бумага", "amount": 250}, {"title": "Мел", "amount": "100.5"}],
        )
        assert report.total_expenses == 350.5
        assert report.balance == 649.5

    def test_empty_items(self):
        report = ExpenseReport(income=Decimal("10"), expense_items=None)
        assert report.total_expenses == 0
        assert report.balance == 10

    def test_item_without_amount_counts_as_zero(self):
        report = ExpenseReport(income=Decimal("5"), expense_items=[{"title": "Без суммы"}])
        assert report.total_expenses == 0


class TestPayment:
    def test_payer_is_student_name(self):
        payment = Payment(
            amount=Decimal("1"), student=Student(last_name="Иванов", first_name="Пётр")
        )
        assert payment.payer_name == "Иванов Пётр"

    def test_payer_falls_back_to_legacy_user(self):
        payment = Payment(amount=Decimal("1"), user=User(full_name="Родитель Иванова"))
        assert payment.payer_name == "Родитель Иванова"

    def test_payer_unknown(self):
        assert Payment(amount=Decimal("1")).payer_name == "—"


class TestUrlProperties:
    def test_expense_receipt_url(self):
        assert (
            Expense(receipt_path="abc_check.png").receipt_url == "/uploads/receipts/abc_check.png"
        )

    def test_expense_without_receipt(self):
        assert Expense(receipt_path=None).receipt_url is None

    def test_general_info_file_url(self):
        assert GeneralInfo(file_path="abc_doc.pdf").file_url == "/uploads/abc_doc.pdf"
        assert GeneralInfo(file_path=None).file_url is None

    def test_news_cover_and_all_images(self):
        news = News(
            title="Новость",
            images=[NewsImage(path="a.png", position=0), NewsImage(path="b.png", position=1)],
        )
        assert news.image_url == "/uploads/a.png"
        assert news.image_urls == ["/uploads/a.png", "/uploads/b.png"]

    def test_news_without_images(self):
        news = News(title="Без картинок")
        assert news.image_url is None
        assert news.image_urls == []


def test_student_full_name():
    assert Student(last_name="Петрова", first_name="Анна").full_name == "Петрова Анна"
