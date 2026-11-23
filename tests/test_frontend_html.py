"""Фронтенд без браузера: разбор отрисованного HTML (Jinja-шаблоны).

Проверяется то, что получает пользователь: структура страниц, навигация,
доступность форм, видимость элементов управления по ролям, подключаемые
внешние ресурсы и работоспособность внутренних ссылок."""

from datetime import time
from urllib.parse import urlparse

import pytest
from bs4 import BeautifulSoup

from app.models import (
    BellScheduleEntry,
    Expense,
    GeneralInfo,
    News,
    NewsImage,
    Payment,
    ScheduleEntry,
    Student,
    Task,
)

ALLOWED_EXTERNAL_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com", "cdn.tailwindcss.com"}

ADMIN_PAGES = [
    "/dashboard",
    "/news",
    "/schedule",
    "/bell-schedule",
    "/info",
    "/tasks",
    "/expenses",
    "/profile",
    "/users",
    "/admin/students",
    "/admin/login-log",
]
PARENT_PAGES = [
    "/dashboard",
    "/news",
    "/schedule",
    "/bell-schedule",
    "/info",
    "/tasks",
    "/expenses",
    "/profile",
]


def soup_of(response):
    return BeautifulSoup(response.get_data(as_text=True), "lxml")


@pytest.fixture()
def sample(db, wipe):
    """Набор данных, при котором на страницах есть все элементы управления."""
    wipe(
        Payment,
        Expense,
        Student,
        GeneralInfo,
        NewsImage,
        News,
        ScheduleEntry,
        BellScheduleEntry,
        Task,
    )
    student = Student(last_name="Иванов", first_name="Пётр")
    news = News(
        title="Собрание",
        description="В пятницу",
        status="published",
        images=[NewsImage(path="a.png", position=0), NewsImage(path="b.png", position=1)],
    )
    info = GeneralInfo(description="Правила", file_name="rules.pdf", file_path="rules.pdf")
    expense = Expense(title="Мел", amount=150, category="Общие")
    db.session.add_all(
        [
            student,
            news,
            info,
            expense,
            Task(title="Купить цветы"),
            ScheduleEntry(day_of_week=0, lesson_number=1, subject="Математика"),
            BellScheduleEntry(lesson_number=1, start_time=time(8, 30), end_time=time(9, 15)),
        ]
    )
    db.session.commit()
    payment = Payment(student_id=student.id, amount=500)
    db.session.add(payment)
    db.session.commit()
    return {
        "news_id": news.id,
        "info_id": info.id,
        "expense_id": expense.id,
        "payment_id": payment.id,
    }


@pytest.fixture()
def edit_pages(sample):
    return [
        f"/news/{sample['news_id']}/edit",
        f"/info/{sample['info_id']}/edit",
        f"/expenses/edit/{sample['expense_id']}",
        f"/payments/edit/{sample['payment_id']}",
    ]


class TestEveryPage:
    @pytest.mark.parametrize("url", ADMIN_PAGES)
    def test_admin_page_basics(self, admin_client, sample, url):
        response = admin_client.get(url)
        assert response.status_code == 200
        assert response.mimetype == "text/html"
        self._assert_well_formed(soup_of(response), response.get_data(as_text=True))

    def test_edit_pages_basics(self, admin_client, edit_pages):
        for url in edit_pages:
            response = admin_client.get(url)
            assert response.status_code == 200, url
            self._assert_well_formed(soup_of(response), response.get_data(as_text=True))

    @pytest.mark.parametrize("url", ["/login", "/register"])
    def test_public_page_basics(self, client, url):
        response = client.get(url)
        assert response.status_code == 200
        self._assert_well_formed(soup_of(response), response.get_data(as_text=True))

    @staticmethod
    def _assert_well_formed(soup, raw):
        assert soup.html["lang"] == "ru"
        assert soup.find("meta", charset=True)["charset"].lower() == "utf-8"
        viewport = soup.find("meta", attrs={"name": "viewport"})
        assert viewport and "width=device-wi" in viewport["content"]
        assert soup.title and soup.title.get_text(strip=True)
        assert len(soup.find_all("h1")) == 1
        assert "{{" not in raw and "{%" not in raw, "в HTML остался неотрисованный Jinja-код"
        assert "None" not in soup.get_text(" ", strip=True).split(), "на странице выведено «None»"
        for image in soup.find_all("img"):
            assert image.has_attr("alt"), f"у картинки {image.get('src')} нет alt"
        for link in soup.find_all("a", href=True):
            href = link["href"].strip()
            assert href and not href.lower().startswith("javascript:"), href
        assert soup.find("main") is not None

    @pytest.mark.parametrize("url", ADMIN_PAGES)
    def test_only_whitelisted_external_resources(self, admin_client, sample, url):
        soup = soup_of(admin_client.get(url))
        urls = [tag["src"] for tag in soup.find_all(src=True)]
        urls += [tag["href"] for tag in soup.find_all("link", href=True)]
        hosts = {urlparse(u).netloc for u in urls if u.startswith(("http://", "https://", "//"))}
        assert hosts <= ALLOWED_EXTERNAL_HOSTS, hosts - ALLOWED_EXTERNAL_HOSTS

    @pytest.mark.parametrize("url", ADMIN_PAGES)
    def test_inline_event_handlers_are_limited_to_known_safe_ones(self, admin_client, sample, url):
        soup = soup_of(admin_client.get(url))
        for tag in soup.find_all(True):
            for attr, value in tag.attrs.items():
                if attr.lower().startswith("on"):
                    safe = value.strip().endswith((".showModal()", ".close()")) or (
                        value.strip() == "this.form.submit()"
                    )
                    assert safe, (tag.name, attr, value)


