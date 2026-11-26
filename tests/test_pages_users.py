"""Управление пользователями (только администратор): список, создание,
редактирование, удаление и смена роли."""

import pytest

from app.models import Payment, Student, User


def text(response):
    return response.get_data(as_text=True)


def location(response):
    return response.headers["Location"]


def user_form(**overrides):
    data = {
        "action": "create_user",
        "last_name": "Петров",
        "first_name": "Пётр",
        "middle_name": "Петрович",
        "phone": "+375 (29) 700-99-99",
        "role": "parent",
        "password": "secret123",
    }
    data.update(overrides)
    return data


@pytest.fixture()
def second_admin(app, make_user, login_as):
    """Второй администратор и клиент, вошедший под ним."""
    user = make_user(role="admin")
    client = app.test_client()
    login_as(client, user.phone, user.plain_password)
    return user, client


class TestUsersListAccess:
    def test_requires_login(self, client):
        response = client.get("/users")
        assert response.status_code == 302
        assert location(response).endswith("/login")

    def test_parent_is_sent_to_dashboard(self, parent_client):
        response = parent_client.get("/users", follow_redirects=True)
        assert "Доступ к пользователям разрешен только администратору." in text(response)

    def test_admin_sees_the_list(self, admin_client, make_user):
        parent = make_user(role="parent", full_name="Список Родитель")
        page = text(admin_client.get("/users"))
        assert "Список Родитель" in page
        assert "Администратор" in page
        assert parent.phone  # телефон существует, но в списке может быть отформатирован

    def test_admin_is_listed_first(self, admin_client, make_user):
        make_user(role="parent", full_name="Яяя Последний")
        page = text(admin_client.get("/users"))
        assert page.index("Администратор") < page.index("Яяя Последний")

    def test_role_filter(self, admin_client, make_user):
        make_user(role="parent", full_name="Фильтр Родитель")
        make_user(role="student", full_name="Фильтр Ученик")
        parents = text(admin_client.get("/users?role_filter=parent"))
        students = text(admin_client.get("/users?role_filter=student"))
        # Имена родителей есть и в выпадающем списке формы, поэтому ищем карточку пользователя.
        parent_card, student_card = ">Фильтр Родитель</h2>", ">Фильтр Ученик</h2>"
        assert parent_card in parents and student_card not in parents
        assert student_card in students and parent_card not in students

    def test_unknown_role_filter_shows_everyone(self, admin_client, make_user):
        make_user(role="parent", full_name="Без Фильтра")
        assert "Без Фильтра" in text(admin_client.get("/users?role_filter=hacker"))


class TestCreateUser:
    def test_admin_creates_a_user(self, admin_client, login_as, app):
        response = admin_client.post("/users", data=user_form(phone="+375 (29) 700-00-01"))
        assert response.status_code == 302
        assert location(response).endswith("/users")
        user = User.query.filter_by(phone="375297000001").one()
        assert user.full_name == "Петров Пётр Петрович"
        assert user.role == "parent"
        assert "Пользователь создан." in text(admin_client.get("/users"))
        fresh = app.test_client()
        assert login_as(fresh, "375297000001", "secret123").status_code == 302
        User.query.filter_by(phone="375297000001").delete()

    def test_blank_middle_name_is_skipped(self, admin_client, db, make_user):
        parent = make_user(role="parent")
        admin_client.post(
            "/users",
            data=user_form(
                phone="375297000002", middle_name="  ", role="student", parent_id=str(parent.id)
            ),
        )
        user = User.query.filter_by(phone="375297000002").one()
        assert user.full_name == "Петров Пётр"
        assert user.role == "student"
        db.session.delete(user)
        db.session.commit()

    def test_unknown_action(self, admin_client):
        response = admin_client.post("/users", data=user_form(action="drop_database"))
        assert response.status_code == 200
        assert "Неизвестное действие." in text(response)

    def test_missing_action(self, admin_client):
        data = user_form()
        del data["action"]
        assert "Неизвестное действие." in text(admin_client.post("/users", data=data))

    @pytest.mark.parametrize("field", ["last_name", "first_name", "phone", "role"])
    def test_required_fields(self, admin_client, field):
        before = User.query.count()
        response = admin_client.post("/users", data=user_form(**{field: ""}))
        assert response.status_code == 200
        assert "Проверьте заполнение обязательных полей." in text(response)
        assert User.query.count() == before

    @pytest.mark.parametrize("phone", ["+7 (916) 123-45-67", "37529123", "3752912345678"])
    def test_only_belarus_numbers_are_accepted(self, admin_client, phone):
        before = User.query.count()
        response = admin_client.post("/users", data=user_form(phone=phone))
        assert response.status_code == 200
        assert "Введите номер в формате +375 (XX) XXX-XX-XX." in text(response)
        assert User.query.count() == before

    def test_duplicate_phone(self, admin_client):
        response = admin_client.post("/users", data=user_form(phone="+375 (29) 000-00-00"))
        assert response.status_code == 200
        assert "Этот номер телефона уже зарегистрирован." in text(response)

    def test_password_is_required_for_new_users(self, admin_client):
        before = User.query.count()
        response = admin_client.post("/users", data=user_form(phone="375297000003", password=""))
        assert response.status_code == 200
        assert "Укажите пароль не короче 6 символов." in text(response)
        assert User.query.count() == before

    def test_short_password_is_rejected(self, admin_client):
        response = admin_client.post("/users", data=user_form(phone="375297000004", password="123"))
        assert response.status_code == 200
        assert User.query.filter_by(phone="375297000004").count() == 0

    def test_invalid_role_is_rejected(self, admin_client):
        response = admin_client.post("/users", data=user_form(phone="375297000005", role="root"))
        assert response.status_code == 200
        assert User.query.filter_by(phone="375297000005").count() == 0

    def test_parent_cannot_create(self, parent_client):
        response = parent_client.post("/users", data=user_form(), follow_redirects=True)
        assert "Доступ к пользователям разрешен только администратору." in text(response)
        assert User.query.filter_by(phone="375297009999").count() == 0


