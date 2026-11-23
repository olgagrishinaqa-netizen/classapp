"""Диалоги (<dialog>), вкладки и формы, которыми управляет встроенный JavaScript."""

import re
from datetime import time

import pytest
from playwright.sync_api import expect

from app.models import BellScheduleEntry, ScheduleEntry, Student, Task, User

pytestmark = pytest.mark.e2e

HIDDEN = re.compile(r"\bhidden\b")
ACTIVE_TAB = re.compile(r"bg-cyan-100")


def day_tab(page, day):
    return page.locator(f'.schedule-day-tab[data-day="{day}"]')


def add(*rows):
    def create(db):
        db.session.add_all(rows)

    return create


class TestStudents:
    def test_create_dialog_opens_closes_and_creates(self, admin_page):
        admin_page.goto("/admin/students")
        expect(admin_page.locator("#create-student-dialog")).not_to_be_visible()

        admin_page.get_by_role("button", name="+ Ученик").click()
        create = admin_page.locator("#create-student-dialog")
        expect(create).to_be_visible()
        create.get_by_label("Закрыть").click()
        expect(create).not_to_be_visible()

        admin_page.get_by_role("button", name="+ Ученик").click()
        create.locator("input[name=last_name]").fill("Орлов")
        create.locator("input[name=first_name]").fill("Иван")
        create.locator("input[name=birth_date]").fill("2014-09-01")
        create.get_by_role("button", name="Создать ученика").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Ученик «Орлов Иван» добавлен")
        card = admin_page.locator("article", has_text="Орлов Иван")
        expect(card).to_contain_text("Дата рождения: 01.09.2014")

    def test_edit_dialog_is_prefilled_and_saves(self, admin_page, seed):
        student = seed(lambda db: _student(db, "Сидоров", "Олег", "2015-05-20"))
        admin_page.goto("/admin/students")
        admin_page.get_by_role("button", name="Редактировать").click()

        edit = admin_page.locator("#edit-student-dialog")
        expect(edit).to_be_visible()
        expect(edit.locator("#edit-student-last-name")).to_have_value("Сидоров")
        expect(edit.locator("#edit-student-first-name")).to_have_value("Олег")
        expect(edit.locator("#edit-student-birth-date")).to_have_value("2015-05-20")
        expect(admin_page.locator("#edit-student-form")).to_have_attribute(
            "action", re.compile(rf"/admin/students/{student}/edit$")
        )

        edit.locator("#edit-student-first-name").fill("Игорь")
        edit.get_by_role("button", name="Сохранить").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("обновлены")
        expect(admin_page.locator("article", has_text="Сидоров Игорь")).to_be_visible()

    def test_edit_dialog_keeps_the_search_query(self, admin_page, seed):
        seed(
            add(
                Student(last_name="Иванов", first_name="Пётр"),
                Student(last_name="Смирнов", first_name="Олег"),
            )
        )
        admin_page.goto("/admin/students?search=Иван")
        expect(admin_page.locator("article")).to_have_count(1)
        admin_page.get_by_role("button", name="Редактировать").click()
        expect(admin_page.locator("#edit-student-form")).to_have_attribute(
            "action", re.compile(r"\?search=")
        )
        admin_page.locator("#edit-student-first-name").fill("Павел")
        admin_page.locator("#edit-student-dialog").get_by_role("button", name="Сохранить").click()
        admin_page.wait_for_url(re.compile(r"search="))
        expect(admin_page.locator("article", has_text="Иванов Павел")).to_be_visible()

    def test_search_filters_the_list_and_can_be_reset(self, admin_page, seed):
        seed(
            add(
                Student(last_name="Иванов", first_name="Пётр"),
                Student(last_name="Смирнов", first_name="Олег"),
            )
        )
        admin_page.goto("/admin/students")
        expect(admin_page.locator("article")).to_have_count(2)

        admin_page.get_by_placeholder("Поиск по фамилии или имени…").fill("Смир")
        admin_page.keyboard.press("Enter")
        admin_page.wait_for_url(re.compile(r"search="))
        expect(admin_page.locator("article")).to_have_count(1)
        expect(admin_page.locator("article")).to_contain_text("Смирнов")

        admin_page.get_by_label("Сбросить поиск").click()
        expect(admin_page.locator("article")).to_have_count(2)

    def test_search_without_results_shows_a_message(self, admin_page, seed):
        seed(add(Student(last_name="Иванов", first_name="Пётр")))
        admin_page.goto("/admin/students?search=Неттакого")
        expect(admin_page.get_by_text("Ученики не найдены.")).to_be_visible()


