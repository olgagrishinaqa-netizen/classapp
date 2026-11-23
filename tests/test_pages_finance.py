"""Взносы и расходы класса: страница /expenses и формы редактирования."""

import io
from decimal import Decimal

import pytest

from app.models import Expense, Payment, Student


def text(response):
    return response.get_data(as_text=True)


def location(response):
    return response.headers["Location"]


def receipt(name="check.png", content=b"\x89PNG-fake"):
    return (io.BytesIO(content), name)


@pytest.fixture()
def clean_finance(wipe):
    wipe(Payment, Expense, Student)


@pytest.fixture()
def student(db, clean_finance):
    row = Student(last_name="Взносов", first_name="Стёпа")
    db.session.add(row)
    db.session.commit()
    return row


def add_expense(db, title="Мел", amount="150.00", category="Общие", receipt_path=None):
    row = Expense(title=title, amount=Decimal(amount), category=category, receipt_path=receipt_path)
    db.session.add(row)
    db.session.commit()
    return row


def add_payment(db, student, amount="500.00"):
    row = Payment(student_id=student.id, amount=Decimal(amount))
    db.session.add(row)
    db.session.commit()
    return row


class TestExpensesPage:
    def test_requires_login(self, client):
        response = client.get("/expenses")
        assert response.status_code == 302
        assert location(response).endswith("/login")

    def test_parent_sees_figures_but_no_forms(self, parent_client, db, student):
        add_payment(db, student, "1000.00")
        add_expense(db, "Тетради", "250.00")
        page = text(parent_client.get("/expenses"))
        assert "Тетради" in page
        assert "Взносов Стёпа" in page
        assert "750.00" in page
        assert 'id="expense-dialog"' not in page

    def test_admin_sees_the_forms(self, admin_client, clean_finance):
        page = text(admin_client.get("/expenses"))
        assert 'id="expense-dialog"' in page
        assert 'id="payment-dialog"' in page

    def test_balance_is_deposits_minus_expenses(self, admin_client, db, student):
        add_payment(db, student, "300.00")
        add_payment(db, student, "200.00")
        add_expense(db, amount="120.50")
        page = text(admin_client.get("/expenses"))
        assert "379.50" in page

    def test_balance_can_be_negative(self, admin_client, db, clean_finance):
        add_expense(db, amount="80.00")
        assert "-80.00" in text(admin_client.get("/expenses"))

    def test_empty_page_renders(self, admin_client, clean_finance):
        assert admin_client.get("/expenses").status_code == 200


class TestAddPayment:
    def _pay(self, client, **data):
        payload = {"action": "add_payment"}
        payload.update(data)
        return client.post("/expenses", data=payload)

    def test_admin_records_a_payment(self, admin_client, student):
        response = self._pay(admin_client, student_id=student.id, amount="1000.00")
        assert response.status_code == 302
        payment = Payment.query.one()
        assert payment.student_id == student.id
        assert payment.amount == Decimal("1000.00")
        assert "Взнос успешно зафиксирован." in text(admin_client.get("/expenses"))

    @pytest.mark.parametrize(("raw", "expected"), [("100,50", "100.50"), (" 1 250,5 ", "1250.50")])
    def test_comma_decimal_separator_is_accepted(self, admin_client, student, raw, expected):
        self._pay(admin_client, student_id=student.id, amount=raw)
        assert Payment.query.one().amount == Decimal(expected)

    @pytest.mark.parametrize("amount", ["0", "-5", "abc", "", "0,001"])
    def test_invalid_amount_is_rejected(self, admin_client, student, amount):
        response = self._pay(admin_client, student_id=student.id, amount=amount)
        assert response.status_code == 200
        assert "Взнос не сохранён: проверьте поля формы." in text(response)
        assert Payment.query.count() == 0

    def test_unknown_student_is_rejected(self, admin_client, student):
        response = self._pay(admin_client, student_id=999999, amount="10")
        assert "Взнос не сохранён: проверьте поля формы." in text(response)
        assert Payment.query.count() == 0

    def test_class_must_have_students(self, admin_client, clean_finance):
        response = self._pay(admin_client, student_id=1, amount="10")
        assert "Сначала добавьте учеников в состав класса." in text(response)
        assert Payment.query.count() == 0

    def test_parent_cannot_record_payments(self, parent_client, student):
        response = parent_client.post(
            "/expenses", data={"action": "add_payment", "student_id": student.id, "amount": "10"}
        )
        assert "Добавлять взносы и расходы может только администратор." in text(response)
        assert Payment.query.count() == 0