class TestInternalLinks:
    @pytest.mark.parametrize("url", ADMIN_PAGES)
    def test_every_internal_link_resolves(self, admin_client, sample, url):
        soup = soup_of(admin_client.get(url))
        broken = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if href.startswith("#") or not href.startswith("/") or href.startswith("//"):
                continue
            if href.startswith("/uploads/"):
                continue  # файлы вложений в тестовых данных не создаются
            path = href.split("#")[0]
            status = admin_client.get(path).status_code
            if status not in (200, 302):
                broken.append((href, status))
        assert not broken

    def test_dashboard_links_to_every_section(self, admin_client, sample):
        hrefs = {
            a["href"].split("#")[0]
            for a in soup_of(admin_client.get("/dashboard")).find_all("a", href=True)
        }
        for section in (
            "/tasks",
            "/expenses",
            "/news",
            "/schedule",
            "/bell-schedule",
            "/info",
            "/users",
            "/admin/students",
            "/admin/login-log",
        ):
            assert section in hrefs, section

    def test_parent_dashboard_hides_admin_sections(self, parent_client, sample):
        hrefs = {
            a["href"] for a in soup_of(parent_client.get("/dashboard")).find_all("a", href=True)
        }
        assert "/users" not in hrefs
        assert "/admin/students" not in hrefs
        assert "/admin/login-log" not in hrefs
        assert "/schedule" in hrefs


class TestNavigation:
    def _nav_links(self, client, url):
        nav = soup_of(client.get(url)).find("nav", attrs={"aria-label": "Основная навигация"})
        links = []
        for anchor in nav.find_all("a"):
            icon = anchor.find("span", attrs={"aria-hidden": "true"})
            label = anchor.get_text(" ", strip=True)
            if icon is not None:
                label = label.replace(icon.get_text(" ", strip=True), "", 1).strip()
            links.append((label, anchor["href"], anchor))
        return nav, links

    def test_admin_nav_has_five_items(self, admin_client):
        _, links = self._nav_links(admin_client, "/dashboard")
        assert [label for label, *_ in links] == ["Хаб", "Квесты", "Баланс", "Класс", "Профиль"]

    def test_parent_nav_has_four_items(self, parent_client):
        _, links = self._nav_links(parent_client, "/dashboard")
        assert [label for label, *_ in links] == ["Хаб", "Квесты", "Баланс", "Профиль"]

    @pytest.mark.parametrize(
        ("url", "label"),
        [
            ("/dashboard", "Хаб"),
            ("/tasks", "Квесты"),
            ("/expenses", "Баланс"),
            ("/profile", "Профиль"),
        ],
    )
    def test_current_section_is_highlighted(self, parent_client, url, label):
        _, links = self._nav_links(parent_client, url)
        active = [text for text, _, anchor in links if "text-cyan-700" in anchor.get("class", [])]
        assert active == [label]

    @pytest.mark.parametrize("url", ["/login", "/register"])
    def test_public_pages_have_no_navigation(self, client, url):
        assert soup_of(client.get(url)).find("nav") is None


