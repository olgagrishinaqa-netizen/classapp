"""Вспомогательные функции routes.py (загрузка файлов, сериализация) и audit.py."""

import io
import logging
import os
import re
from datetime import date, datetime

import pytest
from werkzeug.datastructures import FileStorage

from app import audit
from app import routes as r
from app.models import News, NewsImage, Task, User


def _file(name, content=b"data"):
    return FileStorage(stream=io.BytesIO(content), filename=name)


class TestSecureFilename:
    def test_cyrillic_name_keeps_extension(self):
        assert r.secure_filename("туалетка.jpg") == "file.jpg"

    def test_regular_name_is_kept(self):
        assert r.secure_filename("photo.png") == "photo.png"

    def test_only_last_extension_is_used(self):
        assert r.secure_filename("archive.tar.PNG") == "archive.tar.PNG"

    def test_name_without_extension(self):
        assert r.secure_filename("README") == "README"

    def test_unrepresentable_extension_gives_empty_name(self):
        assert r.secure_filename("photo.йцу") == ""

    @pytest.mark.parametrize("name", ["", None])
    def test_empty_name(self, name):
        assert r.secure_filename(name) == ""

    def test_path_traversal_is_neutralised(self):
        result = r.secure_filename("../../etc/passwd.png")
        assert "/" not in result
        assert ".." not in result
        assert result.endswith(".png")


class TestHasAllowedExtension:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [("a.jpg", True), ("A.JPG", True), ("a.exe", False), ("noext", False), ("a.", False)],
    )
    def test_check(self, name, expected):
        assert r._has_allowed_extension(name, {"jpg"}) is expected


class TestFileSizeExceedsLimit:
    def test_over_limit(self):
        assert r._file_size_exceeds_limit(_file("a.png", b"x" * 10), 5) is True

    def test_at_limit(self):
        assert r._file_size_exceeds_limit(_file("a.png", b"x" * 10), 10) is False

    @pytest.mark.parametrize("limit", [None, 0])
    def test_no_limit(self, limit):
        assert r._file_size_exceeds_limit(_file("a.png", b"x" * 10), limit) is False

    def test_stream_position_is_restored(self):
        upload = _file("a.png", b"x" * 10)
        upload.stream.seek(3)
        r._file_size_exceeds_limit(upload, 5)
        assert upload.stream.tell() == 3


@pytest.mark.usefixtures("app")
class TestSaveUploadedFile:
    def _save(self, upload, folder, extensions=frozenset({"png"})):
        return r._save_uploaded_file(
            upload,
            allowed_extensions=extensions,
            destination_folder=str(folder),
            field_error_message="Недопустимый тип.",
        )

    def test_saves_under_unique_name(self, tmp_path):
        name, error = self._save(_file("photo.png", b"PNG"), tmp_path / "nested")
        assert error is None
        assert re.fullmatch(r"[0-9a-f]{32}_photo\.png", name)
        assert (tmp_path / "nested" / name).read_bytes() == b"PNG"

    def test_same_name_does_not_overwrite(self, tmp_path):
        first, _ = self._save(_file("photo.png", b"1"), tmp_path)
        second, _ = self._save(_file("photo.png", b"2"), tmp_path)
        assert first != second
        assert len(list(tmp_path.iterdir())) == 2

    def test_rejects_unusable_name(self, tmp_path):
        name, error = self._save(_file("???"), tmp_path)
        assert name is None
        assert error == "Укажите файл с допустимым именем."
        assert list(tmp_path.iterdir()) == []

    def test_rejects_wrong_extension(self, tmp_path):
        name, error = self._save(_file("virus.exe"), tmp_path)
        assert (name, error) == (None, "Недопустимый тип.")
        assert list(tmp_path.iterdir()) == []

    def test_rejects_file_over_size_limit(self, app, tmp_path, monkeypatch):
        monkeypatch.setitem(app.config, "MAX_CONTENT_LENGTH", 5)
        name, error = self._save(_file("big.png", b"x" * 100), tmp_path)
        assert name is None
        assert error == "Размер файла превышает лимит 1 МБ."
        assert list(tmp_path.iterdir()) == []


class TestUploadFolders:
    def test_upload_folder_from_config(self, app, upload_dir):
        assert r._upload_folder() == str(upload_dir)

    def test_receipts_live_in_subfolder(self, app, upload_dir):
        assert r._receipts_folder() == os.path.join(str(upload_dir), "receipts")

    def test_upload_folder_defaults_to_cwd(self, app, monkeypatch):
        monkeypatch.delitem(app.config, "UPLOAD_FOLDER", raising=False)
        assert r._upload_folder() == os.path.join(os.getcwd(), "uploads")


