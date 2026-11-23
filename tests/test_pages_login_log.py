"""Журнал входов для администратора: доступ, фильтры, пагинация, статистика."""

from datetime import datetime, timedelta

import pytest
from bs4 import BeautifulSoup

from app.models import LoginEvent, User


def text(response):
    return response.get_data(as_text=True)


@pytest.fixture()
def clean_log(wipe):
    wipe(LoginEvent)


def add_event(db, event="login_success", **fields):
    row = LoginEvent(event=event, channel=fields.pop("channel", "web"), **fields)
    db.session.add(row)
    db.session.commit()
    return row


class TestAccess:
    def test_requires_login(self, client):
        response = client.get("/admin/login-log")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")

    def test_parent_is_sent_to_dashboard(self, parent_client):
        response = parent_client.get("/admin/login-log", follow_redirects=True)
        assert "Журнал входов доступен только администратору." in text(response)

    def test_admin_in_parent_mode_is_refused(self, admin_client):
        admin_client.post("/change_role", data={"role": "parent"})
        response = admin_client.get("/admin/login-log", follow_redirects=True)
        assert "Журнал входов доступен только администратору." in text(response)

    def test_admin_sees_the_page(self, admin_client, clean_log):
        assert admin_client.get("/admin/login-log").status_code == 200


class TestFilters:
    @pytest.fixture(autouse=True)
    def _events(self, db, clean_log):
        add_event(db, "login_success", phone="***1111")
        add_event(db, "login_failed", phone="***2222", reason="bad_password")
        add_event(db, "logout", phone=None)
        add_event(db, "register", phone="***3333")
        add_event(db, "register_rejected", phone="***4444", reason="phone_exists")

    def test_no_filter_shows_all(self, admin_client):
        page = text(admin_client.get("/admin/login-log"))
        for marker in ("***1111", "***2222", "***3333", "***4444"):
            assert marker in page

    def test_success_filter(self, admin_client):
        page = text(admin_client.get("/admin/login-log?filter=success"))
        assert "***1111" in page
        assert "***2222" not in page

    def test_failed_filter_shows_reason(self, admin_client):
        page = text(admin_client.get("/admin/login-log?filter=failed"))
        assert "***2222" in page
        assert "неверный пароль" in page
        assert "***1111" not in page

    def test_logout_filter(self, admin_client):
        page = text(admin_client.get("/admin/login-log?filter=logout"))
        assert "Выход" in page
        assert "***1111" not in page

    def test_register_filter_includes_rejected(self, admin_client):
        page = text(admin_client.get("/admin/login-log?filter=register"))
        assert "***3333" in page and "***4444" in page
        assert "номер уже занят" in page
        assert "***1111" not in page

    def test_unknown_filter_is_ignored(self, admin_client):
        page = text(admin_client.get("/admin/login-log?filter=bogus"))
        assert "***1111" in page and "***2222" in page


class TestRows:
    def test_registered_user_is_shown_by_name(self, admin_client, db, clean_log):
        admin = User.query.filter_by(phone="375290000000").one()
        add_event(db, "login_success", user_id=admin.id, phone="***0000")
        assert admin.full_name in text(admin_client.get("/admin/login-log"))

    def test_deleted_user_is_marked(self, admin_client, db, clean_log):
        add_event(db, "login_success", user_id=987654, phone="***9999")
        assert "удалённый пользователь" in text(admin_client.get("/admin/login-log"))

    def test_unknown_event_type_is_shown_as_is(self, admin_client, db, clean_log):
        add_event(db, "custom_event", phone="***5555")
        assert "custom_event" in text(admin_client.get("/admin/login-log"))

    def test_device_is_described_from_user_agent(self, admin_client, db, clean_log):
        add_event(
            db,
            "login_success",
            user_agent="Mozilla/5.0 (Linux; Android 14) Chrome/120.0 Mobile Safari/537.36",
            ip="203.0.113.5",
        )
        page = text(admin_client.get("/admin/login-log"))
        assert "Android · Chrome" in page
        assert "203.0.113.5" in page

    def test_newest_events_come_first(self, admin_client, db, clean_log):
        now = datetime.now()
        add_event(db, "login_success", phone="***0001", created_at=now - timedelta(hours=2))
        add_event(db, "login_success", phone="***0002", created_at=now)
        page = text(admin_client.get("/admin/login-log"))
        assert page.index("***0002") < page.index("***0001")


def read_stats(client):
    """Три счётчика над таблицей: входов за 24 ч, неудачных, пользователей."""
    soup = BeautifulSoup(client.get("/admin/login-log").get_data(as_text=True), "lxml")
    numbers = [
        int(p.get_text(strip=True)) for p in soup.select("div.glass-card.p-3 p.text-2xl")[:3]
    ]
    return {"success": numbers[0], "failed": numbers[1], "users": numbers[2]}


class TestStats:
    def test_counts_only_last_24_hours(self, admin_client, db, clean_log):
        before = read_stats(admin_client)
        now = datetime.now()
        add_event(db, "login_success", user_id=9001, created_at=now)
        add_event(db, "login_success", user_id=9002, created_at=now - timedelta(hours=1))
        add_event(db, "login_success", user_id=9002, created_at=now - timedelta(hours=2))
        add_event(db, "login_failed", created_at=now)
        add_event(db, "login_success", user_id=9003, created_at=now - timedelta(days=3))
        add_event(db, "login_failed", created_at=now - timedelta(days=3))

        after = read_stats(admin_client)

        assert after["success"] - before["success"] == 3
        assert after["failed"] - before["failed"] == 1
        # Уникальных пользователей: 9001 и 9002 (повторный вход 9002 считается один раз).
        assert after["users"] - before["users"] == 2


class TestPagination:
    @pytest.fixture(autouse=True)
    def _many_events(self, db, clean_log):
        base = datetime.now() - timedelta(hours=1)
        for index in range(35):
            add_event(
                db,
                "login_failed",
                phone=f"***{7000 + index}",
                created_at=base + timedelta(seconds=index),
            )

    def test_first_page_has_thirty_rows(self, admin_client):
        page = text(admin_client.get("/admin/login-log"))
        assert "***7034" in page
        assert "***7000" not in page

    def test_second_page_has_the_rest(self, admin_client):
        page = text(admin_client.get("/admin/login-log?page=2"))
        assert "***7000" in page
        assert "***7034" not in page

    @pytest.mark.parametrize("value", ["0", "-5"])
    def test_non_positive_page_means_first(self, admin_client, value):
        assert "***7034" in text(admin_client.get(f"/admin/login-log?page={value}"))

    def test_page_beyond_the_end_is_empty_not_an_error(self, admin_client):
        assert admin_client.get("/admin/login-log?page=99").status_code == 200

    def test_garbage_page_falls_back_to_first(self, admin_client):
        assert "***7034" in text(admin_client.get("/admin/login-log?page=abc"))
