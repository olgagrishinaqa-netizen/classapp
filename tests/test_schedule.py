import io

from app.models import BellScheduleEntry, GeneralInfo, ScheduleEntry, User


def _login_admin(client):
    client.post("/login", data={"username": "79990000000", "password": "admin123"})


def _login_parent(client, db):
    phone = "79991112233"
    if not User.query.filter_by(phone=phone).first():
        parent = User(full_name="Родитель", phone=phone, role="parent")
        parent.set_password("parent123")
        db.session.add(parent)
        db.session.commit()
    client.post("/login", data={"username": phone, "password": "parent123"})


# --- Расписание класса ---------------------------------------------------


def test_admin_can_create_schedule_entry(client, db):
    _login_admin(client)
    response = client.post(
        "/schedule",
        data={"day_of_week": "0", "lesson_number": "1", "subject": "Математика", "teacher": "Иванова И.И.", "room": "12"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    entry = ScheduleEntry.query.filter_by(subject="Математика").one()
    assert entry.day_of_week == 0
    assert entry.lesson_number == 1
    assert entry.room == "12"


def test_duplicate_day_and_lesson_number_is_rejected(client, db):
    _login_admin(client)
    db.session.add(ScheduleEntry(day_of_week=1, lesson_number=1, subject="Математика"))
    db.session.commit()
    before_count = ScheduleEntry.query.count()

    response = client.post(
        "/schedule",
        data={"day_of_week": "1", "lesson_number": "1", "subject": "Русский язык"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert ScheduleEntry.query.count() == before_count


def test_admin_can_edit_and_delete_schedule_entry(client, db):
    _login_admin(client)
    entry = ScheduleEntry(day_of_week=2, lesson_number=1, subject="Математика")
    db.session.add(entry)
    db.session.commit()

    edit_response = client.post(
        f"/schedule/{entry.id}/edit",
        data={"day_of_week": "3", "lesson_number": "2", "subject": "Физика", "teacher": "", "room": ""},
        follow_redirects=False,
    )
    assert edit_response.status_code == 302
    updated = db.session.get(ScheduleEntry, entry.id)
    assert updated.subject == "Физика"
    assert updated.day_of_week == 3

    delete_response = client.post(f"/schedule/{entry.id}/delete", follow_redirects=False)
    assert delete_response.status_code == 302
    assert db.session.get(ScheduleEntry, entry.id) is None


def test_parent_cannot_manage_schedule_but_can_view_it(client, db):
    _login_parent(client, db)
    before_count = ScheduleEntry.query.count()

    create_response = client.post(
        "/schedule",
        data={"day_of_week": "4", "lesson_number": "1", "subject": "Математика"},
        follow_redirects=False,
    )
    assert create_response.status_code == 200
    assert ScheduleEntry.query.count() == before_count

    view_response = client.get("/schedule")
    assert view_response.status_code == 200
    assert "+ Урок".encode() not in view_response.data


# --- Расписание звонков ---------------------------------------------------


def test_admin_can_create_bell_schedule_entry(client, db):
    _login_admin(client)
    response = client.post(
        "/bell-schedule",
        data={"lesson_number": "1", "start_time": "08:30", "end_time": "09:15"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    entry = BellScheduleEntry.query.filter_by(lesson_number=1).one()
    assert entry.start_time.strftime("%H:%M") == "08:30"
    assert entry.end_time.strftime("%H:%M") == "09:15"


def test_bell_schedule_rejects_end_time_before_start_time(client, db):
    _login_admin(client)
    before_count = BellScheduleEntry.query.count()
    response = client.post(
        "/bell-schedule",
        data={"lesson_number": "2", "start_time": "09:15", "end_time": "08:30"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert BellScheduleEntry.query.count() == before_count


def test_admin_can_edit_and_delete_bell_schedule_entry(client, db):
    _login_admin(client)
    from datetime import time

    entry = BellScheduleEntry(lesson_number=3, start_time=time(8, 30), end_time=time(9, 15))
    db.session.add(entry)
    db.session.commit()

    edit_response = client.post(
        f"/bell-schedule/{entry.id}/edit",
        data={"lesson_number": "3", "start_time": "08:35", "end_time": "09:20"},
        follow_redirects=False,
    )
    assert edit_response.status_code == 302
    updated = db.session.get(BellScheduleEntry, entry.id)
    assert updated.start_time.strftime("%H:%M") == "08:35"

    delete_response = client.post(f"/bell-schedule/{entry.id}/delete", follow_redirects=False)
    assert delete_response.status_code == 302
    assert db.session.get(BellScheduleEntry, entry.id) is None


def test_parent_cannot_manage_bell_schedule(client, db):
    _login_parent(client, db)
    before_count = BellScheduleEntry.query.count()
    response = client.post(
        "/bell-schedule",
        data={"lesson_number": "4", "start_time": "08:30", "end_time": "09:15"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert BellScheduleEntry.query.count() == before_count


# --- Общая информация ------------------------------------------------------


def test_admin_can_create_general_info_with_file(client, db):
    _login_admin(client)
    response = client.post(
        "/info",
        data={
            "description": "Список учебников на новый год",
            "file": (io.BytesIO(b"fake-pdf-bytes"), "books.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302
    item = GeneralInfo.query.filter_by(description="Список учебников на новый год").one()
    assert item.file_path is not None
    assert item.file_url == f"/uploads/{item.file_path}"


def test_general_info_can_be_created_without_file(client, db):
    _login_admin(client)
    response = client.post(
        "/info",
        data={"description": "Просто текст без вложений"},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302
    item = GeneralInfo.query.filter_by(description="Просто текст без вложений").one()
    assert item.file_path is None


def test_general_info_rejects_unsupported_extension(client, db):
    _login_admin(client)
    before_count = GeneralInfo.query.count()
    response = client.post(
        "/info",
        data={
            "description": "Плохой файл",
            "file": (io.BytesIO(b"exe-bytes"), "virus.exe"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert GeneralInfo.query.count() == before_count


def test_admin_can_edit_and_delete_general_info(client, db):
    _login_admin(client)
    item = GeneralInfo(description="Старое описание")
    db.session.add(item)
    db.session.commit()

    edit_response = client.post(
        f"/info/{item.id}/edit",
        data={"description": "Новое описание"},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert edit_response.status_code == 302
    assert db.session.get(GeneralInfo, item.id).description == "Новое описание"

    delete_response = client.post(f"/info/{item.id}/delete", follow_redirects=False)
    assert delete_response.status_code == 302
    assert db.session.get(GeneralInfo, item.id) is None


def test_parent_cannot_manage_general_info_but_can_view_it(client, db):
    _login_parent(client, db)
    before_count = GeneralInfo.query.count()
    create_response = client.post(
        "/info",
        data={"description": "Родитель пытается написать"},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert create_response.status_code == 200
    assert GeneralInfo.query.count() == before_count

    view_response = client.get("/info")
    assert view_response.status_code == 200
