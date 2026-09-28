import io

from app.models import News


def _login_admin(client):
    client.post("/login", data={"username": "79990000000", "password": "admin123"})


def test_admin_can_create_news_with_image(client, db):
    _login_admin(client)

    response = client.post(
        "/news",
        data={
            "title": "С картинкой",
            "description": "Текст новости",
            "status": "published",
            "image": (io.BytesIO(b"fake-png-bytes"), "photo.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302

    news_item = News.query.filter_by(title="С картинкой").one()
    assert news_item.image_path is not None
    assert news_item.image_url == f"/uploads/{news_item.image_path}"

    page = client.get("/news")
    assert news_item.image_url.encode() in page.data


def test_news_can_be_created_without_image(client, db):
    _login_admin(client)
    response = client.post(
        "/news",
        data={"title": "Без картинки", "description": "Текст", "status": "published"},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302
    news_item = News.query.filter_by(title="Без картинки").one()
    assert news_item.image_path is None


def test_news_creation_rejects_unsupported_image_extension(client, db):
    _login_admin(client)
    before_count = News.query.count()

    response = client.post(
        "/news",
        data={
            "title": "Плохой файл",
            "description": "Текст",
            "status": "published",
            "image": (io.BytesIO(b"gif-bytes"), "bad.gif"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert News.query.count() == before_count


def test_admin_can_replace_news_image_on_edit(client, db):
    _login_admin(client)
    news_item = News(title="Старая", description="старое описание", status="published")
    db.session.add(news_item)
    db.session.commit()

    response = client.post(
        f"/news/{news_item.id}/edit",
        data={
            "title": "Новая",
            "description": "новое описание",
            "status": "published",
            "image": (io.BytesIO(b"fake-jpg-bytes"), "new.jpg"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302

    updated = db.session.get(News, news_item.id)
    assert updated.title == "Новая"
    assert updated.image_path is not None


def test_editing_news_without_new_image_keeps_the_old_one(client, db):
    _login_admin(client)
    news_item = News(
        title="С картинкой",
        description="описание",
        status="published",
        image_name="old.png",
        image_path="old-stored-name.png",
    )
    db.session.add(news_item)
    db.session.commit()

    response = client.post(
        f"/news/{news_item.id}/edit",
        data={"title": "С картинкой (изменено)", "description": "описание", "status": "published"},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302

    updated = db.session.get(News, news_item.id)
    assert updated.title == "С картинкой (изменено)"
    assert updated.image_path == "old-stored-name.png"
