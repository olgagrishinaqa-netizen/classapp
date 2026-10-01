import io

import os

from app.models import News, NewsImage


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
            "images": [(io.BytesIO(b"fake-png-bytes"), "photo.png"), (io.BytesIO(b"fake-jpg"), "two.jpg")],
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302

    news_item = News.query.filter_by(title="С картинкой").one()
    assert len(news_item.images) == 2
    assert news_item.image_url == f"/uploads/{news_item.images[0].path}"

    page = client.get("/news")
    for url in news_item.image_urls:
        assert url.encode() in page.data


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
    assert news_item.images == []


def test_news_creation_rejects_unsupported_image_extension(client, db):
    _login_admin(client)
    before_count = News.query.count()

    response = client.post(
        "/news",
        data={
            "title": "Плохой файл",
            "description": "Текст",
            "status": "published",
            "images": [(io.BytesIO(b"gif-bytes"), "bad.gif")],
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert News.query.count() == before_count


def test_admin_can_add_and_remove_news_images_on_edit(client, db):
    _login_admin(client)
    news_item = News(
        title="Старая",
        description="старое описание",
        status="published",
        images=[NewsImage(name="old.png", path="old-stored.png")],
    )
    db.session.add(news_item)
    db.session.commit()
    old_id = news_item.images[0].id

    response = client.post(
        f"/news/{news_item.id}/edit",
        data={
            "title": "Новая",
            "description": "новое описание",
            "status": "published",
            "images": [(io.BytesIO(b"fake-jpg-bytes"), "new.jpg")],
            "remove_images": str(old_id),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302

    updated = db.session.get(News, news_item.id)
    assert updated.title == "Новая"
    assert [i.name for i in updated.images] == ["new.jpg"]


def test_editing_news_without_new_image_keeps_the_old_one(client, db):
    _login_admin(client)
    news_item = News(
        title="С картинкой",
        description="описание",
        status="published",
        images=[NewsImage(name="old.png", path="old-stored-name.png")],
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
    assert [i.path for i in updated.images] == ["old-stored-name.png"]


def test_news_rejects_more_than_ten_images(client, db):
    _login_admin(client)
    response = client.post(
        "/news",
        data={
            "title": "Много",
            "description": "Текст",
            "status": "published",
            "images": [(io.BytesIO(b"x"), f"{i}.png") for i in range(11)],
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert News.query.filter_by(title="Много").count() == 0


def test_deleting_news_removes_images(client, db, app):
    _login_admin(client)
    client.post(
        "/news",
        data={
            "title": "Удалить",
            "description": "Текст",
            "status": "published",
            "images": [(io.BytesIO(b"x"), "a.png")],
        },
        content_type="multipart/form-data",
    )
    news_item = News.query.filter_by(title="Удалить").one()
    stored = news_item.images[0].path
    news_id = news_item.id
    folder = app.config.get("UPLOAD_FOLDER", os.path.join(os.getcwd(), "uploads"))
    assert os.path.exists(os.path.join(folder, stored))

    client.post(f"/news/{news_id}/delete")
    assert not os.path.exists(os.path.join(folder, stored))
    assert NewsImage.query.filter_by(news_id=news_id).count() == 0
