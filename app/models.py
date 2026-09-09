from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(32), unique=True, nullable=False, index=True)
    role = db.Column(db.String(32), nullable=False, default="parent")
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"


class ExpenseReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    income = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    expense_items = db.Column(db.JSON, nullable=False, default=list)
    receipt_name = db.Column(db.String(255))
    receipt_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def total_expenses(self):
        return sum(float(item.get("amount", 0)) for item in (self.expense_items or []))

    @property
    def balance(self):
        return float(self.income) - self.total_expenses


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(20), nullable=False, default="created")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class TaskComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
