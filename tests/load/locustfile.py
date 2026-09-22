"""Нагрузочный сценарий Locust для classapp.

Логинится под учёткой администратора (JSON API, без CSRF-формы) и
дальше имитирует типичную навигацию: дашборд, список задач, новости.

Запуск (UI):
    locust -f tests/load/locustfile.py --host=http://localhost:8000

Запуск headless (для отчёта/CI):
    locust -f tests/load/locustfile.py --host=http://localhost:8000 \
        --headless -u 20 -r 5 --run-time 1m --csv=load_report

Креды берутся из LOAD_TEST_PHONE/LOAD_TEST_PASSWORD (по умолчанию —
дефолтный bootstrap-админ дев-стенда, см. app/__init__.py).
"""

import os
import random

from locust import HttpUser, between, task

LOGIN_PHONE = os.environ.get("LOAD_TEST_PHONE", "79990000000")
LOGIN_PASSWORD = os.environ.get("LOAD_TEST_PASSWORD", "admin123")


class ClassappUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        with self.client.post(
            "/api/login",
            json={"phone": LOGIN_PHONE, "password": LOGIN_PASSWORD},
            name="/api/login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"login failed: {response.status_code} {response.text}")

    @task(5)
    def view_dashboard(self):
        self.client.get("/dashboard", name="/dashboard")

    @task(4)
    def view_tasks_page(self):
        self.client.get("/tasks", name="/tasks")

    @task(3)
    def list_tasks_api(self):
        self.client.get("/api/tasks", name="/api/tasks")

    @task(3)
    def list_news_api(self):
        self.client.get("/api/news", name="/api/news")

    @task(2)
    def view_expenses_page(self):
        self.client.get("/expenses", name="/expenses")

    @task(1)
    def whoami(self):
        self.client.get("/api/me", name="/api/me")

    @task(1)
    def create_task(self):
        self.client.post(
            "/api/tasks",
            json={"title": f"Load-test task {random.randint(1, 10_000)}"},
            name="/api/tasks [POST]",
        )