class TestRemoveUploadedFile:
    def test_removes_existing_file(self, upload_dir):
        target = upload_dir / "gone.png"
        target.write_bytes(b"x")
        r._remove_uploaded_file("gone.png")
        assert not target.exists()

    def test_missing_file_is_ignored(self, upload_dir):
        r._remove_uploaded_file("never-existed.png")  # не должно упасть


class TestRemoveNewsImages:
    def test_removes_only_selected_images(self, db):
        news = News(
            title="С картинками",
            description="x",
            images=[NewsImage(path=f"{i}.png", position=i) for i in range(3)],
        )
        db.session.add(news)
        db.session.commit()
        first, second, third = (image.id for image in news.images)

        removed = r._remove_news_images(news, [str(first), str(third), "not-a-number", "999999"])

        assert sorted(removed) == ["0.png", "2.png"]
        assert [image.id for image in news.images] == [second]
        db.session.rollback()


class TestAttachNewsImages:
    def test_limit_of_images(self, app, upload_dir):
        news = News(title="t", description="d")
        files = [_file(f"{i}.png") for i in range(r.MAX_NEWS_IMAGES + 1)]
        error = r._attach_news_images(news, files)
        assert error == f"К новости можно прикрепить не более {r.MAX_NEWS_IMAGES} изображений."
        assert news.images == []

    def test_empty_file_fields_are_skipped(self, app, upload_dir):
        news = News(title="t", description="d")
        assert r._attach_news_images(news, [None, _file("")]) is None
        assert news.images == []

    def test_positions_continue_after_existing_images(self, app, upload_dir):
        news = News(title="t", description="d", images=[NewsImage(path="old.png", position=4)])
        assert r._attach_news_images(news, [_file("new.png")]) is None
        assert [image.position for image in news.images] == [4, 5]

    def test_error_removes_files_saved_before_it(self, app, upload_dir):
        news = News(title="t", description="d")
        error = r._attach_news_images(news, [_file("ok.png"), _file("bad.exe")])
        assert error == "Допустимы JPG, PNG или WEBP."
        assert list(upload_dir.iterdir()) == []


class TestSerializers:
    def test_user_json_known_role(self):
        user = User(id=1, full_name="Иван", phone="375291112233", role="parent")
        assert r.user_json(user) == {
            "id": 1,
            "full_name": "Иван",
            "phone": "375291112233",
            "role": "parent",
            "role_label": "Родитель",
        }

    def test_user_json_unknown_role_falls_back_to_code(self):
        user = User(id=2, full_name="X", phone="1", role="teacher")
        assert r.user_json(user)["role_label"] == "teacher"

    def test_task_json_with_deadline(self):
        task = Task(
            id=5,
            title="Т",
            description=None,
            deadline=date(2026, 12, 20),
            status="in_progress",
            priority="high",
            created_at=datetime(2026, 11, 1, 10, 0),
        )
        assert r.task_json(task) == {
            "id": 5,
            "title": "Т",
            "description": "",
            "deadline": "2026-12-20",
            "status": "in_progress",
            "status_label": "В работе",
            "priority": "high",
            "created_at": "01.11.2026",
        }

    def test_task_json_without_deadline(self):
        task = Task(id=6, title="Т", status="created", created_at=datetime(2026, 1, 2))
        assert r.task_json(task)["deadline"] is None

    def test_news_json(self):
        news = News(
            id=3,
            title="Н",
            description=None,
            status="draft",
            created_at=datetime(2026, 5, 6, 7, 8),
            updated_at=datetime(2026, 5, 7, 9, 10),
            images=[NewsImage(path="a.png")],
        )
        assert r.news_json(news) == {
            "id": 3,
            "title": "Н",
            "description": "",
            "status": "draft",
            "image_url": "/uploads/a.png",
            "image_urls": ["/uploads/a.png"],
            "created_at": "06.05.2026 07:08",
            "updated_at": "07.05.2026 09:10",
        }


class TestTaskSortKey:
    def test_priority_then_deadline_with_undated_last(self):
        tasks = [
            Task(title="low", priority="low", deadline=date(2026, 1, 1)),
            Task(title="med-late", priority="medium", deadline=date(2026, 3, 1)),
            Task(title="high-none", priority="high", deadline=None),
            Task(title="med-early", priority="medium", deadline=date(2026, 2, 1)),
            Task(title="high-dated", priority="high", deadline=date(2026, 5, 1)),
        ]
        ordered = [task.title for task in sorted(tasks, key=r._task_sort_key)]
        assert ordered == ["high-dated", "high-none", "med-early", "med-late", "low"]

    def test_unknown_priority_is_treated_as_medium(self):
        assert r._task_sort_key(Task(priority="weird", deadline=None))[0] == 1