class TestAddExpense:
    def _spend(self, client, **data):
        payload = {"action": "add_expense", "title": "Маркеры", "amount": "125.50"}
        payload.update(data)
        return client.post("/expenses", data=payload, content_type="multipart/form-data")

    def test_admin_adds_an_expense(self, admin_client, clean_finance):
        response = self._spend(admin_client, category="Канцтовары")
        assert response.status_code == 302
        expense = Expense.query.one()
        assert (expense.title, expense.amount, expense.category) == (
            "Маркеры",
            Decimal("125.50"),
            "Канцтовары",
        )
        assert expense.receipt_path is None
        assert "Расход успешно добавлен." in text(admin_client.get("/expenses"))

    def test_empty_category_defaults_to_general(self, admin_client, clean_finance):
        self._spend(admin_client, category="")
        assert Expense.query.one().category == "Общие"

    def test_receipt_is_stored_in_receipts_folder(self, admin_client, upload_dir, clean_finance):
        response = self._spend(admin_client, receipt=receipt("чек.png"))
        assert response.status_code == 302
        expense = Expense.query.one()
        assert (upload_dir / "receipts" / expense.receipt_path).exists()
        assert expense.receipt_url == f"/uploads/receipts/{expense.receipt_path}"

    def test_pdf_receipt_is_allowed(self, admin_client, upload_dir, clean_finance):
        assert self._spend(admin_client, receipt=receipt("check.pdf")).status_code == 302

    def test_wrong_receipt_type_is_rejected(self, admin_client, upload_dir, clean_finance):
        response = self._spend(admin_client, receipt=receipt("virus.exe"))
        assert response.status_code == 200
        assert "Расход не сохранён: проверьте поля формы." in text(response)
        assert Expense.query.count() == 0
        assert not (upload_dir / "receipts").exists()

    @pytest.mark.parametrize(
        "overrides", [{"title": ""}, {"amount": "0"}, {"amount": "-1"}, {"amount": "abc"}]
    )
    def test_invalid_expense_is_rejected(self, admin_client, clean_finance, overrides):
        response = self._spend(admin_client, **overrides)
        assert response.status_code == 200
        assert "Расход не сохранён: проверьте поля формы." in text(response)
        assert Expense.query.count() == 0

    def test_unknown_action(self, admin_client, clean_finance):
        response = admin_client.post("/expenses", data={"action": "steal"})
        assert "Неизвестное действие." in text(response)

    def test_missing_action(self, admin_client, clean_finance):
        assert "Неизвестное действие." in text(admin_client.post("/expenses", data={}))

    def test_parent_cannot_add(self, parent_client, clean_finance):
        response = self._spend(parent_client)
        assert "Добавлять взносы и расходы может только администратор." in text(response)
        assert Expense.query.count() == 0

    def test_failed_form_reopens_the_dialog(self, admin_client, clean_finance):
        page = text(self._spend(admin_client, title=""))
        assert "getElementById('expense-dialog').showModal()" in page


