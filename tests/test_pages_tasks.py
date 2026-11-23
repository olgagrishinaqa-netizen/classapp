"""Страница задач: список, создание, приоритеты, отметка выполнения."""

from datetime import date, timedelta

import pytest

from app.models import Task


def text(response):
    return response.get_data(as_text=True)


@pytest.fixture()
def clean_tasks(wipe):
    wipe(Task)


def add_task(db, title="Задача", status="created", priority="medium", deadline=None):
    task = Task(title=title, status=status, priority=priority, deadline=deadline)
    db.session.add(task)
    db.session.commit()
    return task


class TestTasksPage:
    def test_requires_login(self, client):
        response = client.get("/tasks")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")

    def test_parent_sees_tasks_without_form(self, parent_client, db, clean_tasks):
        add_task(db, "Купить цветы")
        page = text(parent_client.get("/tasks"))
        assert "Купить цветы" in page
        assert 'name="priority"' not in page

    def test_admin_sees_the_form(self, admin_client, clean_tasks):
        assert 'name="priority"' in text(admin_client.get("/tasks"))

    def test_active_and_completed_are_separated(self, admin_client, db, clean_tasks):
        add_task(db, "Ещё не сделана")
        add_task(db, "Уже сделана", status="done")
        page = text(admin_client.get("/tasks"))
        assert "Ещё не сделана" in page
        assert "Уже сделана" in page

    def test_active_tasks_are_sorted_by_priority_then_deadline(self, admin_client, db, clean_tasks):
        today = date.today()
        add_task(db, "Низкая-приоритет", priority="low", deadline=today)
        add_task(db, "Средняя-поздняя", priority="medium", deadline=today + timedelta(days=9))
        add_task(db, "Высокая-без-срока", priority="high")
        add_task(db, "Средняя-ранняя", priority="medium", deadline=today + timedelta(days=1))
        add_task(db, "Высокая-срочная", priority="high", deadline=today + timedelta(days=2))
        page = text(admin_client.get("/tasks"))
        order = [
            "Высокая-срочная",
            "Высокая-без-срока",
            "Средняя-ранняя",
            "Средняя-поздняя",
            "Низкая-приоритет",
        ]
        positions = [page.index(title) for title in order]
        assert positions == sorted(positions)


class TestCreateTask:
    def test_admin_creates_a_task_with_priority(self, admin_client, clean_tasks):
        response = admin_client.post(
            "/tasks",
            data={"title": "  Новая  ", "description": " Описание ", "priority": "high"},
        )
        assert response.status_code == 302
        task = Task.query.one()
        assert (task.title, task.description, task.priority) == ("Новая", "Описание", "high")
        assert "Задача создана." in text(admin_client.get("/tasks"))

    def test_priority_defaults_to_medium(self, admin_client, clean_tasks):
        admin_client.post("/tasks", data={"title": "Без приоритета"})
        assert Task.query.one().priority == "medium"

    @pytest.mark.parametrize(
        "data",
        [
            {"title": ""},
            {"title": "Т" * 181},
            {"title": "Т", "deadline": "31/12/2026"},
            {"title": "Т", "priority": "urgent"},
        ],
    )
    def test_invalid_task_is_rejected(self, admin_client, clean_tasks, data):
        response = admin_client.post("/tasks", data=data)
        assert response.status_code == 200
        assert "Проверьте правильность заполнения формы." in text(response)
        assert Task.query.count() == 0

    def test_parent_cannot_create(self, parent_client, clean_tasks):
        response = parent_client.post("/tasks", data={"title": "Взлом"}, follow_redirects=True)
        assert "Создавать задачи может только администратор." in text(response)
        assert Task.query.count() == 0

    def test_anonymous_is_redirected(self, client, clean_tasks):
        assert client.post("/tasks", data={"title": "Т"}).status_code == 302
        assert Task.query.count() == 0


class TestCompleteTask:
    def test_requires_login(self, client, db, clean_tasks):
        task = add_task(db)
        response = client.post(f"/tasks/{task.id}/complete")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")
        db.session.refresh(task)
        assert task.status == "created"

    def test_missing_task(self, admin_client, clean_tasks):
        response = admin_client.post("/tasks/999999/complete", follow_redirects=True)
        assert "Задача не найдена." in text(response)

    def test_parent_cannot_change_status(self, parent_client, db, clean_tasks):
        task = add_task(db)
        response = parent_client.post(f"/tasks/{task.id}/complete", follow_redirects=True)
        assert "Изменять статус задач может только администратор." in text(response)
        db.session.refresh(task)
        assert task.status == "created"

    def test_admin_toggles_between_done_and_created(self, admin_client, db, clean_tasks):
        task = add_task(db)
        response = admin_client.post(f"/tasks/{task.id}/complete", follow_redirects=True)
        assert "Статус задачи обновлен." in text(response)
        db.session.refresh(task)
        assert task.status == "done"
        admin_client.post(f"/tasks/{task.id}/complete")
        db.session.refresh(task)
        assert task.status == "created"

    def test_in_progress_task_becomes_done(self, admin_client, db, clean_tasks):
        task = add_task(db, status="in_progress")
        admin_client.post(f"/tasks/{task.id}/complete")
        db.session.refresh(task)
        assert task.status == "done"
