"""Страницы новостей: лента, создание, редактирование, удаление, картинки."""

import io

import pytest

from app.models import News, NewsImage


def text(response):
    return response.get_data(as_text=True)


def png(name="photo.png", content=b"\x89PNG-fake"):
    return (io.BytesIO(content), name)


def create_news(db, title="Новость", status="published", images=()):
    news = News(
        title=title,
        description="Описание",
        status=status,
        images=[NewsImage(path=path, position=index) for index, path in enumerate(images)],
    )
    db.session.add(news)
    db.session.commit()
    return news


@pytest.fixture()
def clean_news(wipe):
    wipe(NewsImage, News)


class TestNewsFeed:
    def test_requires_login(self, client):
        response = client.get("/news")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")

    def test_parent_sees_only_published(self, parent_client, db, clean_news):
        create_news(db, "Видна всем", "published")
        create_news(db, "Только черновик", "draft")
        page = text(parent_client.get("/news"))
        assert "Видна всем" in page
        assert "Только черновик" not in page

    def test_parent_does_not_get_the_publish_form(self, parent_client, clean_news):
        assert 'name="images"' not in text(parent_client.get("/news"))

    def test_admin_sees_drafts_and_the_form(self, admin_client, db, clean_news):
        create_news(db, "Видна всем", "published")
        create_news(db, "Только черновик", "draft")
        page = text(admin_client.get("/news"))
        assert "Видна всем" in page
        assert "Только черновик" in page
        assert 'name="images"' in page

    def test_admin_in_parent_mode_sees_only_published(self, admin_client, db, clean_news):
        create_news(db, "Опубликовано", "published")
        create_news(db, "Скрытый черновик", "draft")
        admin_client.post("/change_role", data={"role": "parent"})
        page = text(admin_client.get("/news"))
        assert "Опубликовано" in page
        assert "Скрытый черновик" not in page

    def test_newest_news_comes_first(self, admin_client, db, clean_news):
        from datetime import datetime, timedelta

        old = create_news(db, "Старая заметка")
        old.created_at = datetime.now() - timedelta(days=3)
        db.session.commit()
        create_news(db, "Свежая заметка")
        page = text(admin_client.get("/news"))
        assert page.index("Свежая заметка") < page.index("Старая заметка")