def _student(db, last, first, birth):
    from datetime import date

    row = Student(last_name=last, first_name=first, birth_date=date.fromisoformat(birth))
    db.session.add(row)
    db.session.flush()
    return row.id


class TestSchedule:
    @pytest.fixture()
    def lessons(self, seed):
        seed(
            add(
                ScheduleEntry(
                    day_of_week=0,
                    lesson_number=1,
                    subject="Математика",
                    teacher="Иванова",
                    room="12",
                ),
                ScheduleEntry(day_of_week=1, lesson_number=2, subject="Физика"),
            )
        )

    def test_day_tabs_switch_the_visible_panel(self, admin_page, lessons):
        admin_page.goto("/schedule")
        monday = admin_page.locator('[data-day-panel="0"]')
        tuesday = admin_page.locator('[data-day-panel="1"]')
        expect(monday).to_be_visible()
        expect(tuesday).not_to_be_visible()
        expect(monday).to_contain_text("Математика")

        day_tab(admin_page, 1).click()
        expect(tuesday).to_be_visible()
        expect(monday).not_to_be_visible()
        expect(tuesday).to_contain_text("Физика")
        expect(day_tab(admin_page, 1)).to_have_class(ACTIVE_TAB)
        expect(day_tab(admin_page, 0)).not_to_have_class(ACTIVE_TAB)

        day_tab(admin_page, 6).click()
        expect(admin_page.locator('[data-day-panel="6"]')).to_contain_text(
            "Уроков на воскресенье пока нет."
        )

    def test_tab_labels_are_the_first_two_letters_of_the_day(self, admin_page, lessons):
        admin_page.goto("/schedule")
        labels = admin_page.locator(".schedule-day-tab").all_text_contents()
        assert labels == ["По", "Вт", "Ср", "Че", "Пя", "Су", "Во"]

    def test_only_one_panel_is_visible_at_a_time(self, admin_page, lessons):
        admin_page.goto("/schedule")
        for day in range(7):
            admin_page.locator(f'.schedule-day-tab[data-day="{day}"]').click()
            visible = admin_page.locator("[data-day-panel]:visible")
            expect(visible).to_have_count(1)
            expect(visible).to_have_attribute("data-day-panel", str(day))

    def test_edit_dialog_is_prefilled_and_saves(self, admin_page, lessons):
        admin_page.goto("/schedule")
        admin_page.locator('[data-day-panel="0"]').get_by_label("Редактировать урок").click()
        dialog = admin_page.locator("#edit-schedule-dialog")
        expect(dialog).to_be_visible()
        expect(dialog.locator("#edit-schedule-day")).to_have_value("0")
        expect(dialog.locator("#edit-schedule-lesson")).to_have_value("1")
        expect(dialog.locator("#edit-schedule-subject")).to_have_value("Математика")
        expect(dialog.locator("#edit-schedule-teacher")).to_have_value("Иванова")
        expect(dialog.locator("#edit-schedule-room")).to_have_value("12")

        dialog.locator("#edit-schedule-subject").fill("Алгебра")
        dialog.get_by_role("button", name="Сохранить").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Урок обновлён.")
        expect(admin_page.locator('[data-day-panel="0"]')).to_contain_text("Алгебра")

    def test_create_dialog_adds_a_lesson(self, admin_page):
        admin_page.goto("/schedule")
        admin_page.get_by_role("button", name="+ Урок").click()
        dialog = admin_page.locator("#create-schedule-dialog")
        expect(dialog).to_be_visible()
        dialog.locator("select[name=day_of_week]").select_option(label="Среда")
        dialog.locator("input[name=lesson_number]").fill("3")
        dialog.locator("input[name=subject]").fill("История")
        dialog.get_by_role("button", name="Сохранить урок").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Урок добавлен в расписание.")
        day_tab(admin_page, 2).click()
        expect(admin_page.locator('[data-day-panel="2"]')).to_contain_text("История")

    def test_parent_sees_tabs_but_no_edit_controls(self, page, login, seed, lessons):
        seed(add(_parent()))
        login("297770002", "secret123")
        page.wait_for_url("**/dashboard")
        page.goto("/schedule")
        expect(page.locator(".schedule-day-tab")).to_have_count(7)
        expect(page.get_by_label("Редактировать урок")).to_have_count(0)
        expect(page.get_by_role("button", name="+ Урок")).to_have_count(0)


def _parent():
    user = User(full_name="Обычный Родитель", phone="375297770002", role="parent")
    user.set_password("secret123")
    return user


