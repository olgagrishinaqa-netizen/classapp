"""Расписание уроков и расписание звонков."""

from datetime import time

import pytest

from app.models import BellScheduleEntry, ScheduleEntry


def text(response):
    return response.get_data(as_text=True)


def location(response):
    return response.headers["Location"]


@pytest.fixture()
def clean_schedule(wipe):
    wipe(ScheduleEntry)


@pytest.fixture()
def clean_bells(wipe):
    wipe(BellScheduleEntry)


def add_lesson(db, day=0, lesson=1, subject="Математика", teacher=None, room=None):
    entry = ScheduleEntry(
        day_of_week=day, lesson_number=lesson, subject=subject, teacher=teacher, room=room
    )
    db.session.add(entry)
    db.session.commit()
    return entry


def add_bell(db, lesson=1, start=time(8, 30), end=time(9, 15)):
    entry = BellScheduleEntry(lesson_number=lesson, start_time=start, end_time=end)
    db.session.add(entry)
    db.session.commit()
    return entry


class TestSchedulePage:
    def test_requires_login(self, client):
        response = client.get("/schedule")
        assert response.status_code == 302
        assert location(response).endswith("/login")

    def test_parent_sees_lessons_without_management_form(self, parent_client, db, clean_schedule):
        add_lesson(db, subject="Русский язык", teacher="Иванова А. А.", room="12")
        page = text(parent_client.get("/schedule"))
        assert "Русский язык" in page
        assert "Иванова А. А." in page
        assert 'name="subject"' not in page

    def test_admin_sees_the_management_form(self, admin_client, clean_schedule):
        assert 'name="subject"' in text(admin_client.get("/schedule"))

    def test_lessons_are_grouped_by_day_and_ordered_by_number(
        self, admin_client, db, clean_schedule
    ):
        add_lesson(db, day=1, lesson=2, subject="Вторая")
        add_lesson(db, day=1, lesson=1, subject="Первая")
        page = text(admin_client.get("/schedule"))
        assert page.index("Первая") < page.index("Вторая")

    def test_empty_schedule_renders(self, parent_client, clean_schedule):
        assert parent_client.get("/schedule").status_code == 200


class TestAddLesson:
    def _add(self, client, **overrides):
        data = {"day_of_week": "0", "lesson_number": "1", "subject": "Математика"}
        data.update(overrides)
        return client.post("/schedule", data=data)

    def test_admin_adds_a_lesson(self, admin_client, clean_schedule):
        response = self._add(
            admin_client, subject="  Физика ", teacher=" Петров ", room=" 305 ", day_of_week="2"
        )
        assert response.status_code == 302
        entry = ScheduleEntry.query.one()
        assert (entry.day_of_week, entry.subject, entry.teacher, entry.room) == (
            2,
            "Физика",
            "Петров",
            "305",
        )
        assert "Урок добавлен в расписание." in text(admin_client.get("/schedule"))

    def test_monday_is_a_valid_day(self, admin_client, clean_schedule):
        # День 0 (понедельник) нельзя считать «пустым» значением.
        assert self._add(admin_client, day_of_week="0").status_code == 302
        assert ScheduleEntry.query.one().day_of_week == 0

    def test_optional_fields_are_stored_as_null(self, admin_client, clean_schedule):
        self._add(admin_client)
        entry = ScheduleEntry.query.one()
        assert entry.teacher is None
        assert entry.room is None

    def test_duplicate_slot_is_rejected(self, admin_client, db, clean_schedule):
        add_lesson(db, day=3, lesson=2, subject="Занято")
        response = self._add(admin_client, day_of_week="3", lesson_number="2", subject="Другой")
        assert response.status_code == 200
        assert "Урок с таким номером в этот день уже есть в расписании." in text(response)
        assert ScheduleEntry.query.count() == 1

    def test_same_lesson_number_on_another_day_is_allowed(self, admin_client, db, clean_schedule):
        add_lesson(db, day=3, lesson=2)
        assert self._add(admin_client, day_of_week="4", lesson_number="2").status_code == 302
        assert ScheduleEntry.query.count() == 2

    @pytest.mark.parametrize(
        "overrides",
        [
            {"lesson_number": "0"},
            {"lesson_number": "13"},
            {"lesson_number": "abc"},
            {"subject": ""},
            {"day_of_week": "9"},
        ],
    )
    def test_invalid_data_is_not_saved(self, admin_client, clean_schedule, overrides):
        response = self._add(admin_client, **overrides)
        assert response.status_code == 200
        assert ScheduleEntry.query.count() == 0

    def test_parent_cannot_add(self, parent_client, clean_schedule):
        response = self._add(parent_client)
        assert response.status_code == 200
        assert "Заполнять расписание класса может только администратор." in text(response)
        assert ScheduleEntry.query.count() == 0


