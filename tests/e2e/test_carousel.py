"""Карусель изображений в новостях: кнопки, счётчик, переход по кругу."""

import base64

import pytest
from playwright.sync_api import expect

from app.models import News, NewsImage

pytestmark = pytest.mark.e2e

# Минимальный валидный PNG 1×1, чтобы браузер не показывал битые картинки.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


@pytest.fixture()
def gallery(seed, live_server):
    """Новость с тремя картинками (файлы лежат в UPLOAD_FOLDER тестового приложения)."""
    for name in ("one.png", "two.png", "three.png"):
        (live_server.uploads / name).write_bytes(PNG)

    def create(db):
        db.session.add(
            News(
                title="Фотоотчёт",
                description="Поездка",
                status="published",
                images=[
                    NewsImage(path=n, position=i)
                    for i, n in enumerate(("one.png", "two.png", "three.png"))
                ],
            )
        )

    seed(create)


@pytest.fixture()
def carousel(admin_page, gallery):
    admin_page.goto("/news")
    box = admin_page.locator(".js-carousel")
    expect(box).to_be_visible()
    return box


def counter(box):
    return box.locator(".js-carousel-counter")


class TestCarousel:
    def test_starts_on_the_first_slide(self, carousel):
        expect(counter(carousel)).to_have_text("1 / 3")
        expect(carousel.locator("img")).to_have_count(3)

    def test_images_are_loaded(self, carousel, admin_page):
        admin_page.wait_for_load_state("load")
        loaded = carousel.locator("img").evaluate_all("imgs => imgs.map(i => i.naturalWidth > 0)")
        assert loaded == [True, True, True]

    def test_next_button_advances_the_counter(self, carousel):
        carousel.get_by_label("Следующее изображение").click()
        expect(counter(carousel)).to_have_text("2 / 3")
        carousel.get_by_label("Следующее изображение").click()
        expect(counter(carousel)).to_have_text("3 / 3")

    def test_next_wraps_around_to_the_first_slide(self, carousel):
        for expected in ("2 / 3", "3 / 3", "1 / 3"):
            carousel.get_by_label("Следующее изображение").click()
            expect(counter(carousel)).to_have_text(expected)

    def test_previous_wraps_around_to_the_last_slide(self, carousel):
        carousel.get_by_label("Предыдущее изображение").click()
        expect(counter(carousel)).to_have_text("3 / 3")
        carousel.get_by_label("Предыдущее изображение").click()
        expect(counter(carousel)).to_have_text("2 / 3")

    def test_track_scrolls_by_exactly_one_slide(self, carousel, admin_page):
        carousel.get_by_label("Следующее изображение").click()
        # Прокрутка плавная: ждём, пока лента дойдёт ровно до второго слайда.
        admin_page.wait_for_function(
            """() => { const t = document.querySelector('.js-carousel-track');
                       return Math.abs(t.scrollLeft - t.clientWidth) < 1; }"""
        )
        expect(counter(carousel)).to_have_text("2 / 3")

    def test_manual_scroll_updates_the_counter(self, carousel):
        carousel.locator(".js-carousel-track").evaluate(
            "t => { t.scrollLeft = 2 * t.clientWidth; }"
        )
        expect(counter(carousel)).to_have_text("3 / 3")


class TestSingleImage:
    def test_no_controls_for_a_single_image(self, admin_page, seed, live_server):
        (live_server.uploads / "solo.png").write_bytes(PNG)
        seed(
            lambda db: db.session.add(
                News(
                    title="Одна",
                    description="д",
                    status="published",
                    images=[NewsImage(path="solo.png", position=0)],
                )
            )
        )
        admin_page.goto("/news")
        expect(admin_page.locator(".js-carousel img")).to_have_count(1)
        expect(admin_page.get_by_label("Следующее изображение")).to_have_count(0)
        expect(admin_page.locator(".js-carousel-counter")).to_have_count(0)