class TestEditExpense:
    def test_requires_login(self, client, db, clean_finance):
        expense = add_expense(db)
        response = client.get(f"/expenses/edit/{expense.id}")
        assert response.status_code == 302
        assert location(response).endswith("/login")

    def test_parent_cannot_edit(self, parent_client, db, clean_finance):
        expense = add_expense(db)
        response = parent_client.get(f"/expenses/edit/{expense.id}", follow_redirects=True)
        assert "Редактировать расходы может только администратор." in text(response)

    def test_missing_expense(self, admin_client, clean_finance):
        response = admin_client.get("/expenses/edit/999999", follow_redirects=True)
        assert "Расход не найден." in text(response)

    def test_form_is_prefilled(self, admin_client, db, clean_finance):
        expense = add_expense(db, "Редактируемый расход")
        assert "Редактируемый расход" in text(admin_client.get(f"/expenses/edit/{expense.id}"))

    def test_admin_updates_an_expense(self, admin_client, db, clean_finance):
        expense = add_expense(db, "Было", "10.00", "Старая")
        response = admin_client.post(
            f"/expenses/edit/{expense.id}",
            data={"title": " Стало ", "amount": "20,25", "category": ""},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert "Расход обновлен." in text(response)
        db.session.refresh(expense)
        assert (expense.title, expense.amount, expense.category) == (
            "Стало",
            Decimal("20.25"),
            "Общие",
        )

    def test_admin_attaches_a_receipt(self, admin_client, db, upload_dir, clean_finance):
        expense = add_expense(db)
        admin_client.post(
            f"/expenses/edit/{expense.id}",
            data={"title": "Т", "amount": "5", "receipt": receipt("new.png")},
            content_type="multipart/form-data",
        )
        db.session.refresh(expense)
        assert expense.receipt_path
        assert (upload_dir / "receipts" / expense.receipt_path).exists()

    def test_update_without_receipt_keeps_the_old_one(self, admin_client, db, clean_finance):
        expense = add_expense(db, receipt_path="keep.png")
        admin_client.post(
            f"/expenses/edit/{expense.id}",
            data={"title": "Т", "amount": "5"},
            content_type="multipart/form-data",
        )
        db.session.refresh(expense)
        assert expense.receipt_path == "keep.png"

    def test_invalid_amount_keeps_the_record(self, admin_client, db, clean_finance):
        expense = add_expense(db, "Без изменений")
        response = admin_client.post(
            f"/expenses/edit/{expense.id}", data={"title": "Изменено", "amount": "0"}
        )
        assert response.status_code == 200
        db.session.refresh(expense)
        assert expense.title == "Без изменений"


class TestEditPayment:
    def test_requires_login(self, client, db, student):
        payment = add_payment(db, student)
        response = client.get(f"/payments/edit/{payment.id}")
        assert response.status_code == 302
        assert location(response).endswith("/login")

    def test_parent_cannot_edit(self, parent_client, db, student):
        payment = add_payment(db, student)
        response = parent_client.get(f"/payments/edit/{payment.id}", follow_redirects=True)
        assert "Редактировать взносы может только администратор." in text(response)

    def test_missing_payment(self, admin_client, clean_finance):
        response = admin_client.get("/payments/edit/999999", follow_redirects=True)
        assert "Взнос не найден." in text(response)

    def test_form_lists_the_class_roster(self, admin_client, db, student):
        payment = add_payment(db, student)
        assert "Взносов Стёпа" in text(admin_client.get(f"/payments/edit/{payment.id}"))

    def test_admin_updates_a_payment(self, admin_client, db, student):
        other = Student(last_name="Другой", first_name="Ученик")
        db.session.add(other)
        db.session.commit()
        payment = add_payment(db, student, "100.00")
        response = admin_client.post(
            f"/payments/edit/{payment.id}",
            data={"student_id": other.id, "amount": "250,75"},
            follow_redirects=True,
        )
        assert "Взнос обновлен." in text(response)
        db.session.refresh(payment)
        assert payment.student_id == other.id
        assert payment.amount == Decimal("250.75")

    @pytest.mark.parametrize("amount", ["0", "abc", "-3"])
    def test_invalid_amount_keeps_the_record(self, admin_client, db, student, amount):
        payment = add_payment(db, student, "100.00")
        response = admin_client.post(
            f"/payments/edit/{payment.id}", data={"student_id": student.id, "amount": amount}
        )
        assert response.status_code == 200
        db.session.refresh(payment)
        assert payment.amount == Decimal("100.00")

    def test_unknown_student_keeps_the_record(self, admin_client, db, student):
        payment = add_payment(db, student)
        response = admin_client.post(
            f"/payments/edit/{payment.id}", data={"student_id": 999999, "amount": "10"}
        )
        assert response.status_code == 200
        db.session.refresh(payment)
        assert payment.student_id == student.id