class TestMaskPhone:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("+375 (29) 000-12-34", "***1234"), ("375290000000", "***0000"), ("12", "***12")],
    )
    def test_masks_all_but_last_four_digits(self, raw, expected):
        assert audit.mask_phone(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "no digits"])
    def test_nothing_to_mask(self, raw):
        assert audit.mask_phone(raw) is None


class TestDescribeDevice:
    @pytest.mark.parametrize(
        ("user_agent", "expected"),
        [
            (
                "Mozilla/5.0 (Linux; Android 14) Chrome/120.0 Mobile Safari/537.36",
                "Android · Chrome",
            ),
            ("Mozilla/5.0 (iPhone; CPU iPhone OS 17) Safari/604.1", "iPhone · Safari"),
            ("Mozilla/5.0 (iPad; CPU OS 17) Safari/604.1", "iPad · Safari"),
            ("Mozilla/5.0 (Windows NT 10.0) Chrome/120 Edg/120", "Windows · Edge"),
            ("Mozilla/5.0 (Windows NT 10.0) Chrome/120 OPR/100", "Windows · Opera"),
            ("Mozilla/5.0 (Windows NT 10.0) Chrome/120 YaBrowser/24", "Windows · Яндекс Браузер"),
            ("Mozilla/5.0 (Macintosh; Intel Mac OS X) Firefox/121.0", "macOS · Firefox"),
            ("Mozilla/5.0 (X11; Linux x86_64) Chrome/120 Safari/537", "Linux · Chrome"),
            ("curl/8.0", "Неизвестное устройство"),
            ("", "Неизвестное устройство"),
            (None, "Неизвестное устройство"),
            ("Windows only", "Windows"),
            ("Firefox/1.0", "Firefox"),
        ],
    )
    def test_describe(self, user_agent, expected):
        assert audit.describe_device(user_agent) == expected


class TestClientIp:
    def test_prefers_x_real_ip(self, app):
        with app.test_request_context("/", headers={"X-Real-IP": "203.0.113.7"}):
            assert audit.client_ip() == "203.0.113.7"

    def test_falls_back_to_remote_addr(self, app):
        with app.test_request_context("/", environ_base={"REMOTE_ADDR": "198.51.100.2"}):
            assert audit.client_ip() == "198.51.100.2"


class TestAuditStorage:
    def test_events_outside_the_persisted_list_are_only_logged(self, app, db):
        from app.models import LoginEvent

        before = LoginEvent.query.count()
        with app.test_request_context("/"):
            audit.audit("some_custom_event", detail="x")
        assert LoginEvent.query.count() == before

    def test_persisted_event_is_stored_with_masked_phone(self, app, db):
        from app.models import LoginEvent

        with app.test_request_context(
            "/", headers={"User-Agent": "UA-test", "X-Real-IP": "203.0.113.9"}
        ):
            audit.audit("login_failed", phone="***1234", reason="bad_password", channel="web")
        event = LoginEvent.query.filter_by(ip="203.0.113.9").order_by(LoginEvent.id.desc()).first()
        assert event.event == "login_failed"
        assert event.phone == "***1234"
        assert event.reason == "bad_password"
        assert event.user_agent == "UA-test"

    def test_storage_failure_is_logged_and_does_not_raise(self, app, db, monkeypatch, caplog):
        def broken(*args, **kwargs):
            raise RuntimeError("db is down")

        monkeypatch.setattr("app.models.LoginEvent", broken)
        with caplog.at_level(logging.ERROR, logger=app.logger.name):
            audit._store_event("login_failed", "203.0.113.1", "ua", {"phone": "***0000"})
        assert any("login_event" in record.getMessage() for record in caplog.records)

    def test_audit_login_counts_attempts(self, app):
        def value(result):
            return audit.LOGIN_ATTEMPTS.labels(result=result, channel="unit")._value.get()

        before_ok, before_fail = value("success"), value("failure")
        with app.test_request_context("/"):
            audit.audit_login(True, "375290000000", User(id=1), channel="unit")
            audit.audit_login(False, "375290000000", reason="bad_password", channel="unit")
        assert value("success") == before_ok + 1
        assert value("failure") == before_fail + 1
