"""Состав класса (только администратор): список, поиск, добавление, правка, удаление."""

from datetime import date

import pytest

from app.models import Payment, Student


def text(response):
    return response.get_data(as_text=True)


def location(response):
    return response.headers["Location"]


@pytest.fixture()
def clean_students(wipe):
    wipe(Payment, Student)


def add_student(db, last="Иванов", first="Пётр", birth=None):
    student = Student(last_name=last, first_name=first, birth_date=birth)
    db.session.add(student)
    db.session.commit()
    return student


class TestStudentsPageAccess:
    def test_requires_login(self, client):
        response = client.get("/admin/students")
        assert response.status_code == 302
        assert location(response).endswith("/login")

    def test_parent_is_sent_away(self, parent_client):
        response = parent_client.get("/admin/students", follow_redirects=True)
        assert "Доступ к разделу «Состав класса» разрешён только администратору." in text(response)

    def test_admin_sees_the_list_and_form(self, admin_client, db, clean_students):
        add_student(db, "Сидоров", "Олег", date(2015, 5, 20))
        page = text(admin_client.get("/admin/students"))
        assert "Сидоров Олег" in page or ("Сидоров" in page and "Олег" in page)
        assert 'name="last_name"' in page
        assert "2015-05-20" in page


class TestStudentsSearch:
    @pytest.fixture(autouse=True)
    def _students(self, db, clean_students):
        add_student(db, "Иванов", "Пётр")
        add_student(db, "Иванова", "Мария")
        add_student(db, "Смирнов", "Пётр")

    def test_search_by_last_name(self, admin_client):
        page = text(admin_client.get("/admin/students?search=Иван"))
        assert "Иванов" in page and "Иванова" in page
        assert "Смирнов" not in page

    def test_search_by_first_name(self, admin_client):
        page = text(admin_client.get("/admin/students?search=Мария"))
        assert "Иванова" in page
        assert "Смирнов" not in page

    def test_every_word_must_match(self, admin_client):
        page = text(admin_client.get("/admin/students?search=Иванов Пётр"))
        assert "Иванов" in page
        assert "Смирнов" not in page
        assert "Мария" not in page

    def test_blank_search_shows_everyone(self, admin_client):
        page = text(admin_client.get("/admin/students?search=%20%20"))
        assert "Смирнов" in page and "Иванов" in page

    def test_search_without_results(self, admin_client):
        page = text(admin_client.get("/admin/students?search=Неттакого"))
        assert "Смирнов" not in page and "Иванов" not in page

    def test_students_are_sorted_by_name(self, admin_client):
        page = text(admin_client.get("/admin/students"))
        assert page.index("Иванов") < page.index("Смирнов")


class TestAddStudent:
    def test_admin_adds_a_student(self, admin_client, clean_students):
        response = admin_client.post(
            "/admin/students",
            data={"last_name": " Орлов ", "first_name": " Иван ", "birth_date": "2014-09-01"},
        )
        assert response.status_code == 302
        student = Student.query.one()
        assert (student.last_name, student.first_name) == ("Орлов", "Иван")
        assert student.birth_date == date(2014, 9, 1)
        followed = admin_client.get("/admin/students")
        assert "добавлен в состав класса" in text(followed)

    def test_birth_date_is_optional(self, admin_client, clean_students):
        admin_client.post("/admin/students", data={"last_name": "Без", "first_name": "Даты"})
        assert Student.query.one().birth_date is None

    def test_duplicate_is_rejected(self, admin_client, db, clean_students):
        add_student(db, "Орлов", "Иван")
        response = admin_client.post(
            "/admin/students", data={"last_name": "Орлов", "first_name": "Иван"}
        )
        assert response.status_code == 200
        assert "уже есть в списке класса." in text(response)
        assert Student.query.count() == 1

    @pytest.mark.parametrize(
        "data",
        [
            {"last_name": "", "first_name": "Иван"},
            {"last_name": "Орлов", "first_name": ""},
            {"last_name": "О" * 65, "first_name": "Иван"},
            {"last_name": "Орлов", "first_name": "Иван", "birth_date": "не дата"},
        ],
    )
    def test_invalid_form_is_rejected(self, admin_client, clean_students, data):
        response = admin_client.post("/admin/students", data=data)
        assert response.status_code == 200
        assert "Проверьте правильность заполнения формы." in text(response)
        assert Student.query.count() == 0

    def test_parent_cannot_add(self, parent_client, clean_students):
        response = parent_client.post(
            "/admin/students", data={"last_name": "Орлов", "first_name": "Иван"}
        )
        assert response.status_code == 302
        assert Student.query.count() == 0


