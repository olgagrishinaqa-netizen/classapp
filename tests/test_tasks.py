from datetime import date

from app.models import Task, User


def _login_admin(client):
    client.post("/login", data={"username": "79990000000", "password": "admin123"})


def test_admin_can_create_task_with_all_fields(client, db):
    _login_admin(client)
    response = client.post(
        "/tasks",
        data={"title": "Собрать деньги на подарки", "description": "До праздника", "deadline": "2026-12-20"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    task = Task.query.filter_by(title="Собрать деньги на подарки").one()
    assert task.description == "До праздника"
    assert task.deadline.isoformat() == "2026-12-20"


def test_title_is_required_but_description_and_deadline_are_not(client, db):
    _login_admin(client)

    missing_title = client.post(
        "/tasks",
        data={"title": "", "description": "Без названия"},
        follow_redirects=False,
    )
    assert missing_title.status_code == 200
    assert Task.query.filter_by(description="Без названия").count() == 0

    minimal = client.post(
        "/tasks",
        data={"title": "Только название"},
        follow_redirects=False,
    )
    assert minimal.status_code == 302
    task = Task.query.filter_by(title="Только название").one()
    assert task.description in (None, "")
    assert task.deadline is None


def test_task_appears_on_tasks_page_with_deadline(client, db):
    _login_admin(client)
    client.post(
        "/tasks",
        data={"title": "Купить цветы", "deadline": "2026-11-01"},
        follow_redirects=False,
    )
    page = client.get("/tasks")
    assert "Купить цветы".encode() in page.data
    assert "01.11.2026".encode() in page.data


def test_non_admin_cannot_create_task(client, db):
    parent = User(full_name="Родитель", phone="79990001122", role="parent")
    parent.set_password("parent123")
    db.session.add(parent)
    db.session.commit()

    client.post("/login", data={"username": "79990001122", "password": "parent123"})
    response = client.post(
        "/tasks",
        data={"title": "Попытка родителя"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert Task.query.filter_by(title="Попытка родителя").count() == 0


def test_admin_can_set_task_priority(client, db):
    _login_admin(client)
    response = client.post(
        "/tasks",
        data={"title": "Срочное дело", "priority": "high"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    task = Task.query.filter_by(title="Срочное дело").one()
    assert task.priority == "high"


def test_task_without_priority_field_defaults_to_medium(client, db):
    _login_admin(client)
    client.post("/tasks", data={"title": "Без явного приоритета"}, follow_redirects=False)
    task = Task.query.filter_by(title="Без явного приоритета").one()
    assert task.priority == "medium"


def test_active_tasks_are_sorted_by_priority_then_nearest_deadline(client, db):
    _login_admin(client)
    db.session.add_all(
        [
            Task(title="A: низкий, без дедлайна", priority="low"),
            Task(title="B: высокий, дедлайн далеко", priority="high", deadline=date(2027, 1, 1)),
            Task(title="C: высокий, дедлайн скоро", priority="high", deadline=date(2026, 10, 1)),
            Task(title="D: средний, без дедлайна", priority="medium"),
        ]
    )
    db.session.commit()

    page = client.get("/tasks")
    body = page.data.decode()
    pos_c = body.index("C: высокий, дедлайн скоро")
    pos_b = body.index("B: высокий, дедлайн далеко")
    pos_d = body.index("D: средний, без дедлайна")
    pos_a = body.index("A: низкий, без дедлайна")

    # Внутри приоритета "высокий" ближайший дедлайн должен идти первым,
    # а сам "высокий" приоритет — раньше "среднего" и "низкого".
    assert pos_c < pos_b < pos_d < pos_a


def test_api_create_task_accepts_deadline(client, db):
    login = client.post("/api/login", json={"phone": "79990000000", "password": "admin123"})
    assert login.status_code == 200

    response = client.post(
        "/api/tasks",
        json={"title": "Через API", "description": "d", "deadline": "2026-10-05"},
    )
    assert response.status_code == 201
    payload = response.get_json()
    assert payload["task"]["deadline"] == "2026-10-05"

    bad = client.post("/api/tasks", json={"title": "Плохая дата", "deadline": "05.10.2026"})
    assert bad.status_code == 400
