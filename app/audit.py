"""Аудит входов и действий пользователей.

События пишутся структурным JSON в основной лог приложения (поле ``event``),
откуда их собирает promtail → Loki. Пароли, тела запросов и полные номера
телефонов в лог не попадают.
"""

from flask import current_app, request, session

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


def audit(event, **fields):
    """Пишет событие аудита в лог приложения."""
    current_app.logger.info(
        "audit: %s",
        event,
        extra={
            "event": event,
            "ip": client_ip(),
            "user_agent": (request.user_agent.string or "")[:200],
            **fields,
        },
    )


def audit_login(success, phone, user=None, reason=None, channel="web"):
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