class TestEditStudent:
    def test_parent_cannot_edit(self, parent_client, db, clean_students):
        student = add_student(db)
        response = parent_client.post(
            f"/admin/students/{student.id}/edit",
            data={"last_name": "Взлом", "first_name": "Хакер"},
            follow_redirects=True,
        )
        assert "Редактировать состав класса может только администратор." in text(response)
        db.session.refresh(student)
        assert student.last_name == "Иванов"

    def test_missing_student(self, admin_client, clean_students):
        response = admin_client.post(
            "/admin/students/999999/edit",
            data={"last_name": "А", "first_name": "Б"},
            follow_redirects=True,
        )
        assert "Ученик не найден." in text(response)

    def test_invalid_form(self, admin_client, db, clean_students):
        student = add_student(db)
        response = admin_client.post(
            f"/admin/students/{student.id}/edit",
            data={"last_name": "", "first_name": "Пётр"},
            follow_redirects=True,
        )
        assert "Проверьте правильность заполнения формы." in text(response)
        db.session.refresh(student)
        assert student.last_name == "Иванов"

    def test_search_is_preserved_after_edit(self, admin_client, db, clean_students):
        student = add_student(db)
        response = admin_client.post(
            f"/admin/students/{student.id}/edit?search=Иван",
            data={"last_name": "Иванов", "first_name": "Павел"},
        )
        assert response.status_code == 302
        assert "search=" in location(response)

    def test_search_from_form_field_is_preserved(self, admin_client, db, clean_students):
        student = add_student(db)
        response = admin_client.post(
            f"/admin/students/{student.id}/edit",
            data={"last_name": "Иванов", "first_name": "Павел", "search": "Пав"},
        )
        assert "search=" in location(response)

    def test_success_message(self, admin_client, db, clean_students):
        student = add_student(db)
        response = admin_client.post(
            f"/admin/students/{student.id}/edit",
            data={"last_name": "Иванов", "first_name": "Павел"},
            follow_redirects=True,
        )
        assert "обновлены" in text(response)


class TestDeleteStudent:
    def test_parent_cannot_delete(self, parent_client, db, clean_students):
        student = add_student(db)
        response = parent_client.post(f"/admin/students/{student.id}/delete", follow_redirects=True)
        assert "Удалять учеников может только администратор." in text(response)
        assert Student.query.count() == 1

    def test_missing_student(self, admin_client, clean_students):
        response = admin_client.post("/admin/students/999999/delete", follow_redirects=True)
        assert "Ученик не найден." in text(response)

    def test_admin_deletes_a_student(self, admin_client, db, clean_students):
        student = add_student(db)
        response = admin_client.post(f"/admin/students/{student.id}/delete", follow_redirects=True)
        assert "удалён из состава класса" in text(response)
        assert Student.query.count() == 0

    def test_search_is_preserved_after_delete(self, admin_client, db, clean_students):
        student = add_student(db)
        response = admin_client.post(f"/admin/students/{student.id}/delete?search=Иван")
        assert "search=" in location(response)

    def test_delete_requires_post(self, admin_client, db, clean_students):
        student = add_student(db)
        assert admin_client.get(f"/admin/students/{student.id}/delete").status_code == 405
