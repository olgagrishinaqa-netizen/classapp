import itertools

import pytest
from _credentials import ADMIN_PASSWORD, ADMIN_PHONE
from _testconfig import TestConfig

from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope="session")
def app():
    application = create_app(config_object=TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        # Тесты читают данные через db.session в этом же контексте и оставляют транзакцию открытой.
        # На PostgreSQL она держит блокировки, и drop_all() зависал бы навсегда (SQLite этого не замечает).
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(autouse=True)
def _clean_session(app):
    """Сессия SQLAlchemy живёт весь прогон (см. fixture app), поэтому после каждого теста
    выбрасываем из неё объекты: SQLite переиспользует id удалённых строк, и «мёртвый»
    объект из прошлого теста ломал бы flush новой записи с тем же id."""
    yield
    _db.session.rollback()
    _db.session.expunge_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    return _db


# Телефоны тестовых пользователей не пересекаются с жёстко заданными в других тестах.
_phone_counter = itertools.count(710000000)


@pytest.fixture()
def upload_dir(app, tmp_path):
    """Подменяет UPLOAD_FOLDER на временный каталог, чтобы тесты не писали в ./uploads."""
    missing = object()
    previous = app.config.get("UPLOAD_FOLDER", missing)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    yield tmp_path
    if previous is missing:
        app.config.pop("UPLOAD_FOLDER", None)
    else:
        app.config["UPLOAD_FOLDER"] = previous


@pytest.fixture()
def login_as():
    """login_as(client, phone, password) — вход через HTML-форму /login."""

    def _login(client, phone, password):
        return client.post("/login", data={"username": phone, "password": password})

    return _login


@pytest.fixture()
def admin_client(app, login_as):
    """Тестовый клиент, уже вошедший как администратор."""
    client = app.test_client()
    login_as(client, ADMIN_PHONE, ADMIN_PASSWORD)
    return client


@pytest.fixture()
def make_user(db):
    """Фабрика пользователей с уникальным телефоном; созданные пользователи
    удаляются после теста, чтобы не влиять на проверки «последнего админа»."""
    from app.models import User

    created = []

    def _make(role="parent", password="secret123", full_name="Тестовый Пользователь"):
        user = User(full_name=full_name, phone=f"375{next(_phone_counter)}", role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        user.plain_password = password
        created.append(user.id)
        return user

    yield _make

    db.session.rollback()
    for user_id in created:
        user = db.session.get(User, user_id)
        if user is not None:
            db.session.delete(user)
    db.session.commit()


@pytest.fixture()
def parent_client(app, make_user, login_as):
    """Клиент, вошедший как обычный родитель (не администратор)."""
    user = make_user(role="parent")
    client = app.test_client()
    login_as(client, user.phone, user.plain_password)
    client.user = user
    return client


@pytest.fixture()
def wipe(db):
    """wipe(Model, ...) — удаляет все строки таблиц (порядок = порядок аргументов).

    Очистка повторяется после теста: БД общая на весь прогон, и строки, оставленные
    здесь, ломали бы более старые тесты, которые рассчитывают на «чистые» таблицы."""
    wiped = []

    def _wipe(*models):
        db.session.rollback()
        for model in models:
            db.session.query(model).delete()
        db.session.commit()
        wiped.append(models)

    yield _wipe

    db.session.rollback()
    for models in wiped:
        for model in models:
            db.session.query(model).delete()
    db.session.commit()
