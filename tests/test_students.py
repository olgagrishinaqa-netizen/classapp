from app.models import Student, User


def _login_admin(client):
    client.post("/login", data={"username": "79990000000", "password": "admin123"})


def test_admin_can_edit_student(client, db):
    _login_admin(client)
    student = Student(last_name="Иванов", first_name="Пётр")
    db.session.add(student)
    db.session.commit()

    response = client.post(
        f"/admin/students/{student.id}/edit",
        data={"last_name": "Иванова", "first_name": "Мария", "birth_date": "2015-05-20"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    updated = db.session.get(Student, student.id)
    assert updated.last_name == "Иванова"
    assert updated.first_name == "Мария"
    assert updated.birth_date.isoformat() == "2015-05-20"


def test_editing_student_to_duplicate_name_keeps_original(client, db):
    _login_admin(client)
    db.session.add_all(
        [
            Student(last_name="Сидоров", first_name="Олег"),
            Student(last_name="Кузнецова", first_name="Анна"),
        ]
    )
    db.session.commit()
    target = Student.query.filter_by(last_name="Кузнецова").one()

    response = client.post(
        f"/admin/students/{target.id}/edit",
        data={"last_name": "Сидоров", "first_name": "Олег"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    unchanged = db.session.get(Student, target.id)
    assert unchanged.last_name == "Кузнецова"
    assert unchanged.first_name == "Анна"


def test_admin_can_delete_student(client, db):
    _login_admin(client)
    student = Student(last_name="Смирнов", first_name="Иван")
    db.session.add(student)
    db.session.commit()
    student_id = student.id

    response = client.post(f"/admin/students/{student_id}/delete", follow_redirects=False)
    assert response.status_code == 302
    assert db.session.get(Student, student_id) is None


def test_deleting_missing_student_flashes_error_without_crashing(client, db):
    _login_admin(client)
    response = client.post("/admin/students/999999/delete", follow_redirects=False)
    assert response.status_code == 302


def test_non_admin_cannot_edit_or_delete_students(client, db):
    parent = User(full_name="Родитель", phone="79997654321", role="parent")
    parent.set_password("parent123")
    db.session.add(parent)
    student = Student(last_name="Волкова", first_name="Ксения")
    db.session.add(student)
    db.session.commit()

    client.post("/login", data={"username": "79997654321", "password": "parent123"})

    edit_response = client.post(
        f"/admin/students/{student.id}/edit",
        data={"last_name": "Изменено", "first_name": "Да"},
        follow_redirects=False,
    )
    assert edit_response.status_code == 302

    delete_response = client.post(f"/admin/students/{student.id}/delete", follow_redirects=False)
    assert delete_response.status_code == 302

    unchanged = db.session.get(Student, student.id)
    assert unchanged is not None
    assert unchanged.last_name == "Волкова"