class TestBellSchedule:
    def test_edit_dialog_is_prefilled_and_saves(self, admin_page, seed):
        seed(add(BellScheduleEntry(lesson_number=1, start_time=time(8, 30), end_time=time(9, 15))))
        admin_page.goto("/bell-schedule")
        expect(admin_page.get_by_text("08:30 – 09:15")).to_be_visible()
        admin_page.get_by_label("Редактировать").click()
        dialog = admin_page.locator("#edit-bell-dialog")
        expect(dialog).to_be_visible()
        expect(dialog.locator("#edit-bell-lesson")).to_have_value("1")
        expect(dialog.locator("#edit-bell-start")).to_have_value("08:30")
        expect(dialog.locator("#edit-bell-end")).to_have_value("09:15")

        dialog.locator("#edit-bell-start").fill("08:00")
        dialog.locator("#edit-bell-end").fill("08:45")
        dialog.get_by_role("button", name="Сохранить").click()
        expect(admin_page.get_by_role("alert")).to_contain_text(
            "Строка расписания звонков обновлена."
        )
        expect(admin_page.get_by_text("08:00 – 08:45")).to_be_visible()

    def test_end_before_start_is_refused(self, admin_page, seed):
        seed(add(BellScheduleEntry(lesson_number=1, start_time=time(8, 30), end_time=time(9, 15))))
        admin_page.goto("/bell-schedule")
        admin_page.get_by_label("Редактировать").click()
        dialog = admin_page.locator("#edit-bell-dialog")
        dialog.locator("#edit-bell-end").fill("08:00")
        dialog.get_by_role("button", name="Сохранить").click()
        expect(admin_page.get_by_role("alert")).to_contain_text(
            "Время окончания должно быть позже времени начала."
        )
        expect(admin_page.get_by_text("08:30 – 09:15")).to_be_visible()

    def test_create_dialog_adds_a_bell(self, admin_page):
        admin_page.goto("/bell-schedule")
        admin_page.get_by_role("button", name="+ Урок").click()
        dialog = admin_page.locator("#create-bell-dialog")
        expect(dialog).to_be_visible()
        dialog.locator("input[name=lesson_number]").fill("2")
        dialog.locator("input[name=start_time]").fill("09:25")
        dialog.locator("input[name=end_time]").fill("10:10")
        dialog.get_by_role("button", name="Сохранить").click()
        expect(admin_page.get_by_role("alert")).to_contain_text(
            "Строка расписания звонков добавлена."
        )
        expect(admin_page.get_by_text("09:25 – 10:10")).to_be_visible()


class TestTasks:
    @pytest.fixture()
    def tasks(self, seed):
        seed(add(Task(title="Купить цветы"), Task(title="Сдать отчёт", status="done")))

    def test_tabs_switch_between_active_and_completed(self, admin_page, tasks):
        admin_page.goto("/tasks")
        active = admin_page.locator('[data-panel="active"]')
        completed = admin_page.locator('[data-panel="completed"]')
        expect(active).to_be_visible()
        expect(completed).not_to_be_visible()
        expect(active).to_contain_text("Купить цветы")

        admin_page.get_by_role("tab", name=re.compile("Пройдено")).click()
        expect(completed).to_be_visible()
        expect(active).not_to_be_visible()
        expect(completed).to_contain_text("Сдать отчёт")

        admin_page.get_by_role("tab", name=re.compile("Активные|Активно|Квест")).first.click()
        expect(active).to_be_visible()

    def test_task_can_be_completed_and_reopened(self, admin_page, tasks):
        admin_page.goto("/tasks")
        admin_page.locator('[data-panel="active"] article form button').first.click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Статус задачи обновлен.")
        expect(admin_page.get_by_role("tab", name=re.compile(r"Пройдено \(2\)"))).to_be_visible()

        admin_page.get_by_role("tab", name=re.compile("Пройдено")).click()
        admin_page.locator('[data-panel="completed"] article form button').first.click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Статус задачи обновлен.")
        expect(admin_page.get_by_role("tab", name=re.compile(r"Пройдено \(1\)"))).to_be_visible()

    def test_create_dialog_adds_a_task(self, admin_page):
        admin_page.goto("/tasks")
        admin_page.get_by_role("button", name="+ Квест").click()
        dialog = admin_page.locator("#create-task-dialog")
        expect(dialog).to_be_visible()
        dialog.locator("input[name=title]").fill("Организовать поездку")
        dialog.locator("select[name=priority]").select_option(label="Высокий")
        dialog.get_by_role("button", name="Создать задачу").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Задача создана.")
        expect(admin_page.locator('[data-panel="active"]')).to_contain_text("Организовать поездку")

    def test_close_button_closes_the_dialog(self, admin_page):
        admin_page.goto("/tasks")
        admin_page.get_by_role("button", name="+ Квест").click()
        dialog = admin_page.locator("#create-task-dialog")
        expect(dialog).to_be_visible()
        dialog.get_by_label("Закрыть").click()
        expect(dialog).not_to_be_visible()

    def test_empty_title_is_blocked_by_the_browser(self, admin_page):
        admin_page.goto("/tasks")
        admin_page.get_by_role("button", name="+ Квест").click()
        dialog = admin_page.locator("#create-task-dialog")
        dialog.get_by_role("button", name="Создать задачу").click()
        # Поле required: браузер не отправляет форму, окно остаётся открытым.
        expect(dialog).to_be_visible()
        assert admin_page.evaluate(
            "document.querySelector('#create-task-dialog input[name=title]').validity.valueMissing"
        )
        assert admin_page.url.endswith("/tasks")


