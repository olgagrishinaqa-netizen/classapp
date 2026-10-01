"""Аудит входов и действий пользователей.

События пишутся структурным JSON в основной лог приложения (поле ``event``),
откуда их собирает promtail → Loki. Пароли, тела запросов и полные номера
телефонов в лог не попадают.
"""

from flask import current_app, request, session
from prometheus_client import Counter

LOGIN_ATTEMPTS = Counter(
    "classapp_login_attempts_total",
    "Попытки входа в приложение",
    ["result", "channel"],
)
USER_ACTIONS = Counter(
    "classapp_user_actions_total",
    "Изменяющие действия пользователей",
    ["endpoint", "status_class"],
)
REGISTRATIONS = Counter("classapp_registrations_total", "Успешные регистрации")

# Эндпоинты, которые аудитируются явно (с причиной/результатом), а не общим хуком.
EXPLICIT_ENDPOINTS = {
    "main.login_page",
    "main.register_page",
    "main.logout_page",
    "main.login",
    "main.logout",
}


def client_ip():
    """IP клиента. nginx перезаписывает X-Real-IP значением $remote_addr,
    поэтому заголовок нельзя подделать снаружи."""
    return request.headers.get("X-Real-IP") or request.remote_addr


def mask_phone(phone):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return f"***{digits[-4:]}" if digits else None


PERSISTED_EVENTS = {"login_success", "login_failed", "logout", "register", "register_rejected"}


def _store_event(event, ip, user_agent, fields):
    """Сохраняет событие в БД для страницы «Журнал входов». Сбой записи не
    должен ломать вход пользователя: ошибка только логируется."""
    from .extensions import db
    from .models import LoginEvent

    try:
        db.session.add(
            LoginEvent(
                event=event,
                user_id=fields.get("user_id"),
                phone=fields.get("phone"),
                ip=ip,
                user_agent=user_agent,
                channel=fields.get("channel"),
                reason=fields.get("reason"),
            )
        )
        db.session.commit()
    except Exception:  # noqa: BLE001 - журнал не должен ломать запрос
        db.session.rollback()
        current_app.logger.exception("Не удалось сохранить событие %s в login_event", event)


def audit(event, **fields):
    """Пишет событие аудита в лог приложения (и в БД для событий входа)."""
    user_agent = (request.user_agent.string or "")[:200]
    if event in PERSISTED_EVENTS:
        _store_event(event, client_ip(), user_agent, fields)
    current_app.logger.info(
        "audit: %s",
        event,
        extra={
            "event": event,
            "ip": client_ip(),
            "user_agent": user_agent,
            **fields,
        },
    )


def audit_login(success, phone, user=None, reason=None, channel="web"):
    LOGIN_ATTEMPTS.labels(result="success" if success else "failure", channel=channel).inc()
    audit(
        "login_success" if success else "login_failed",
        user_id=user.id if user else None,
        phone=mask_phone(phone),
        reason=reason,
        channel=channel,
    )


def register_request_audit(app):
    """Общий хук: логирует каждое изменяющее запрос-действие (POST/PUT/PATCH/
    DELETE) с пользователем, ролью, эндпоинтом и статусом ответа."""

    @app.after_request
    def audit_state_changing_requests(response):
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return response
        if request.endpoint in EXPLICIT_ENDPOINTS or request.endpoint is None:
            return response
        USER_ACTIONS.labels(
            endpoint=request.endpoint, status_class=f"{response.status_code // 100}xx"
        ).inc()
        audit(
            "action",
            user_id=session.get("user_id"),
            role=session.get("active_role"),
            method=request.method,
            endpoint=request.endpoint,
            request_path=request.path,
            status=response.status_code,
        )
        return response


def describe_device(user_agent):
    """Короткое описание устройства по User-Agent: «Android · Chrome»."""
    ua = user_agent or ""
    system = next(
        (
            name
            for marker, name in (
                ("Android", "Android"),
                ("iPhone", "iPhone"),
                ("iPad", "iPad"),
                ("Windows", "Windows"),
                ("Macintosh", "macOS"),
                ("Linux", "Linux"),
            )
            if marker in ua
        ),
        None,
    )
    browser = next(
        (
            name
            for marker, name in (
                ("Edg/", "Edge"),
                ("OPR/", "Opera"),
                ("YaBrowser", "Яндекс Браузер"),
                ("Firefox/", "Firefox"),
                ("Chrome/", "Chrome"),
                ("Safari/", "Safari"),
            )
            if marker in ua
        ),
        None,
    )
    return " · ".join(part for part in (system, browser) if part) or "Неизвестное устройство"