class TestEditUser:
    def _edit(self, client, user_id, **overrides):
        data = user_form(
            last_name="Новая",
            first_name="Фамилия",
            middle_name="",
            phone="375297100001",
            password="",
        )
        del data["action"]
        data.update(overrides)
        return client.post(f"/users/edit/{user_id}", data=data, follow_redirects=True)

    def test_requires_login(self, client, make_user):
        user = make_user()
        response = client.post(f"/users/edit/{user.id}", data={})
        assert response.status_code == 302
        assert location(response).endswith("/login")

    def test_parent_cannot_edit(self, parent_client, make_user):
        target = make_user()
        response = self._edit(parent_client, target.id)
        assert "Редактировать пользователей может только администратор." in text(response)

    def test_missing_user(self, admin_client):
        assert "Пользователь не найден." in text(self._edit(admin_client, 999999))

    def test_admin_updates_a_user(self, admin_client, make_user, db):
        target = make_user(role="parent")
        old_hash = target.password_hash
        parent = make_user(role="parent")
        response = self._edit(admin_client, target.id, role="student", parent_id=str(parent.id))
        assert "Данные пользователя обновлены." in text(response)
        db.session.refresh(target)
        assert target.full_name == "Новая Фамилия"
        assert target.phone == "375297100001"
        assert target.role == "student"
        assert target.password_hash == old_hash  # пустой пароль = оставить прежний

    def test_admin_can_set_a_new_password(self, admin_client, make_user, db):
        target = make_user()
        self._edit(admin_client, target.id, password="brand-new-pass")
        db.session.refresh(target)
        assert target.check_password("brand-new-pass")

    def test_keeping_own_phone_is_not_a_duplicate(self, admin_client, make_user, db):
        target = make_user()
        response = self._edit(admin_client, target.id, phone=target.phone)
        assert "Данные пользователя обновлены." in text(response)

    def test_duplicate_phone_is_rejected(self, admin_client, make_user, db):
        target, other = make_user(), make_user()
        response = self._edit(admin_client, target.id, phone=other.phone)
        assert "Этот номер телефона уже зарегистрирован." in text(response)
        db.session.refresh(target)
        assert target.phone != other.phone

    def test_non_belarus_phone_is_rejected(self, admin_client, make_user):
        target = make_user()
        response = self._edit(admin_client, target.id, phone="+7 (916) 123-45-67")
        assert "Введите номер в формате +375 (XX) XXX-XX-XX." in text(response)

    def test_invalid_form_is_rejected(self, admin_client, make_user):
        target = make_user()
        response = self._edit(admin_client, target.id, last_name="")
        assert "Проверьте заполнение обязательных полей." in text(response)

    def test_last_admin_cannot_be_demoted(self, admin_client, db):
        admin = User.query.filter_by(phone="375290000000").one()
        response = self._edit(admin_client, admin.id, phone=admin.phone, role="parent")
        assert "Нельзя изменить роль последнего администратора." in text(response)
        db.session.refresh(admin)
        assert admin.role == "admin"

    def test_admin_can_be_demoted_when_another_admin_exists(self, admin_client, second_admin, db):
        other, _ = second_admin
        response = self._edit(admin_client, other.id, phone=other.phone, role="parent")
        assert "Данные пользователя обновлены." in text(response)
        db.session.refresh(other)
        assert other.role == "parent"