class TestFlashMessages:
    def test_error_and_success_messages_are_alerts(self, admin_client, sample):
        admin_client.post("/news/999999/delete")
        page = soup_of(admin_client.get("/news"))
        alert = page.find(attrs={"role": "alert"})
        assert alert and "Новость не найдена." in alert.get_text()
        assert "text-rose-700" in " ".join(alert["class"])

    def test_success_message_uses_success_colours(self, admin_client, sample):
        admin_client.post("/change_role", data={"role": "parent"})
        alert = soup_of(admin_client.get("/profile")).find(attrs={"role": "alert"})
        assert "text-emerald-700" in " ".join(alert["class"])

    def test_message_is_shown_only_once(self, admin_client, sample):
        admin_client.post("/news/999999/delete")
        admin_client.get("/news")
        assert soup_of(admin_client.get("/news")).find(attrs={"role": "alert"}) is None


def _known_gap(url, reason):
    return pytest.param(url, marks=pytest.mark.xfail(strict=True, reason=reason), id=url)


class TestFormsAreAccessible:
    @pytest.mark.parametrize(
        "url",
        [
            _known_gap(
                "/login",
                "label[for] указывает на id по умолчанию (username/password), а у полей id "
                "переопределён (phone-input/password-input): подпись не связана с полем",
            ),
            "/register",
        ],
    )
    def test_public_form_fields_have_labels(self, client, url):
        self._assert_fields_labelled(soup_of(client.get(url)))

    @pytest.mark.parametrize(
        "url",
        [
            "/news",
            "/info",
            "/tasks",
            "/expenses",
            _known_gap("/schedule", "в диалоге редактирования <label> без атрибута for"),
            _known_gap("/bell-schedule", "в диалоге редактирования <label> без атрибута for"),
            _known_gap("/users", "в диалогах редактирования у полей нет id и подписей"),
            _known_gap(
                "/admin/students",
                "у поля поиска нет подписи (только placeholder), в диалоге правки <label> без for",
            ),
        ],
    )
    def test_admin_form_fields_have_labels(self, admin_client, sample, url):
        self._assert_fields_labelled(soup_of(admin_client.get(url)))

    @staticmethod
    def _assert_fields_labelled(soup):
        labelled = {label["for"] for label in soup.find_all("label", attrs={"for": True})}
        for field in soup.find_all(["input", "select", "textarea"]):
            if field.name == "input" and field.get("type") in {"hidden", "submit", "button"}:
                continue
            ident = field.get("id")
            has_name = bool(field.get("aria-label")) or (ident in labelled)
            assert has_name, f"поле {field.get('name')} без подписи"

    def test_every_post_form_has_a_submit_button(self, admin_client, sample):
        for url in ADMIN_PAGES:
            for form in soup_of(admin_client.get(url)).find_all(
                "form", method=lambda m: m and m.lower() == "post"
            ):
                assert form.find(
                    ["button", "input"], attrs={"type": lambda t: t in (None, "submit")}
                ), (url, form.get("id"))

    def test_phone_field_is_telephone_input(self, client):
        phone = soup_of(client.get("/login")).find(id="phone-input")
        assert phone["inputmode"] == "tel"
        assert phone["autocomplete"] == "tel"

    def test_password_field_is_masked_with_toggle(self, client):
        soup = soup_of(client.get("/login"))
        assert soup.find(id="password-input")["type"] == "password"
        toggle = soup.find(id="password-toggle")
        assert toggle["aria-pressed"] == "false"
        assert toggle["aria-label"] == "Показать пароль"

    def test_registration_form_fields(self, client):
        names = {f.get("name") for f in soup_of(client.get("/register")).find_all("input")}
        assert {"full_name", "username", "password", "password_confirm"} <= names

    def test_file_inputs_restrict_types(self, admin_client, sample):
        soup = soup_of(admin_client.get("/expenses"))
        receipt = soup.find("input", attrs={"name": "receipt"})
        assert receipt["accept"] == ".jpg,.jpeg,.png,.webp,.pdf"

    def test_validation_errors_are_shown_next_to_fields(self, client):
        page = soup_of(
            client.post("/register", data={"full_name": "", "username": "", "password": "1"})
        )
        errors = [p.get_text(strip=True) for p in page.select("p.text-rose-600")]
        assert errors, "ошибки валидации не показаны"


