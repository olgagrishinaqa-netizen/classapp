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
    __tablename__ = "payment"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)

    user = db.relationship("User", backref=db.backref("payments", lazy=True))


class Expense(db.Model):
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
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(20), nullable=False, default="created")
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)


class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="draft")
    image_name = db.Column(db.String(255))
    image_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=local_now, onupdate=local_now, nullable=False)

    @property
    def image_url(self):
        if not self.image_path:
            return None
        return f"/uploads/{self.image_path}"


class TaskComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=local_now, nullable=False)
