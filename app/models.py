"""ORM-модели classapp: пользователи и роли, задачи, новости, учёт взносов
и расходов класса, состав учеников."""

import re
from datetime import datetime

from flask_login import UserMixin
from sqlalchemy.orm import validates
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def local_now():
    """Return the local time configured for the application server."""
    return datetime.now()


class User(UserMixin, db.Model):
    """Учётная запись: родитель, ученик или администратор. Пароль хранится
    только в виде хэша (werkzeug scrypt), телефон — уникальный логин."""

    @staticmethod
    def normalize_phone(raw_phone):
        if raw_phone is None:
            return ""
        digits = re.sub(r"\D+", "", str(raw_phone))
        if not digits:
            return ""
        if digits.startswith("8") and len(digits) == 11:
            digits = "7" + digits[1:]
        return digits

    @validates("phone")
    def validate_phone(self, key, value):
        return self.normalize_phone(value)

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(32), unique=True, nullable=False, index=True)
    role = db.Column(db.String(32), nullable=False, default="parent")
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        try:
            return check_password_hash(self.password_hash, password)
        except (TypeError, ValueError):
            # Invalid legacy hashes must behave like an incorrect password.
            return False

    @property
    def is_admin(self):
        return self.role == "admin"


class ExpenseReport(db.Model):
    """Сводный финансовый отчёт (доход + список статей расходов одним JSON-блобом)."""

    id = db.Column(db.Integer, primary_key=True)
    income = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    expense_items = db.Column(db.JSON, nullable=False, default=list)
    receipt_name = db.Column(db.String(255))
    receipt_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)

    @property
    def total_expenses(self):
        return sum(float(item.get("amount", 0)) for item in (self.expense_items or []))

    @property
    def balance(self):
        return float(self.income) - self.total_expenses


class Payment(db.Model):
    """Взнос в бюджет класса от конкретного ученика."""

    __tablename__ = "payment"

    id = db.Column(db.Integer, primary_key=True)
    # user_id — устаревшее поле (взносы раньше привязывались к учётной записи
    # родителя); оставлено nullable для старых записей, новые взносы его не
    # заполняют и привязываются к ученику через student_id.
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=True, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)

    user = db.relationship("User", backref=db.backref("payments", lazy=True))
    student = db.relationship("Student", backref=db.backref("payments", lazy=True))

    @property
    def payer_name(self):
        if self.student:
            return self.student.full_name
        if self.user:
            return self.user.full_name
        return "—"


class Expense(db.Model):
    """Расход из бюджета класса, опционально с приложенным чеком."""

    __tablename__ = "expense"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    category = db.Column(db.String(64), nullable=False, default="Общие")
    receipt_path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)

    @property
    def receipt_url(self):
        if not self.receipt_path:
            return None
        return f"/static/uploads/receipts/{self.receipt_path}"


class Task(db.Model):
    """Задача/поручение класса со статусом created/in_progress/done и
    приоритетом low/medium/high (влияет на сортировку активных задач)."""

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, default="")
    deadline = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="created")
    priority = db.Column(db.String(10), nullable=False, default="medium")
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)


class News(db.Model):
    """Новость с черновым/опубликованным статусом и несколькими картинками."""

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="draft")
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=local_now, onupdate=local_now, nullable=False)
    images = db.relationship(
        "NewsImage",
        backref="news",
        cascade="all, delete-orphan",
        order_by="NewsImage.position, NewsImage.id",
    )

    @property
    def image_urls(self):
        return [image.url for image in self.images]

    @property
    def image_url(self):
        """URL первой картинки (обложка) либо None."""
        return self.images[0].url if self.images else None


class NewsImage(db.Model):
    """Изображение, прикреплённое к новости."""

    __tablename__ = "news_image"

    id = db.Column(db.Integer, primary_key=True)
    news_id = db.Column(db.Integer, db.ForeignKey("news.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(255))
    path = db.Column(db.String(255), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)

    @property
    def url(self):
        return f"/uploads/{self.path}"


class LoginEvent(db.Model):
    """Журнал входов/выходов/регистраций для страницы администратора.
    user_id без внешнего ключа: история сохраняется после удаления пользователя."""

    __tablename__ = "login_event"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=local_now, nullable=False, index=True)
    event = db.Column(db.String(30), nullable=False, index=True)
    user_id = db.Column(db.Integer, index=True)
    phone = db.Column(db.String(20))  # замаскирован: ***1234
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    channel = db.Column(db.String(10))
    reason = db.Column(db.String(30))


class ScheduleEntry(db.Model):
    """Урок в недельном расписании класса. Управление доступно только
    администратору, остальные пользователи — только просмотр."""

    __tablename__ = "schedule_entry"
    __table_args__ = (
        db.UniqueConstraint("day_of_week", "lesson_number", name="uq_schedule_day_lesson"),
    )

    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Понедельник .. 6=Воскресенье
    lesson_number = db.Column(db.Integer, nullable=False)
    subject = db.Column(db.String(120), nullable=False)
    teacher = db.Column(db.String(120), nullable=True)
    room = db.Column(db.String(40), nullable=True)
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)


class BellScheduleEntry(db.Model):
    """Строка расписания звонков: номер урока и время начала/конца.
    Управление доступно только администратору."""

    __tablename__ = "bell_schedule_entry"

    id = db.Column(db.Integer, primary_key=True)
    lesson_number = db.Column(db.Integer, nullable=False, unique=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)


class GeneralInfo(db.Model):
    """Запись общей информации класса: описание и опциональный прикреплённый
    файл (изображение, PDF, документ или таблица). Управление доступно
    только администратору, остальные пользователи — только просмотр."""

    __tablename__ = "general_info"

    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.Text, nullable=False)
    file_name = db.Column(db.String(255))
    file_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=local_now, onupdate=local_now, nullable=False)

    @property
    def file_url(self):
        if not self.file_path:
            return None
        return f"/uploads/{self.file_path}"


class TaskComment(db.Model):
    """Комментарий к задаче (модель не используется UI на текущий момент)."""

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)


class Student(db.Model):
    """Ученик класса. Управление составом доступно только администратору."""

    __tablename__ = "students"
    __table_args__ = (
        db.UniqueConstraint(
            "last_name", "first_name", name="uq_students_last_name_first_name"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    last_name = db.Column(db.String(64), nullable=False, index=True)
    first_name = db.Column(db.String(64), nullable=False, index=True)
    birth_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def full_name(self):
        return f"{self.last_name} {self.first_name}"
