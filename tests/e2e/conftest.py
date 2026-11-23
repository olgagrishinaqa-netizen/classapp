"""Инфраструктура браузерных тестов (Playwright + Chromium).

Каждый тест получает собственный сервер приложения на свободном порту и новую
SQLite-базу, поэтому тесты не влияют друг на друга. Сторонние ресурсы (Tailwind CDN,
Google Fonts) подменяются заглушками, так что тесты работают без интернета."""

import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from werkzeug.serving import make_server

from app import create_app
from app.extensions import db

# Без установленного Playwright (обычная задача test в CI) браузерные тесты не собираются.
try:
    import playwright  # noqa: F401
except ImportError:
    collect_ignore_glob = ["test_*.py"]

ADMIN_DIGITS = "290000000"  # телефон администратора без кода страны: +375 (29) 000-00-00
ADMIN_PASSWORD = "admin123"

# Заглушка вместо https://cdn.tailwindcss.com: объявляет tailwind (его использует base.html)
# и добавляет несколько утилитных классов, без которых не работают скрытие и карусель.
TAILWIND_STUB = (
    "window.tailwind = {};"
    "(function () { var s = document.createElement('style');"
    "s.textContent = '.hidden{display:none!important}.flex{display:flex}.w-full{width:100%}"
    ".shrink-0{flex-shrink:0}.overflow-x-auto{overflow-x:auto}.overflow-hidden{overflow:hidden}"
    ".relative{position:relative}.scroll-smooth{scroll-behavior:smooth}"
    ".h-56{height:14rem}.h-64{height:16rem}';"
    "document.head.appendChild(s); })();"
)


@pytest.fixture()
def live_server(tmp_path):
    """Приложение, запущенное в потоке на 127.0.0.1:<свободный порт>, с включённым CSRF."""
    from config import BaseConfig

    uploads = tmp_path / "uploads"
    uploads.mkdir()

    class E2EConfig(BaseConfig):
        TESTING = True
        DEBUG = False
        SECRET_KEY = "e2e-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'e2e.db'}"
        APP_JSON_LOG_PATH = str(tmp_path / "app.json.log")
        UPLOAD_FOLDER = str(uploads)
        WTF_CSRF_ENABLED = True

    application = create_app(E2EConfig)
    server = make_server("127.0.0.1", 0, application, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield SimpleNamespace(
        url=f"http://127.0.0.1:{server.server_port}", app=application, uploads=uploads
    )
    server.shutdown()
    thread.join(timeout=5)
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Сохраняет результат каждой фазы теста, чтобы фикстура page знала, упал ли тест."""
    outcome = yield
    setattr(item, f"rep_{call.when}", outcome.get_result())


@pytest.fixture(scope="session")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch()
        except Exception as error:  # noqa: BLE001 - браузер не установлен
            pytest.skip(
                f"Chromium недоступен ({error.__class__.__name__}); playwright install chromium"
            )
        yield chromium
        chromium.close()


@pytest.fixture()
def page(browser, live_server, request):
    """Страница мобильного размера (интерфейс mobile-first). После теста проверяется,
    что в консоли браузера не было JavaScript-ошибок; при падении теста сохраняется
    скриншот в reports/e2e-failures/ (в CI попадает в артефакты)."""
    from playwright.sync_api import expect

    expect.set_options(timeout=5000)
    context = browser.new_context(
        locale="ru-RU", viewport={"width": 390, "height": 844}, base_url=live_server.url
    )
    local = re.compile(r"^http://127\.0\.0\.1[:/]")

    def stub_external(route):
        if "tailwindcss" in route.request.url:
            route.fulfill(status=200, content_type="application/javascript", body=TAILWIND_STUB)
        else:
            route.abort()

    context.route(lambda url: not local.match(url), stub_external)
    tab = context.new_page()
    tab.set_default_timeout(5000)
    errors = []
    tab.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    tab.on(
        "console",
        lambda message: message.type == "error"
        and "Failed to load resource" not in message.text
        and errors.append(f"console.error: {message.text}"),
    )
    tab.js_errors = errors
    yield tab
    report = getattr(request.node, "rep_call", None)
    if report is not None and report.failed:
        folder = Path("reports") / "e2e-failures"
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^\w.-]+", "_", request.node.nodeid)
        tab.screenshot(path=str(folder / f"{name}.png"), full_page=True)
    context.close()
    assert not errors, "JavaScript-ошибки в браузере:\n" + "\n".join(errors)


@pytest.fixture()
def login(page):
    """login(digits, password) — вход через форму, ввод номера клавишами (работает маска)."""

    def _login(digits=ADMIN_DIGITS, password=ADMIN_PASSWORD):
        page.goto("/login")
        page.locator("#phone-input").press_sequentially(digits)
        page.locator("#password-input").fill(password)
        page.get_by_role("button", name="Войти").click()

    return _login


@pytest.fixture()
def admin_page(page, login):
    """Страница, на которой уже выполнен вход администратора."""
    login()
    page.wait_for_url("**/dashboard")
    return page


@pytest.fixture()
def seed(live_server):
    """seed(fn) — выполняет fn(db) в контексте приложения и сохраняет изменения."""

    def _seed(function):
        with live_server.app.app_context():
            result = function(db)
            db.session.commit()
            return result

    return _seed