class TestDeleteUser:
    def test_requires_login(self, client, make_user):
        target = make_user()
        response = client.post(f"/users/delete/{target.id}")
        assert response.status_code == 302
        assert location(response).endswith("/login")

    def test_parent_cannot_delete(self, parent_client, make_user, db):
        target = make_user()
        response = parent_client.post(f"/users/delete/{target.id}", follow_redirects=True)
        assert "Удалять пользователей может только администратор." in text(response)
        assert db.session.get(User, target.id) is not None

    def test_missing_user(self, admin_client):
        response = admin_client.post("/users/delete/999999", follow_redirects=True)
        assert "Пользователь не найден." in text(response)

    def test_admin_cannot_delete_themselves(self, admin_client, db):
        admin = User.query.filter_by(phone="375290000000").one()
        response = admin_client.post(f"/users/delete/{admin.id}", follow_redirects=True)
        assert "Нельзя удалить собственный аккаунт." in text(response)
        assert db.session.get(User, admin.id) is not None

    def test_user_with_payments_cannot_be_deleted(self, admin_client, make_user, db):
        target = make_user()
        payment = Payment(user_id=target.id, amount=100)
        db.session.add(payment)
        db.session.commit()
        response = admin_client.post(f"/users/delete/{target.id}", follow_redirects=True)
        assert "Нельзя удалить пользователя с историей взносов." in text(response)
        assert db.session.get(User, target.id) is not None
        db.session.delete(payment)
        db.session.commit()

    def test_admin_deletes_a_user(self, admin_client, make_user, db):
        target = make_user()
        response = admin_client.post(f"/users/delete/{target.id}", follow_redirects=True)
        assert "Пользователь удален." in text(response)
        assert db.session.get(User, target.id) is None

    def test_one_admin_can_delete_another(self, admin_client, second_admin, db):
        other, _ = second_admin
        response = admin_client.post(f"/users/delete/{other.id}", follow_redirects=True)
        assert "Пользователь удален." in text(response)

    def test_delete_requires_post(self, admin_client, make_user):
        assert admin_client.get(f"/users/delete/{make_user().id}").status_code == 405


class TestUpdateUserRole:
    def test_requires_login(self, client, make_user):
        response = client.post(f"/users/{make_user().id}/role", data={"role": "student"})
        assert response.status_code == 302
        assert location(response).endswith("/login")

    def test_parent_cannot_change_roles(self, parent_client, make_user, db):
        target = make_user()
        response = parent_client.post(
            f"/users/{target.id}/role", data={"role": "admin"}, follow_redirects=True
        )
        assert "Изменять роли может только администратор." in text(response)
        db.session.refresh(target)
        assert target.role == "parent"

    def test_missing_user(self, admin_client):
        response = admin_client.post(
            "/users/999999/role", data={"role": "student"}, follow_redirects=True
        )
        assert "Пользователь не найден." in text(response)

    @pytest.mark.parametrize("role", ["student", "admin", "parent"])
    def test_admin_changes_a_role(self, admin_client, make_user, db, role):
        target = make_user(role="parent" if role != "parent" else "student")
        response = admin_client.post(
            f"/users/{target.id}/role", data={"role": role}, follow_redirects=True
        )
        assert "Роль пользователя обновлена." in text(response)
        db.session.refresh(target)
        assert target.role == role

    def test_invalid_role(self, admin_client, make_user, db):
        target = make_user()
        response = admin_client.post(
            f"/users/{target.id}/role", data={"role": "root"}, follow_redirects=True
        )
        assert "Выберите корректную роль." in text(response)
        db.session.refresh(target)
        assert target.role == "parent"

    def test_last_admin_cannot_be_demoted(self, admin_client, db):
        admin = User.query.filter_by(phone="375290000000").one()
        response = admin_client.post(
            f"/users/{admin.id}/role", data={"role": "parent"}, follow_redirects=True
        )
        assert "Нельзя изменить роль последнего администратора." in text(response)
        db.session.refresh(admin)
        assert admin.role == "admin"


def test_students_are_not_users(admin_client, db):
    """Ученики из «Состава класса» и учётные записи — разные сущности."""
    db.session.add(Student(last_name="Отдельный", first_name="Ученик"))
    db.session.commit()
    assert "Отдельный" not in text(admin_client.get("/users"))
    Student.query.filter_by(last_name="Отдельный").delete()
    db.session.commit()
