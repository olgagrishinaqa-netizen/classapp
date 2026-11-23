"""JSON API: авторизация, пользователи, новости, задачи, отчёты, загрузки."""

import io
import json

import pytest
from _credentials import ADMIN_PASSWORD, ADMIN_PHONE

from app.models import ExpenseReport, LoginEvent, News, NewsImage, Task, User


def png(name="photo.png", content=b"\x89PNG-fake"):
    return (io.BytesIO(content), name)


@pytest.fixture()
def api_admin(app, client):
    client.post("/api/login", json={"phone": ADMIN_PHONE, "password": ADMIN_PASSWORD})
    return client


@pytest.fixture()
def api_parent(app, make_user):
    user = make_user(role="parent")
    client = app.test_client()
    client.post("/api/login", json={"phone": user.phone, "password": user.plain_password})
    client.user = user
    return client


@pytest.fixture()
def clean_api(wipe):
    wipe(NewsImage, News, Task, ExpenseReport)


class TestApiLogin:
    def test_json_login(self, client):
        response = client.post(
            "/api/login", json={"phone": ADMIN_PHONE, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["active_role"] == "admin"
        assert body["user"]["role_label"] == "Админ"

    def test_form_login(self, client):
        response = client.post(
            "/api/login", data={"phone": ADMIN_PHONE, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200

    def test_parent_login_has_parent_role(self, app, make_user):
        user = make_user(role="parent")
        response = app.test_client().post(
            "/api/login", json={"phone": user.phone, "password": user.plain_password}
        )
        assert response.get_json()["active_role"] == "parent"

    @pytest.mark.parametrize(
        "payload",
        [
            {"phone": ADMIN_PHONE, "password": "wrong"},
            {"phone": "375001112233", "password": "x"},
            {"phone": ADMIN_PHONE},
            {"password": ADMIN_PASSWORD},
            {},
        ],
    )
    def test_bad_credentials(self, client, payload):
        response = client.post("/api/login", json=payload)
        assert response.status_code == 401
        assert response.get_json() == {"error": "Неверный телефон или пароль"}

    def test_failed_login_is_audited_with_api_channel(self, client):
        client.post("/api/login", json={"phone": ADMIN_PHONE, "password": "wrong"})
        event = LoginEvent.query.order_by(LoginEvent.id.desc()).first()
        assert (event.event, event.channel, event.reason) == ("login_failed", "api", "bad_password")

    def test_unknown_phone_reason(self, client):
        client.post("/api/login", json={"phone": "375001112233", "password": "x"})
        assert LoginEvent.query.order_by(LoginEvent.id.desc()).first().reason == "unknown_user"

    def test_login_without_body(self, client):
        assert client.post("/api/login").status_code == 401


class TestApiSession:
    def test_me_when_anonymous(self, client):
        assert client.get("/api/me").get_json() == {"user": None}

    def test_me_when_logged_in(self, api_admin):
        body = api_admin.get("/api/me").get_json()
        assert body["user"]["phone"] == ADMIN_PHONE
        assert body["active_role"] == "admin"

    def test_logout(self, api_admin):
        assert api_admin.post("/api/logout").get_json() == {"ok": True}
        assert api_admin.get("/api/me").get_json() == {"user": None}
        assert LoginEvent.query.filter_by(event="logout", channel="api").count() >= 1

    def test_logout_without_session(self, client):
        assert client.post("/api/logout").status_code == 200

    def test_switch_role(self, api_admin):
        assert api_admin.post("/api/role", json={"role": "parent"}).get_json() == {
            "active_role": "parent"
        }
        assert api_admin.get("/api/me").get_json()["active_role"] == "parent"
        assert api_admin.post("/api/role", json={"role": "admin"}).status_code == 200

    @pytest.mark.parametrize("body", [{"role": "root"}, {"role": "student"}, {}, None])
    def test_switch_role_rejects_invalid_values(self, api_admin, body):
        response = (
            api_admin.post("/api/role", json=body)
            if body is not None
            else api_admin.post("/api/role")
        )
        assert response.status_code == 400
        assert response.get_json() == {"error": "Недопустимая роль"}

    def test_parent_cannot_become_admin(self, api_parent):
        assert api_parent.post("/api/role", json={"role": "admin"}).status_code == 400

    def test_switch_role_requires_login(self, client):
        assert client.post("/api/role", json={"role": "parent"}).status_code == 401


class TestApiAccessControl:
    @pytest.mark.parametrize(
        ("method", "url"),
        [
            ("get", "/api/users"),
            ("post", "/api/users"),
            ("put", "/api/users/1"),
            ("get", "/api/news"),
            ("post", "/api/news"),
            ("patch", "/api/news/1"),
            ("get", "/api/tasks"),
            ("post", "/api/tasks"),
            ("patch", "/api/tasks/1"),
            ("get", "/api/reports"),
            ("post", "/api/reports"),
            ("get", "/uploads/anything.png"),
        ],
    )
    def test_anonymous_gets_401(self, client, method, url):
        response = getattr(client, method)(url)
        assert response.status_code == 401
        assert response.get_json() == {"error": "Требуется авторизация"}

    @pytest.mark.parametrize(
        ("method", "url"),
        [
            ("get", "/api/users"),
            ("post", "/api/users"),
            ("put", "/api/users/1"),
            ("post", "/api/news"),
            ("patch", "/api/news/1"),
            ("post", "/api/tasks"),
            ("patch", "/api/tasks/1"),
            ("get", "/api/reports"),
            ("post", "/api/reports"),
        ],
    )
    def test_parent_gets_403_on_admin_endpoints(self, api_parent, method, url):
        response = getattr(api_parent, method)(url)
        assert response.status_code == 403
        assert response.get_json() == {"error": "Доступ только для администратора"}


class TestApiUsers:
    def test_list_users(self, api_admin, make_user):
        make_user(full_name="В списке")
        body = api_admin.get("/api/users").get_json()
        assert "В списке" in [item["full_name"] for item in body["users"]]
        assert all(set(item) >= {"id", "phone", "role", "role_label"} for item in body["users"])
        assert all("password" not in item and "password_hash" not in item for item in body["users"])

    def test_create_user_from_json(self, api_admin, db):
        response = api_admin.post(
            "/api/users",
            json={
                "full_name": " Новый ",
                "phone": "+375 (29) 800-00-01",
                "role": "parent",
                "password": "secret123",
            },
        )
        assert response.status_code == 201
        assert response.get_json()["user"]["phone"] == "375298000001"
        user = User.query.filter_by(phone="375298000001").one()
        assert user.full_name == "Новый"
        assert user.check_password("secret123")
        db.session.delete(user)
        db.session.commit()

    def test_create_user_from_form(self, api_admin, db):
        response = api_admin.post(
            "/api/users",
            data={
                "full_name": "Форма",
                "phone": "375298000002",
                "role": "student",
                "password": "secret123",
            },
        )
        assert response.status_code == 201
        db.session.delete(User.query.filter_by(phone="375298000002").one())
        db.session.commit()

    @pytest.mark.parametrize(
        ("alias", "role"),
        [
            ("Родитель", "parent"),
            ("родитель", "parent"),
            ("Ученик", "student"),
            ("student", "student"),
        ],
    )
    def test_russian_role_names_are_accepted(self, api_admin, db, alias, role):
        phone = f"37529800{ord(alias[0]) % 10000:04d}"
        response = api_admin.post(
            "/api/users",
            json={"full_name": "Роль", "phone": phone, "role": alias, "password": "secret123"},
        )
        assert response.status_code == 201
        assert response.get_json()["user"]["role"] == role
        db.session.delete(User.query.filter_by(phone=phone).one())
        db.session.commit()

    @pytest.mark.parametrize("missing", ["full_name", "phone", "role", "password"])
    def test_required_fields(self, api_admin, missing):
        payload = {"full_name": "Имя", "phone": "375298000003", "role": "parent", "password": "x"}
        payload[missing] = "  "
        response = api_admin.post("/api/users", json=payload)
        assert response.status_code == 400
        assert response.get_json() == {"error": "Заполните все обязательные поля"}

    def test_admin_role_cannot_be_created_through_api(self, api_admin):
        response = api_admin.post(
            "/api/users",
            json={
                "full_name": "Х",
                "phone": "375298000004",
                "role": "admin",
                "password": "secret123",
            },
        )
        assert response.status_code == 400
        assert response.get_json() == {"error": "Роль должна быть Родитель или Ученик"}

    def test_phone_without_digits(self, api_admin):
        response = api_admin.post(
            "/api/users",
            json={"full_name": "Х", "phone": "не номер", "role": "parent", "password": "secret123"},
        )
        assert response.status_code == 400
        assert response.get_json() == {"error": "Введите корректный номер телефона"}

    def test_duplicate_phone(self, api_admin):
        response = api_admin.post(
            "/api/users",
            json={
                "full_name": "Х",
                "phone": ADMIN_PHONE,
                "role": "parent",
                "password": "secret123",
            },
        )
        assert response.status_code == 409
        assert response.get_json() == {"error": "Такой номер телефона уже используется"}


class TestApiUpdateUser:
    def test_update_name_and_password(self, api_admin, make_user, db):
        target = make_user()
        response = api_admin.put(
            f"/api/users/{target.id}", json={"full_name": " Другое имя ", "password": "new-secret"}
        )
        assert response.status_code == 200
        db.session.refresh(target)
        assert target.full_name == "Другое имя"
        assert target.check_password("new-secret")

    def test_update_phone(self, api_admin, make_user, db):
        target = make_user()
        response = api_admin.put(f"/api/users/{target.id}", json={"phone": "+375 (29) 811-11-11"})
        assert response.status_code == 200
        db.session.refresh(target)
        assert target.phone == "375298111111"

    @pytest.mark.parametrize(
        ("alias", "role"),
        [("Админ", "admin"), ("ученик", "student"), ("Родитель", "parent"), ("admin", "admin")],
    )
    def test_update_role_with_aliases(self, api_admin, make_user, db, alias, role):
        target = make_user(role="parent" if role != "parent" else "student")
        assert api_admin.put(f"/api/users/{target.id}", json={"role": alias}).status_code == 200
        db.session.refresh(target)
        assert target.role == role

    def test_invalid_role(self, api_admin, make_user):
        response = api_admin.put(f"/api/users/{make_user().id}", json={"role": "root"})
        assert response.status_code == 400
        assert response.get_json() == {"error": "Недопустимая роль"}

    def test_phone_without_digits(self, api_admin, make_user):
        response = api_admin.put(f"/api/users/{make_user().id}", json={"phone": "abc"})
        assert response.status_code == 400
        assert response.get_json() == {"error": "Введите корректный номер телефона"}

    def test_duplicate_phone(self, api_admin, make_user):
        response = api_admin.put(f"/api/users/{make_user().id}", json={"phone": ADMIN_PHONE})
        assert response.status_code == 409

    def test_missing_user(self, api_admin):
        response = api_admin.put("/api/users/999999", json={"full_name": "Х"})
        assert response.status_code == 404
        assert response.get_json() == {"error": "Пользователь не найден"}

    def test_empty_values_change_nothing(self, api_admin, make_user, db):
        target = make_user(full_name="Прежнее имя")
        old_hash = target.password_hash
        api_admin.put(
            f"/api/users/{target.id}",
            json={"full_name": "  ", "role": " ", "phone": "", "password": ""},
        )
        db.session.refresh(target)
        assert target.full_name == "Прежнее имя"
        assert target.role == "parent"
        assert target.password_hash == old_hash

    def test_last_admin_cannot_be_demoted(self, api_admin, db):
        admin = User.query.filter_by(phone=ADMIN_PHONE).one()
        response = api_admin.put(f"/api/users/{admin.id}", json={"role": "parent"})
        assert response.status_code == 400
        assert response.get_json() == {"error": "Нельзя изменить роль последнего администратора"}

    def test_admin_cannot_demote_themselves_even_with_another_admin(self, api_admin, make_user, db):
        make_user(role="admin")
        admin = User.query.filter_by(phone=ADMIN_PHONE).one()
        response = api_admin.put(f"/api/users/{admin.id}", json={"role": "parent"})
        assert response.status_code == 400
        assert response.get_json() == {
            "error": "Нельзя понизить собственную роль администратора через API"
        }
        db.session.refresh(admin)
        assert admin.role == "admin"

    def test_other_admin_can_be_demoted(self, api_admin, make_user, db):
        other = make_user(role="admin")
        assert api_admin.put(f"/api/users/{other.id}", json={"role": "parent"}).status_code == 200


class TestApiNews:
    def test_parent_sees_only_published(self, api_parent, db, clean_api):
        db.session.add_all(
            [
                News(title="Опубликована", description="д", status="published"),
                News(title="Черновик", description="д", status="draft"),
            ]
        )
        db.session.commit()
        titles = [item["title"] for item in api_parent.get("/api/news").get_json()["news"]]
        assert titles == ["Опубликована"]

    def test_admin_sees_drafts(self, api_admin, db, clean_api):
        db.session.add_all(
            [
                News(title="Опубликована", description="д", status="published"),
                News(title="Черновик", description="д", status="draft"),
            ]
        )
        db.session.commit()
        titles = {item["title"] for item in api_admin.get("/api/news").get_json()["news"]}
        assert titles == {"Опубликована", "Черновик"}

    def test_create_news_defaults_to_draft(self, api_admin, clean_api):
        response = api_admin.post("/api/news", json={"title": " Т ", "description": " Д "})
        assert response.status_code == 201
        body = response.get_json()["news"]
        assert (body["title"], body["description"], body["status"]) == ("Т", "Д", "draft")

    def test_create_news_from_form_with_images(self, api_admin, upload_dir, clean_api):
        response = api_admin.post(
            "/api/news",
            data={
                "title": "С фото",
                "description": "Д",
                "status": "published",
                "image": [png("one.png")],
                "images": [png("two.jpg")],
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 201
        assert len(response.get_json()["news"]["image_urls"]) == 2
        assert len(list(upload_dir.iterdir())) == 2

    @pytest.mark.parametrize(
        ("payload", "error"),
        [
            ({"title": "", "description": "Д"}, "Укажите заголовок и описание новости"),
            ({"title": "Т", "description": ""}, "Укажите заголовок и описание новости"),
            (
                {"title": "Т", "description": "Д", "status": "archived"},
                "Некорректный статус новости",
            ),
        ],
    )
    def test_create_news_validation(self, api_admin, clean_api, payload, error):
        response = api_admin.post("/api/news", json=payload)
        assert response.status_code == 400
        assert response.get_json() == {"error": error}
        assert News.query.count() == 0

    def test_create_news_with_bad_image(self, api_admin, upload_dir, clean_api):
        response = api_admin.post(
            "/api/news",
            data={"title": "Т", "description": "Д", "image": [(io.BytesIO(b"x"), "run.exe")]},
            content_type="multipart/form-data",
        )
        assert response.status_code == 400
        assert response.get_json() == {"error": "Допустимы JPG, PNG или WEBP."}
        assert News.query.count() == 0

    def test_update_news_json(self, api_admin, db, clean_api):
        news = News(title="Было", description="Было", status="draft")
        db.session.add(news)
        db.session.commit()
        response = api_admin.patch(
            f"/api/news/{news.id}",
            json={"title": "Стало", "description": "Новое", "status": "published"},
        )
        assert response.status_code == 200
        db.session.refresh(news)
        assert (news.title, news.description, news.status) == ("Стало", "Новое", "published")

    def test_update_news_ignores_blank_and_invalid_values(self, api_admin, db, clean_api):
        news = News(title="Прежний", description="Прежнее", status="draft")
        db.session.add(news)
        db.session.commit()
        api_admin.patch(
            f"/api/news/{news.id}", json={"title": " ", "description": "", "status": "archived"}
        )
        db.session.refresh(news)
        assert (news.title, news.description, news.status) == ("Прежний", "Прежнее", "draft")

    def test_update_news_adds_and_removes_images(self, api_admin, db, upload_dir, clean_api):
        (upload_dir / "old.png").write_bytes(b"old")
        news = News(title="Т", description="Д", images=[NewsImage(path="old.png", position=0)])
        db.session.add(news)
        db.session.commit()
        image_id = news.images[0].id

        response = api_admin.patch(
            f"/api/news/{news.id}",
            data={"remove_images": str(image_id), "images": [png("fresh.png")]},
            content_type="multipart/form-data",
        )

        assert response.status_code == 200
        assert not (upload_dir / "old.png").exists()
        assert len(response.get_json()["news"]["image_urls"]) == 1

    def test_update_news_with_bad_image_rolls_back(self, api_admin, db, upload_dir, clean_api):
        news = News(title="Прежний", description="Д")
        db.session.add(news)
        db.session.commit()
        response = api_admin.patch(
            f"/api/news/{news.id}",
            data={"title": "Новый", "images": [(io.BytesIO(b"x"), "run.exe")]},
            content_type="multipart/form-data",
        )
        assert response.status_code == 400
        db.session.refresh(news)
        assert news.title == "Прежний"

    def test_update_missing_news(self, api_admin, clean_api):
        response = api_admin.patch("/api/news/999999", json={"title": "Х"})
        assert response.status_code == 404
        assert response.get_json() == {"error": "Новость не найдена"}


class TestApiTasks:
    def test_list_tasks(self, api_parent, db, clean_api):
        db.session.add(Task(title="Видна всем"))
        db.session.commit()
        titles = [t["title"] for t in api_parent.get("/api/tasks").get_json()["tasks"]]
        assert titles == ["Видна всем"]

    def test_create_task(self, api_admin, clean_api):
        response = api_admin.post(
            "/api/tasks", json={"title": " Задача ", "description": " Д ", "deadline": "2026-12-20"}
        )
        assert response.status_code == 201
        task = response.get_json()["task"]
        assert (task["title"], task["description"], task["deadline"]) == (
            "Задача",
            "Д",
            "2026-12-20",
        )
        assert task["status"] == "created"

    def test_create_task_without_deadline(self, api_admin, clean_api):
        response = api_admin.post("/api/tasks", json={"title": "Без срока"})
        assert response.get_json()["task"]["deadline"] is None

    @pytest.mark.parametrize(
        ("payload", "error"),
        [
            ({"title": ""}, "Укажите название задачи"),
            ({}, "Укажите название задачи"),
            (
                {"title": "Т", "deadline": "20.12.2026"},
                "Некорректный формат дедлайна, ожидается ГГГГ-ММ-ДД",
            ),
        ],
    )
    def test_create_task_validation(self, api_admin, clean_api, payload, error):
        response = api_admin.post("/api/tasks", json=payload)
        assert response.status_code == 400
        assert response.get_json() == {"error": error}
        assert Task.query.count() == 0

    @pytest.mark.parametrize("status", ["created", "in_progress", "done"])
    def test_update_status(self, api_admin, db, clean_api, status):
        task = Task(title="Т", status="created" if status != "created" else "done")
        db.session.add(task)
        db.session.commit()
        response = api_admin.patch(f"/api/tasks/{task.id}", json={"status": status})
        assert response.status_code == 200
        assert response.get_json()["task"]["status"] == status

    @pytest.mark.parametrize("payload", [{"status": "archived"}, {}])
    def test_update_with_bad_status(self, api_admin, db, clean_api, payload):
        task = Task(title="Т")
        db.session.add(task)
        db.session.commit()
        response = api_admin.patch(f"/api/tasks/{task.id}", json=payload)
        assert response.status_code == 404
        assert response.get_json() == {"error": "Задача или статус не найдены"}

    def test_update_missing_task(self, api_admin, clean_api):
        assert api_admin.patch("/api/tasks/999999", json={"status": "done"}).status_code == 404


class TestApiReports:
    def test_list_reports(self, api_admin, db, clean_api):
        db.session.add(
            ExpenseReport(income=1000, expense_items=[{"title": "Бумага", "amount": 250}])
        )
        db.session.commit()
        report = api_admin.get("/api/reports").get_json()["reports"][0]
        assert report["income"] == 1000
        assert report["total_expenses"] == 250
        assert report["balance"] == 750
        assert report["items"] == [{"title": "Бумага", "amount": 250}]

    def test_create_report(self, api_admin, clean_api):
        response = api_admin.post(
            "/api/reports",
            data={
                "income": "1000",
                "items": json.dumps(
                    [{"title": " Бумага ", "amount": 250}, {"title": "Мел", "amount": "50"}]
                ),
            },
        )
        assert response.status_code == 201
        report = response.get_json()["report"]
        assert report["total_expenses"] == 300
        assert report["balance"] == 700
        assert report["items"][0]["title"] == "Бумага"
        assert ExpenseReport.query.count() == 1

    def test_create_report_without_items(self, api_admin, clean_api):
        response = api_admin.post("/api/reports", data={"income": "10"})
        assert response.status_code == 201
        assert response.get_json()["report"]["balance"] == 10

    def test_create_report_with_receipt(self, api_admin, upload_dir, clean_api):
        response = api_admin.post(
            "/api/reports",
            data={"income": "5", "receipt": png("check.png")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 201
        report = ExpenseReport.query.one()
        assert report.receipt_name == "check.png"
        assert (upload_dir / report.receipt_path).exists()

    def test_create_report_with_bad_receipt(self, api_admin, upload_dir, clean_api):
        response = api_admin.post(
            "/api/reports",
            data={"income": "5", "receipt": (io.BytesIO(b"x"), "run.exe")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 400
        assert response.get_json() == {"error": "Допустимы JPG, PNG, WEBP или PDF."}
        assert ExpenseReport.query.count() == 0

    @pytest.mark.parametrize(
        ("data", "error"),
        [
            ({"income": "abc"}, "Проверьте суммы"),
            ({"income": "1", "items": "{not json"}, "Проверьте суммы"),
            ({"income": "-1"}, "Некорректные данные отчетности"),
            ({"income": "1", "items": json.dumps({"a": 1})}, "Некорректные данные отчетности"),
            (
                {"income": "1", "items": json.dumps([{"title": "", "amount": 5}])},
                "Каждая статья должна иметь название и сумму",
            ),
            (
                {"income": "1", "items": json.dumps([{"title": "Х", "amount": -5}])},
                "Каждая статья должна иметь название и сумму",
            ),
            (
                {"income": "1", "items": json.dumps([{"title": "Х", "amount": "много"}])},
                "Каждая статья должна иметь название и сумму",
            ),
            (
                {"income": "1", "items": json.dumps(["строка"])},
                "Каждая статья должна иметь название и сумму",
            ),
        ],
    )
    def test_create_report_validation(self, api_admin, clean_api, data, error):
        response = api_admin.post("/api/reports", data=data)
        assert response.status_code == 400
        assert response.get_json() == {"error": error}
        assert ExpenseReport.query.count() == 0


class TestUploads:
    def test_logged_in_user_can_download(self, api_parent, upload_dir):
        (upload_dir / "doc.txt").write_bytes(b"hello")
        response = api_parent.get("/uploads/doc.txt")
        assert response.status_code == 200
        assert response.data == b"hello"

    def test_receipts_subfolder(self, api_parent, upload_dir):
        (upload_dir / "receipts").mkdir()
        (upload_dir / "receipts" / "r.png").write_bytes(b"png")
        assert api_parent.get("/uploads/receipts/r.png").status_code == 200

    def test_missing_file(self, api_parent, upload_dir):
        assert api_parent.get("/uploads/nope.png").status_code == 404

    def test_path_traversal_is_blocked(self, api_parent, upload_dir):
        (upload_dir.parent / "secret.txt").write_bytes(b"secret")
        response = api_parent.get("/uploads/../secret.txt")
        assert response.status_code == 404
        assert b"secret" not in response.data
