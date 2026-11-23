"""Раздел «Общая информация»: записи с описанием и необязательным файлом."""

import io

import pytest

from app.models import GeneralInfo


def text(response):
    return response.get_data(as_text=True)


def upload(name, content=b"%PDF-fake"):
    return (io.BytesIO(content), name)


@pytest.fixture()
def clean_info(wipe):
    wipe(GeneralInfo)


def add_info(db, description="Описание", file_name=None, file_path=None):
    item = GeneralInfo(description=description, file_name=file_name, file_path=file_path)
    db.session.add(item)
    db.session.commit()
    return item


class TestInfoPage:
    def test_requires_login(self, client):
        response = client.get("/info")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")

    def test_parent_sees_items_without_form(self, parent_client, db, clean_info):
        add_info(db, "Звонок учителю: 123", "doc.pdf", "stored_doc.pdf")
        page = text(parent_client.get("/info"))
        assert "Звонок учителю: 123" in page
        assert "/uploads/stored_doc.pdf" in page
        assert 'name="description"' not in page

    def test_admin_sees_the_form(self, admin_client, clean_info):
        assert 'name="description"' in text(admin_client.get("/info"))

    def test_empty_page_renders(self, parent_client, clean_info):
        assert parent_client.get("/info").status_code == 200


class TestAddInfo:
    def test_admin_adds_text_only(self, admin_client, clean_info):
        response = admin_client.post("/info", data={"description": "  Правила класса  "})
        assert response.status_code == 302
        item = GeneralInfo.query.one()
        assert item.description == "Правила класса"
        assert item.file_path is None
        assert "Информация добавлена." in text(admin_client.get("/info"))

    def test_admin_adds_a_file(self, admin_client, upload_dir, clean_info):
        response = admin_client.post(
            "/info",
            data={"description": "С файлом", "file": upload("Список.pdf")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 302
        item = GeneralInfo.query.one()
        assert item.file_name == "file.pdf"
        assert (upload_dir / item.file_path).exists()
        assert item.file_url == f"/uploads/{item.file_path}"

    @pytest.mark.parametrize("name", ["table.xlsx", "memo.docx", "scan.jpg", "old.xls", "a.doc"])
    def test_office_documents_and_images_are_allowed(
        self, admin_client, upload_dir, clean_info, name
    ):
        response = admin_client.post(
            "/info",
            data={"description": "Файл", "file": upload(name)},
            content_type="multipart/form-data",
        )
        assert response.status_code == 302

    def test_executable_is_rejected(self, admin_client, upload_dir, clean_info):
        response = admin_client.post(
            "/info",
            data={"description": "Вирус", "file": upload("run.exe")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
        assert GeneralInfo.query.count() == 0
        assert list(upload_dir.iterdir()) == []

    def test_emoji_file_name_is_sanitised(self, admin_client, upload_dir, clean_info):
        response = admin_client.post(
            "/info",
            data={"description": "Имя из эмодзи", "file": upload("🙂.pdf")},
            content_type="multipart/form-data",
        )
        # «🙂.pdf» превращается в «file.pdf», поэтому запись сохраняется.
        assert response.status_code == 302

    def test_description_is_required(self, admin_client, clean_info):
        response = admin_client.post("/info", data={"description": ""})
        assert response.status_code == 200
        assert GeneralInfo.query.count() == 0

    def test_parent_cannot_add(self, parent_client, clean_info):
        response = parent_client.post("/info", data={"description": "Взлом"})
        assert "Заполнять общую информацию может только администратор." in text(response)
        assert GeneralInfo.query.count() == 0


class TestEditInfo:
    def test_parent_cannot_edit(self, parent_client, db, clean_info):
        item = add_info(db)
        response = parent_client.get(f"/info/{item.id}/edit", follow_redirects=True)
        assert "Редактировать общую информацию может только администратор." in text(response)

    def test_missing_item(self, admin_client, clean_info):
        response = admin_client.get("/info/999999/edit", follow_redirects=True)
        assert "Запись не найдена." in text(response)

    def test_form_is_prefilled(self, admin_client, db, clean_info):
        item = add_info(db, "Старое описание")
        assert "Старое описание" in text(admin_client.get(f"/info/{item.id}/edit"))

    def test_admin_updates_description(self, admin_client, db, clean_info):
        item = add_info(db, "Старое")
        response = admin_client.post(
            f"/info/{item.id}/edit", data={"description": " Новое "}, follow_redirects=True
        )
        assert "Запись обновлена." in text(response)
        db.session.refresh(item)
        assert item.description == "Новое"

    def test_admin_replaces_the_file(self, admin_client, db, upload_dir, clean_info):
        item = add_info(db, "С файлом", "old.pdf", "old_stored.pdf")
        response = admin_client.post(
            f"/info/{item.id}/edit",
            data={"description": "С файлом", "file": upload("new.pdf")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 302
        db.session.refresh(item)
        assert item.file_name == "new.pdf"
        assert item.file_path != "old_stored.pdf"
        assert (upload_dir / item.file_path).exists()

    def test_update_without_file_keeps_the_old_one(self, admin_client, db, clean_info):
        item = add_info(db, "С файлом", "keep.pdf", "keep_stored.pdf")
        admin_client.post(f"/info/{item.id}/edit", data={"description": "Другой текст"})
        db.session.refresh(item)
        assert item.file_path == "keep_stored.pdf"

    def test_bad_file_keeps_the_record_unchanged(self, admin_client, db, upload_dir, clean_info):
        item = add_info(db, "Неизменное")
        response = admin_client.post(
            f"/info/{item.id}/edit",
            data={"description": "Изменено", "file": upload("run.exe")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
        db.session.refresh(item)
        assert item.description == "Неизменное"

    def test_empty_description_is_rejected(self, admin_client, db, clean_info):
        item = add_info(db, "Осталось")
        response = admin_client.post(f"/info/{item.id}/edit", data={"description": ""})
        assert response.status_code == 200
        db.session.refresh(item)
        assert item.description == "Осталось"


class TestDeleteInfo:
    def test_parent_cannot_delete(self, parent_client, db, clean_info):
        item = add_info(db)
        response = parent_client.post(f"/info/{item.id}/delete", follow_redirects=True)
        assert "Удалять общую информацию может только администратор." in text(response)
        assert GeneralInfo.query.count() == 1

    def test_admin_deletes_an_item(self, admin_client, db, clean_info):
        item = add_info(db)
        response = admin_client.post(f"/info/{item.id}/delete", follow_redirects=True)
        assert "Запись удалена." in text(response)
        assert GeneralInfo.query.count() == 0

    def test_deleting_a_missing_item_is_harmless(self, admin_client, clean_info):
        response = admin_client.post("/info/999999/delete")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/info")
