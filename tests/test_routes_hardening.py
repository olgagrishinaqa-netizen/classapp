import io

from app.models import Expense, User


def _login_admin_api(client):
    response = client.post("/api/login", json={"phone": "79990000000", "password": "admin123"})
    assert response.status_code == 200


def test_uploads_endpoint_requires_authentication(client):
    anonymous = client.get("/uploads/non-existent-file.jpg")
    assert anonymous.status_code == 401
    assert anonymous.get_json()["error"] == "Требуется авторизация"

    _login_admin_api(client)
    authenticated = client.get("/uploads/non-existent-file.jpg")
    # После авторизации запрос проходит в обработчик файла; несуществующий файл дает 404.
    assert authenticated.status_code == 404


def test_api_prevents_demoting_last_admin(client, db):
    _login_admin_api(client)
    admin = User.query.filter_by(phone="79990000000").one()

    response = client.put(f"/api/users/{admin.id}", json={"role": "parent"})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Нельзя изменить роль последнего администратора"
    db.session.refresh(admin)
    assert admin.role == "admin"


def test_page_prevents_demoting_last_admin(client, db):
    _login_admin_api(client)
    admin = User.query.filter_by(phone="79990000000").one()

    response = client.post(f"/users/{admin.id}/role", data={"role": "parent"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/users")
    db.session.refresh(admin)
    assert admin.role == "admin"


def test_api_news_rejects_unsupported_image_extension(client):
    _login_admin_api(client)

    response = client.post(
        "/api/news",
        data={
            "title": "Тест новости",
            "description": "Описание",
            "status": "published",
            "image": (io.BytesIO(b"gif-bytes"), "bad.gif"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Допустимы JPG, PNG или WEBP."


def test_api_report_rejects_unsupported_receipt_extension(client):
    _login_admin_api(client)

    response = client.post(
        "/api/reports",
        data={
            "income": "1000",
            "items": '[{"title":"Бумага","amount":150}]',
            "receipt": (io.BytesIO(b"gif-bytes"), "bad.gif"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Допустимы JPG, PNG, WEBP или PDF."


def test_expenses_page_does_not_create_record_for_unsupported_receipt_extension(client):
    _login_admin_api(client)
    before_count = Expense.query.count()

    response = client.post(
        "/expenses",
        data={
            "action": "add_expense",
            "title": "Тестовый расход",
            "amount": "25.00",
            "category": "Тест",
            "receipt": (io.BytesIO(b"gif-bytes"), "bad.gif"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    # Валидация формы возвращает ту же страницу с ошибками, расход не сохраняется.
    assert response.status_code == 200
    assert Expense.query.count() == before_count