class TestExpenses:
    def test_payment_dialog_reopens_with_a_message_when_class_is_empty(self, admin_page):
        admin_page.goto("/expenses")
        admin_page.get_by_role("button", name="+ Взнос").click()
        dialog = admin_page.locator("#payment-dialog")
        expect(dialog).to_be_visible()
        dialog.locator("input[name=amount]").fill("100")
        dialog.get_by_role("button", name="Зафиксировать взнос").click()
        expect(admin_page.get_by_role("alert")).to_contain_text(
            "Сначала добавьте учеников в состав класса."
        )
        # После неудачной отправки окно открывается заново (скрипт в expenses.html).
        expect(admin_page.locator("#payment-dialog")).to_be_visible()

    def test_payment_is_recorded_and_balance_updates(self, admin_page, seed):
        seed(add(Student(last_name="Взносов", first_name="Стёпа")))
        admin_page.goto("/expenses")
        admin_page.get_by_role("button", name="+ Взнос").click()
        dialog = admin_page.locator("#payment-dialog")
        dialog.locator("input[name=amount]").fill("1000.50")
        dialog.get_by_role("button", name="Зафиксировать взнос").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Взнос успешно зафиксирован.")
        expect(admin_page.get_by_text("1000.50").first).to_be_visible()
        # Список плательщиков свёрнут в <details>: раскрываем и проверяем.
        expect(admin_page.get_by_role("heading", name="Взносов Стёпа")).not_to_be_visible()
        admin_page.get_by_text("Кто сдал деньги").click()
        expect(admin_page.get_by_role("heading", name="Взносов Стёпа")).to_be_visible()

    def test_invalid_expense_reopens_the_dialog_with_errors(self, admin_page):
        admin_page.goto("/expenses")
        admin_page.get_by_role("button", name="+ Расход").click()
        dialog = admin_page.locator("#expense-dialog")
        dialog.locator("input[name=title]").fill("Маркеры")
        dialog.locator("input[name=amount]").fill("0")
        dialog.get_by_role("button", name="Добавить расход").click()
        expect(admin_page.get_by_role("alert")).to_contain_text(
            "Расход не сохранён: проверьте поля формы."
        )
        expect(admin_page.locator("#expense-dialog")).to_be_visible()
        expect(admin_page.locator("#expense-dialog input[name=title]")).to_have_value("Маркеры")

    def test_expense_is_recorded(self, admin_page):
        admin_page.goto("/expenses")
        admin_page.get_by_role("button", name="+ Расход").click()
        dialog = admin_page.locator("#expense-dialog")
        dialog.locator("input[name=title]").fill("Бумага А4")
        dialog.locator("input[name=amount]").fill("45.5")
        dialog.locator("input[name=category]").fill("Канцтовары")
        dialog.get_by_role("button", name="Добавить расход").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Расход успешно добавлен.")
        expect(admin_page.get_by_text("Бумага А4")).to_be_visible()

    def test_wrong_receipt_type_is_refused(self, admin_page, tmp_path):
        bad = tmp_path / "virus.exe"
        bad.write_bytes(b"MZ")
        admin_page.goto("/expenses")
        admin_page.get_by_role("button", name="+ Расход").click()
        dialog = admin_page.locator("#expense-dialog")
        dialog.locator("input[name=title]").fill("С чеком")
        dialog.locator("input[name=amount]").fill("10")
        dialog.locator("input[name=receipt]").set_input_files(bad)
        dialog.get_by_role("button", name="Добавить расход").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Расход не сохранён")

    def test_receipt_is_attached(self, admin_page, tmp_path, live_server):
        good = tmp_path / "check.png"
        good.write_bytes(b"\x89PNG\r\n\x1a\n")
        admin_page.goto("/expenses")
        admin_page.get_by_role("button", name="+ Расход").click()
        dialog = admin_page.locator("#expense-dialog")
        dialog.locator("input[name=title]").fill("С чеком")
        dialog.locator("input[name=amount]").fill("10")
        dialog.locator("input[name=receipt]").set_input_files(good)
        dialog.get_by_role("button", name="Добавить расход").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Расход успешно добавлен.")
        assert len(list((live_server.uploads / "receipts").iterdir())) == 1