class TestCreateNews:
    def test_admin_publishes_news(self, admin_client, clean_news):
        response = admin_client.post(
            "/news",
            data={
                "title": "  Родительское собрание ",
                "description": " В пятницу ",
                "status": "published",
            },
        )
        assert response.status_code == 302
        news = News.query.one()
        assert (news.title, news.description, news.status) == (
            "Родительское собрание",
            "В пятницу",
            "published",
        )
        followed = admin_client.get("/news")
        assert "Новость сохранена." in text(followed)

    def test_admin_saves_a_draft(self, admin_client, clean_news):
        admin_client.post("/news", data={"title": "Т", "description": "Д", "status": "draft"})
        assert News.query.one().status == "draft"

    def test_news_with_images(self, admin_client, upload_dir, clean_news):
        response = admin_client.post(
            "/news",
            data={
                "title": "С фото",
                "description": "Д",
                "status": "published",
                "images": [png("a.png"), png("b.jpg")],
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 302
        news = News.query.one()
        assert [image.position for image in news.images] == [0, 1]
        assert all((upload_dir / image.path).exists() for image in news.images)

    def test_too_many_images_are_rejected(self, admin_client, upload_dir, clean_news):
        response = admin_client.post(
            "/news",
            data={
                "title": "Много фото",
                "description": "Д",
                "status": "published",
                "images": [png(f"{i}.png") for i in range(11)],
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
        assert "не более 10 изображений" in text(response)
        assert News.query.count() == 0
        assert list(upload_dir.iterdir()) == []

    def test_non_image_upload_is_rejected(self, admin_client, upload_dir, clean_news):
        response = admin_client.post(
            "/news",
            data={
                "title": "Скрипт",
                "description": "Д",
                "status": "published",
                "images": [(io.BytesIO(b"echo"), "run.sh")],
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
        assert "Допустимы JPG, PNG или WEBP." in text(response)
        assert News.query.count() == 0

    @pytest.mark.parametrize(
        "data",
        [
            {"title": "", "description": "Д", "status": "published"},
            {"title": "Т", "description": "", "status": "published"},
            {"title": "Т", "description": "Д", "status": "weird"},
            {"title": "Т", "description": "Д"},
        ],
    )
    def test_invalid_form_is_not_saved(self, admin_client, clean_news, data):
        response = admin_client.post("/news", data=data)
        assert response.status_code == 200
        assert News.query.count() == 0

    def test_parent_cannot_publish(self, parent_client, clean_news):
        response = parent_client.post(
            "/news",
            data={"title": "Взлом", "description": "Д", "status": "published"},
            follow_redirects=True,
        )
        assert "Публиковать новости может только администратор." in text(response)
        assert News.query.count() == 0

    def test_admin_in_parent_mode_cannot_publish(self, admin_client, clean_news):
        admin_client.post("/change_role", data={"role": "parent"})
        admin_client.post("/news", data={"title": "Т", "description": "Д", "status": "published"})
        assert News.query.count() == 0

    def test_anonymous_post_redirects_to_login(self, client, clean_news):
        response = client.post("/news", data={"title": "Т", "description": "Д", "status": "draft"})
        assert response.status_code == 302
        assert News.query.count() == 0


class TestDeleteNews:
    def test_requires_login(self, client, db, clean_news):
        news = create_news(db)
        response = client.post(f"/news/{news.id}/delete")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")
        assert db.session.get(News, news.id) is not None

    def test_parent_cannot_delete(self, parent_client, db, clean_news):
        news = create_news(db)
        response = parent_client.post(f"/news/{news.id}/delete", follow_redirects=True)
        assert "Удалять новости может только администратор." in text(response)
        assert db.session.get(News, news.id) is not None

    def test_admin_deletes_news_and_its_files(self, admin_client, db, upload_dir, clean_news):
        (upload_dir / "pic.png").write_bytes(b"x")
        news = create_news(db, images=["pic.png"])
        news_id = news.id
        response = admin_client.post(f"/news/{news_id}/delete", follow_redirects=True)
        assert "Новость удалена." in text(response)
        assert db.session.get(News, news_id) is None
        assert NewsImage.query.count() == 0
        assert not (upload_dir / "pic.png").exists()

    def test_missing_news(self, admin_client, clean_news):
        response = admin_client.post("/news/999999/delete", follow_redirects=True)
        assert "Новость не найдена." in text(response)

    def test_delete_requires_post(self, admin_client, db, clean_news):
        news = create_news(db)
        assert admin_client.get(f"/news/{news.id}/delete").status_code == 405


class TestEditNews:
    def test_requires_login(self, client, db, clean_news):
        news = create_news(db)
        response = client.get(f"/news/{news.id}/edit")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")

    def test_parent_cannot_edit(self, parent_client, db, clean_news):
        news = create_news(db)
        response = parent_client.get(f"/news/{news.id}/edit", follow_redirects=True)
        assert "Редактировать новости может только администратор." in text(response)

    def test_missing_news(self, admin_client, clean_news):
        response = admin_client.get("/news/999999/edit", follow_redirects=True)
        assert "Новость не найдена." in text(response)

    def test_form_is_prefilled(self, admin_client, db, clean_news):
        news = create_news(db, "Заголовок для правки", "draft")
        page = text(admin_client.get(f"/news/{news.id}/edit"))
        assert "Заголовок для правки" in page
        assert 'name="title"' in page

    def test_admin_updates_news(self, admin_client, db, clean_news):
        news = create_news(db, "Было", "draft")
        response = admin_client.post(
            f"/news/{news.id}/edit",
            data={"title": " Стало ", "description": " Новый текст ", "status": "published"},
            follow_redirects=True,
        )
        assert "Новость обновлена." in text(response)
        db.session.refresh(news)
        assert (news.title, news.description, news.status) == ("Стало", "Новый текст", "published")

    def test_invalid_update_keeps_old_values(self, admin_client, db, clean_news):
        news = create_news(db, "Без изменений")
        response = admin_client.post(
            f"/news/{news.id}/edit", data={"title": "", "description": "Д", "status": "published"}
        )
        assert response.status_code == 200
        db.session.refresh(news)
        assert news.title == "Без изменений"

    def test_admin_adds_and_removes_images(self, admin_client, db, upload_dir, clean_news):
        (upload_dir / "old.png").write_bytes(b"old")
        news = create_news(db, images=["old.png"])
        image_id = news.images[0].id

        response = admin_client.post(
            f"/news/{news.id}/edit",
            data={
                "title": "Т",
                "description": "Д",
                "status": "published",
                "remove_images": str(image_id),
                "images": [png("new.png")],
            },
            content_type="multipart/form-data",
        )

        assert response.status_code == 302
        db.session.refresh(news)
        assert len(news.images) == 1
        assert news.images[0].path != "old.png"
        assert not (upload_dir / "old.png").exists()
        assert (upload_dir / news.images[0].path).exists()

    def test_too_many_images_roll_the_edit_back(self, admin_client, db, upload_dir, clean_news):
        news = create_news(db, "Оставить как есть")
        response = admin_client.post(
            f"/news/{news.id}/edit",
            data={
                "title": "Изменено",
                "description": "Д",
                "status": "published",
                "images": [png(f"{i}.png") for i in range(11)],
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
        assert "не более 10 изображений" in text(response)
        db.session.refresh(news)
        assert news.title == "Оставить как есть"
        assert list(upload_dir.iterdir()) == []
