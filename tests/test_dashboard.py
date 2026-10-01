from app.models import NewsImage, Expense, News


def _login_admin(client):
    client.post("/login", data={"username": "79990000000", "password": "admin123"})


def test_dashboard_shows_latest_news_image(client, db):
    _login_admin(client)
    news_item = News(
        title="Дашборд: новость с картинкой",
        description="описание",
        status="published",
        images=[NewsImage(name="photo.png", path="stored-photo.png"), NewsImage(name="b.png", path="stored-b.png")],
    )
    db.session.add(news_item)
    db.session.commit()

    page = client.get("/dashboard")
    assert page.status_code == 200
    assert b'/uploads/stored-photo.png' in page.data
    assert b'/uploads/stored-b.png' in page.data
    assert b'js-carousel-next' in page.data
    assert b'object-contain' in page.data


def test_dashboard_hides_image_block_when_news_has_none(client, db):
    _login_admin(client)
    NewsImage.query.delete()
    db.session.commit()
    db.session.add(News(title="Дашборд: новость без картинки", description="описание", status="published"))
    db.session.commit()

    page = client.get("/dashboard")
    assert page.status_code == 200
    assert b"<img" not in page.data


def test_dashboard_monthly_expenses_use_the_b_currency_symbol(client, db):
    _login_admin(client)
    db.session.add(Expense(title="Тетради", amount=100, category="Учеба"))
    db.session.commit()

    page = client.get("/dashboard")
    assert page.status_code == 200
    html = page.data.decode()
    card_start = html.index("Баланс класса")
    card_end = html.index("Перейти к финансам")
    card_html = html[card_start:card_end]
    assert "₽" not in card_html
    assert ">Б</span>" in card_html