class TestEditLesson:
    def test_parent_cannot_edit(self, parent_client, db, clean_schedule):
        entry = add_lesson(db, subject="Было")
        response = parent_client.post(
            f"/schedule/{entry.id}/edit", data={"subject": "Стало"}, follow_redirects=True
        )
        assert "Редактировать расписание класса может только администратор." in text(response)
        db.session.refresh(entry)
        assert entry.subject == "Было"

    def test_missing_lesson(self, admin_client, clean_schedule):
        response = admin_client.post("/schedule/999999/edit", data={}, follow_redirects=True)
        assert "Урок не найден." in text(response)

    def test_admin_updates_a_lesson(self, admin_client, db, clean_schedule):
        entry = add_lesson(db, day=0, lesson=1, subject="Было", teacher="Т", room="1")
        response = admin_client.post(
            f"/schedule/{entry.id}/edit",
            data={
                "day_of_week": "4",
                "lesson_number": "6",
                "subject": " Стало ",
                "teacher": "",
                "room": " 22 ",
            },
            follow_redirects=True,
        )
        assert "Урок обновлён." in text(response)
        db.session.refresh(entry)
        assert (entry.day_of_week, entry.lesson_number, entry.subject) == (4, 6, "Стало")
        assert entry.teacher is None
        assert entry.room == "22"

    def test_missing_fields_keep_current_values(self, admin_client, db, clean_schedule):
        entry = add_lesson(db, day=2, lesson=3, subject="Прежний")
        admin_client.post(f"/schedule/{entry.id}/edit", data={})
        db.session.refresh(entry)
        assert (entry.day_of_week, entry.lesson_number, entry.subject) == (2, 3, "Прежний")

    def test_moving_to_an_occupied_slot_is_rejected(self, admin_client, db, clean_schedule):
        add_lesson(db, day=0, lesson=1, subject="Занято")
        entry = add_lesson(db, day=0, lesson=2, subject="Двигаем")
        response = admin_client.post(
            f"/schedule/{entry.id}/edit",
            data={"day_of_week": "0", "lesson_number": "1", "subject": "Двигаем"},
            follow_redirects=True,
        )
        assert "Урок с таким номером в этот день уже есть в расписании." in text(response)
        db.session.refresh(entry)
        assert entry.lesson_number == 2


class TestDeleteLesson:
    def test_parent_cannot_delete(self, parent_client, db, clean_schedule):
        entry = add_lesson(db)
        response = parent_client.post(f"/schedule/{entry.id}/delete", follow_redirects=True)
        assert "Удалять из расписания класса может только администратор." in text(response)
        assert ScheduleEntry.query.count() == 1

    def test_admin_deletes_a_lesson(self, admin_client, db, clean_schedule):
        entry = add_lesson(db)
        response = admin_client.post(f"/schedule/{entry.id}/delete", follow_redirects=True)
        assert "Урок удалён из расписания." in text(response)
        assert ScheduleEntry.query.count() == 0

    def test_deleting_a_missing_lesson_is_harmless(self, admin_client, clean_schedule):
        response = admin_client.post("/schedule/999999/delete")
        assert response.status_code == 302
        assert location(response).endswith("/schedule")


class TestBellSchedulePage:
    def test_requires_login(self, client):
        assert client.get("/bell-schedule").status_code == 302

    def test_parent_sees_times_without_form(self, parent_client, db, clean_bells):
        add_bell(db, 1, time(8, 30), time(9, 15))
        page = text(parent_client.get("/bell-schedule"))
        assert "08:30" in page
        assert "09:15" in page
        assert 'name="start_time"' not in page

    def test_admin_sees_the_form(self, admin_client, clean_bells):
        assert 'name="start_time"' in text(admin_client.get("/bell-schedule"))

    def test_entries_are_ordered_by_lesson(self, admin_client, db, clean_bells):
        add_bell(db, 2, time(9, 25), time(10, 10))
        add_bell(db, 1, time(8, 30), time(9, 15))
        page = text(admin_client.get("/bell-schedule"))
        assert page.index("08:30") < page.index("09:25")