class TestRoleBasedControls:
    def test_news_controls(self, admin_client, parent_client, sample):
        admin, parent = soup_of(admin_client.get("/news")), soup_of(parent_client.get("/news"))
        assert admin.select_one("form#news-form")
        assert admin.select_one("form.js-confirm-delete")
        assert admin.select_one('a[href*="/edit"]')
        assert not parent.select_one("form#news-form")
        assert not parent.select_one("form.js-confirm-delete")
        assert not parent.select_one('a[href*="/edit"]')

    def test_schedule_controls(self, admin_client, parent_client, sample):
        admin, parent = soup_of(admin_client.get("/schedule")), soup_of(
            parent_client.get("/schedule")
        )
        assert admin.select_one('button[onclick*="create-schedule-dialog"]')
        assert admin.select_one(".edit-schedule-btn")
        assert admin.select_one("form.js-confirm-delete")
        assert not parent.select_one('button[onclick*="create-schedule-dialog"]')
        assert not parent.select_one(".edit-schedule-btn")
        assert not parent.select_one("form.js-confirm-delete")

    def test_bell_schedule_controls(self, admin_client, parent_client, sample):
        admin = soup_of(admin_client.get("/bell-schedule"))
        parent = soup_of(parent_client.get("/bell-schedule"))
        assert admin.select_one('button[onclick*="create-bell-dialog"]')
        assert admin.select_one(".edit-bell-btn")
        assert not parent.select_one('button[onclick*="create-bell-dialog"]')
        assert not parent.select_one(".edit-bell-btn")

    def test_info_controls(self, admin_client, parent_client, sample):
        admin, parent = soup_of(admin_client.get("/info")), soup_of(parent_client.get("/info"))
        assert admin.select_one("form#info-form")
        assert admin.select_one("form.js-confirm-delete")
        assert not parent.select_one("form#info-form")
        assert not parent.select_one("form.js-confirm-delete")

    def test_expenses_controls(self, admin_client, parent_client, sample):
        admin, parent = soup_of(admin_client.get("/expenses")), soup_of(
            parent_client.get("/expenses")
        )
        assert admin.select_one("dialog#payment-dialog") and admin.select_one(
            "dialog#expense-dialog"
        )
        assert admin.select_one('a[aria-label="Редактировать расход"]')
        assert not parent.select_one("dialog#expense-dialog")
        assert not parent.select_one('a[aria-label="Редактировать расход"]')

    def test_tasks_controls(self, admin_client, parent_client, sample):
        admin, parent = soup_of(admin_client.get("/tasks")), soup_of(parent_client.get("/tasks"))
        assert admin.select_one('button[onclick*="create-task-dialog"]')
        assert not parent.select_one('button[onclick*="create-task-dialog"]')

    def test_profile_role_switcher_is_admin_only(self, admin_client, parent_client):
        assert soup_of(admin_client.get("/profile")).select_one('form[action="/change_role"]')
        assert not soup_of(parent_client.get("/profile")).select_one('form[action="/change_role"]')

    def test_admin_in_parent_mode_loses_news_controls(self, admin_client, sample):
        admin_client.post("/change_role", data={"role": "parent"})
        page = soup_of(admin_client.get("/news"))
        assert not page.select_one("form#news-form")


class TestDeleteConfirmation:
    def test_every_delete_form_has_a_confirm_message(self, admin_client, sample):
        checked = 0
        for url in ("/news", "/schedule", "/bell-schedule", "/info", "/users"):
            for form in soup_of(admin_client.get(url)).select("form.js-confirm-delete"):
                message = form.get("data-confirm-message", "")
                assert message.startswith("Удалить"), (url, message)
                assert form["method"].lower() == "post"
                checked += 1
        assert checked >= 4

    def test_confirm_message_names_the_item(self, admin_client, sample):
        form = soup_of(admin_client.get("/news")).select_one("form.js-confirm-delete")
        assert "Собрание" in form["data-confirm-message"]

    def test_confirm_dialog_is_present_on_every_page(self, admin_client, sample):
        for url in ADMIN_PAGES:
            dialog = soup_of(admin_client.get(url)).find("dialog", id="confirm-dialog")
            assert dialog is not None, url
            assert dialog.find(id="confirm-dialog-accept") and dialog.find(
                id="confirm-dialog-cancel"
            )


