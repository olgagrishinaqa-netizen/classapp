from app import create_app
from app.models import User


def test_login_accepts_common_phone_formats(client):
    for phone in ["79990000000", "+7 (999) 000-00-00", "89990000000"]:
        response = client.post(
            "/api/login",
            json={"phone": phone, "password": "admin123"},
        )
        assert response.status_code == 200, phone
        payload = response.get_json()
        assert payload["user"]["phone"] == "79990000000"


def test_user_creation_normalizes_phone(db):
    user = User(full_name="Иван Иванов", phone="+7 (999) 123-45-67", role="parent")
    user.set_password("secure-pass")
    db.session.add(user)
    db.session.commit()

    assert user.phone == "79991234567"
    assert User.query.filter_by(phone="79991234567").count() == 1


def test_admin_password_is_reset_to_default_on_bootstrap(tmp_path):
    db_path = tmp_path / "bootstrap-admin.db"

    class BootstrapConfig:
        TESTING = True
        DEBUG = False
        SECRET_KEY = "bootstrap-secret"
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        ADMIN_PHONE = "79990000000"
        ADMIN_NAME = "Администратор"
        ADMIN_PASSWORD = "admin123"

    app = create_app(config_object=BootstrapConfig)
    with app.app_context():
        admin = User.query.filter_by(phone="79990000000").first()
        admin.set_password("wrong-password")
        from app.extensions import db

        db.session.commit()

    app = create_app(config_object=BootstrapConfig)
    with app.app_context():
        admin = User.query.filter_by(phone="79990000000").first()
        assert admin is not None
        assert admin.check_password("admin123")