class TestAddBell:
    def _add(self, client, **overrides):
        data = {"lesson_number": "1", "start_time": "08:30", "end_time": "09:15"}
        data.update(overrides)
        return client.post("/bell-schedule", data=data)

    def test_admin_adds_a_bell(self, admin_client, clean_bells):
        response = self._add(admin_client)
        assert response.status_code == 302
        entry = BellScheduleEntry.query.one()
        assert (entry.lesson_number, entry.start_time, entry.end_time) == (
            1,
            time(8, 30),
            time(9, 15),
        )
        assert "Строка расписания звонков добавлена." in text(admin_client.get("/bell-schedule"))

    @pytest.mark.parametrize(("start", "end"), [("09:00", "09:00"), ("10:00", "09:00")])
    def test_end_must_be_after_start(self, admin_client, clean_bells, start, end):
        response = self._add(admin_client, start_time=start, end_time=end)
        assert response.status_code == 200
        assert "Время окончания должно быть позже времени начала." in text(response)
        assert BellScheduleEntry.query.count() == 0

    def test_duplicate_lesson_number_is_rejected(self, admin_client, db, clean_bells):
        add_bell(db, 1)
        response = self._add(admin_client, start_time="10:00", end_time="10:45")
        assert response.status_code == 200
        assert "Урок с таким номером уже есть в расписании звонков." in text(response)
        assert BellScheduleEntry.query.count() == 1

    @pytest.mark.parametrize(
        "overrides",
        [{"lesson_number": "0"}, {"lesson_number": "13"}, {"start_time": ""}, {"end_time": "xx"}],
    )
    def test_invalid_data_is_not_saved(self, admin_client, clean_bells, overrides):
        assert self._add(admin_client, **overrides).status_code == 200
        assert BellScheduleEntry.query.count() == 0

    def test_parent_cannot_add(self, parent_client, clean_bells):
        response = self._add(parent_client)
        assert "Заполнять расписание звонков может только администратор." in text(response)
        assert BellScheduleEntry.query.count() == 0


class TestEditBell:
    def _edit(self, client, entry_id, **overrides):
        data = {"lesson_number": "1", "start_time": "08:00", "end_time": "08:45"}
        data.update(overrides)
        return client.post(f"/bell-schedule/{entry_id}/edit", data=data, follow_redirects=True)

    def test_parent_cannot_edit(self, parent_client, db, clean_bells):
        entry = add_bell(db)
        response = self._edit(parent_client, entry.id)
        assert "Редактировать расписание звонков может только администратор." in text(response)
        db.session.refresh(entry)
        assert entry.start_time == time(8, 30)

    def test_missing_entry(self, admin_client, clean_bells):
        assert "Строка расписания не найдена." in text(self._edit(admin_client, 999999))

    def test_admin_updates_an_entry(self, admin_client, db, clean_bells):
        entry = add_bell(db)
        response = self._edit(admin_client, entry.id, lesson_number="3")
        assert "Строка расписания звонков обновлена." in text(response)
        db.session.refresh(entry)
        assert (entry.lesson_number, entry.start_time, entry.end_time) == (
            3,
            time(8, 0),
            time(8, 45),
        )

    @pytest.mark.parametrize(
        ("start", "end"), [("abc", "09:00"), ("08:00", ""), ("25:00", "26:00")]
    )
    def test_malformed_time_is_rejected(self, admin_client, db, clean_bells, start, end):
        entry = add_bell(db)
        response = self._edit(admin_client, entry.id, start_time=start, end_time=end)
        assert "Укажите корректное время в формате ЧЧ:ММ." in text(response)
        db.session.refresh(entry)
        assert entry.start_time == time(8, 30)

    def test_end_must_be_after_start(self, admin_client, db, clean_bells):
        entry = add_bell(db)
        response = self._edit(admin_client, entry.id, start_time="09:00", end_time="08:00")
        assert "Время окончания должно быть позже времени начала." in text(response)

    def test_renumbering_to_an_existing_lesson_is_rejected(self, admin_client, db, clean_bells):
        add_bell(db, 1)
        entry = add_bell(db, 2, time(9, 25), time(10, 10))
        response = self._edit(admin_client, entry.id, lesson_number="1")
        assert "Урок с таким номером уже есть в расписании звонков." in text(response)
        db.session.refresh(entry)
        assert entry.lesson_number == 2


class TestDeleteBell:
    def test_parent_cannot_delete(self, parent_client, db, clean_bells):
        entry = add_bell(db)
        response = parent_client.post(f"/bell-schedule/{entry.id}/delete", follow_redirects=True)
        assert "Удалять из расписания звонков может только администратор." in text(response)
        assert BellScheduleEntry.query.count() == 1

    def test_admin_deletes_an_entry(self, admin_client, db, clean_bells):
        entry = add_bell(db)
        response = admin_client.post(f"/bell-schedule/{entry.id}/delete", follow_redirects=True)
        assert "Строка расписания звонков удалена." in text(response)
        assert BellScheduleEntry.query.count() == 0

    def test_deleting_a_missing_entry_is_harmless(self, admin_client, clean_bells):
        response = admin_client.post("/bell-schedule/999999/delete")
        assert response.status_code == 302
        assert location(response).endswith("/bell-schedule")