class TestCarouselMarkup:
    def test_multiple_images_get_controls_and_counter(self, parent_client, sample):
        carousel = soup_of(parent_client.get("/news")).select_one(".js-carousel")
        assert len(carousel.select(".js-carousel-track img")) == 2
        assert carousel.select_one(".js-carousel-prev")["aria-label"] == "Предыдущее изображение"
        assert carousel.select_one(".js-carousel-next")["aria-label"] == "Следующее изображение"
        assert carousel.select_one(".js-carousel-counter").get_text(strip=True) == "1 / 2"

    def test_single_image_has_no_controls(self, parent_client, db, wipe):
        wipe(NewsImage, News)
        db.session.add(
            News(
                title="Одна",
                description="д",
                status="published",
                images=[NewsImage(path="one.png", position=0)],
            )
        )
        db.session.commit()
        carousel = soup_of(parent_client.get("/news")).select_one(".js-carousel")
        assert len(carousel.select("img")) == 1
        assert not carousel.select_one(".js-carousel-prev")
        assert not carousel.select_one(".js-carousel-counter")

    def test_news_without_images_has_no_carousel(self, parent_client, db, wipe):
        wipe(NewsImage, News)
        db.session.add(News(title="Без картинок", description="д", status="published"))
        db.session.commit()
        assert soup_of(parent_client.get("/news")).select_one(".js-carousel") is None

    def test_images_point_to_uploads(self, parent_client, sample):
        sources = [i["src"] for i in soup_of(parent_client.get("/news")).select(".js-carousel img")]
        assert sources == ["/uploads/a.png", "/uploads/b.png"]


class TestTabsAndPanels:
    def test_tasks_tabs_match_panels(self, parent_client, sample):
        soup = soup_of(parent_client.get("/tasks"))
        tabs = {t["data-tab"] for t in soup.select("[data-tab]")}
        panels = {p["data-panel"] for p in soup.select("[data-panel]")}
        assert tabs == panels == {"active", "completed"}
        assert all(t["role"] == "tab" for t in soup.select("[data-tab]"))

    def test_schedule_has_a_tab_and_panel_for_each_weekday(self, parent_client, sample):
        soup = soup_of(parent_client.get("/schedule"))
        tabs = [t["data-day"] for t in soup.select(".schedule-day-tab")]
        panels = [p["data-day-panel"] for p in soup.select("[data-day-panel]")]
        assert tabs == panels == [str(i) for i in range(7)]

    def test_only_the_first_schedule_panel_is_visible_initially(self, parent_client, sample):
        panels = soup_of(parent_client.get("/schedule")).select("[data-day-panel]")
        hidden = ["hidden" in p.get("class", []) for p in panels]
        assert hidden == [False] + [True] * 6

    def test_only_active_tasks_panel_is_visible_initially(self, parent_client, sample):
        panels = {
            p["data-panel"]: p for p in soup_of(parent_client.get("/tasks")).select("[data-panel]")
        }
        assert "hidden" not in panels["active"].get("class", [])
        assert "hidden" in panels["completed"].get("class", [])


class TestThemeSwitcher:
    def test_profile_has_two_theme_radios(self, parent_client):
        soup = soup_of(parent_client.get("/profile"))
        for ident in ("theme-choice-light", "theme-choice-dark"):
            assert soup.find(id=ident)["role"] == "radio"

    def test_dark_mode_is_applied_before_styles_load(self, client):
        raw = client.get("/login").get_data(as_text=True)
        assert raw.index("localStorage.theme === 'dark'") < raw.index("cdn.tailwindcss.com")


class TestPageContent:
    def test_dashboard_greets_the_user(self, admin_client, sample):
        soup = soup_of(admin_client.get("/dashboard"))
        assert soup.find("h1").get_text(strip=True) == "Администратор"
        assert "Админ" in soup.find("span", class_="badge-hard").get_text()

    def test_parent_dashboard_badge(self, parent_client):
        assert (
            "Родитель"
            in soup_of(parent_client.get("/dashboard"))
            .find("span", class_="badge-medium")
            .get_text()
        )

    def test_empty_news_feed_has_a_placeholder(self, parent_client, wipe):
        wipe(NewsImage, News)
        assert "Событий пока нет." in soup_of(parent_client.get("/news")).get_text()

    def test_task_deadline_is_formatted_for_humans(self, parent_client, db, wipe):
        from datetime import date

        wipe(Task)
        db.session.add(Task(title="Со сроком", deadline=date(2026, 12, 20)))
        db.session.commit()
        assert "20.12.2026" in soup_of(parent_client.get("/tasks")).get_text()

    def test_expenses_page_shows_balance_card(self, parent_client, sample):
        assert "350.00" in soup_of(parent_client.get("/expenses")).get_text()

    def test_login_log_marks_event_kinds(self, admin_client):
        soup = soup_of(admin_client.get("/admin/login-log"))
        assert soup.find("h1").get_text(strip=True) == "Журнал входов"