class TestUsers:
    def test_empty_create_form_reopens_with_a_message(self, admin_page):
        admin_page.goto("/users")
        admin_page.get_by_role("button", name="+ Добавить пользователя").click()
        dialog = admin_page.locator("#create-user-dialog")
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="Создать пользователя").click()
        expect(admin_page.get_by_role("alert")).to_contain_text(
            "Проверьте заполнение обязательных полей."
        )
        expect(admin_page.locator("#create-user-dialog")).to_be_visible()

    def test_user_is_created_edited_and_can_log_in(self, admin_page, login):
        admin_page.goto("/users")
        admin_page.get_by_role("button", name="+ Добавить пользователя").click()
        dialog = admin_page.locator("#create-user-dialog")
        dialog.locator("input[name=last_name]").fill("Петров")
        dialog.locator("input[name=first_name]").fill("Пётр")
        dialog.locator("input[name=phone]").fill("+375 (29) 700-00-09")
        dialog.locator("select[name=role]").select_option(label="Ученик")
        dialog.locator("input[name=password]").fill("secret123")
        dialog.get_by_role("button", name="Создать пользователя").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Пользователь создан.")

        card = admin_page.locator("article", has_text="Петров Пётр")
        expect(card).to_contain_text("Ученик")
        card.get_by_role("button", name=re.compile("Редактировать")).click()
        edit = admin_page.locator("dialog[open]")
        expect(edit.locator("input[name=last_name]")).to_have_value("Петров")
        expect(edit.locator("input[name=first_name]")).to_have_value("Пётр")
        edit.locator("input[name=first_name]").fill("Павел")
        edit.get_by_role("button", name="Сохранить изменения").click()
        expect(admin_page.get_by_role("alert")).to_contain_text("Данные пользователя обновлены.")
        expect(admin_page.locator("article", has_text="Петров Павел")).to_be_visible()

    def test_role_filter_submits_on_change(self, admin_page, seed):
        seed(
            add(
                User(
                    full_name="Родитель Один",
                    phone="375297770010",
                    role="parent",
                    password_hash="x",
                ),
                User(
                    full_name="Ученик Один", phone="375297770011", role="student", password_hash="x"
                ),
            )
        )
        admin_page.goto("/users")
        admin_page.locator("#role-filter").select_option(label="Ученик")
        admin_page.wait_for_url(re.compile(r"role_filter=student"))
        expect(admin_page.get_by_text("Ученик Один")).to_be_visible()
        expect(admin_page.get_by_text("Родитель Один")).to_have_count(0)
        expect(admin_page.locator("#role-filter")).to_have_value("student")


class TestEveryDialogCanBeOpenedAndClosed:
    @pytest.mark.parametrize(
        ("url", "opener", "dialog_id"),
        [
            ("/tasks", "+ Квест", "create-task-dialog"),
            ("/expenses", "+ Взнос", "payment-dialog"),
            ("/expenses", "+ Расход", "expense-dialog"),
            ("/schedule", "+ Урок", "create-schedule-dialog"),
            ("/bell-schedule", "+ Урок", "create-bell-dialog"),
            ("/admin/students", "+ Ученик", "create-student-dialog"),
            ("/users", "+ Добавить пользователя", "create-user-dialog"),
        ],
    )
    def test_open_and_close(self, admin_page, url, opener, dialog_id):
        admin_page.goto(url)
        dialog = admin_page.locator(f"#{dialog_id}")
        expect(dialog).not_to_be_visible()
        admin_page.get_by_role("button", name=opener).click()
        expect(dialog).to_be_visible()
        admin_page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        admin_page.get_by_role("button", name=opener).click()
        expect(dialog).to_be_visible()
        dialog.get_by_label("Закрыть").click()
        expect(dialog).not_to_be_visible()
