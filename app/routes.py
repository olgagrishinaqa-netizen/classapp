import json
import os
from functools import wraps
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory, session
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from .extensions import db
from .models import ExpenseReport, News, Task, User

bp = Blueprint("main", __name__)

STATUS_LABELS = {"created": "Создана", "in_progress": "В работе", "done": "Сделано"}
ROLE_LABELS = {"parent": "Родитель", "student": "Ученик", "admin": "Админ"}


def current_user():
    user_id = session.get("user_id")
    return db.session.get(User, user_id) if user_id else None


def auth_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return jsonify(error="Требуется авторизация"), 401
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @auth_required
    def wrapped(*args, **kwargs):
        if not current_user().is_admin:
            return jsonify(error="Доступ только для администратора"), 403
        return view(*args, **kwargs)

    return wrapped


def user_json(user):
    return {
        "id": user.id,
        "full_name": user.full_name,
        "phone": user.phone,
        "role": user.role,
        "role_label": ROLE_LABELS.get(user.role, user.role),
    }


def task_json(task):
    return {"id": task.id, "title": task.title, "description": task.description or "", "status": task.status, "status_label": STATUS_LABELS[task.status], "created_at": task.created_at.strftime("%d.%m.%Y")}


def news_json(news):
    return {
        "id": news.id,
        "title": news.title,
        "description": news.description or "",
        "status": news.status,
        "image_url": news.image_url,
        "created_at": news.created_at.strftime("%d.%m.%Y %H:%M"),
        "updated_at": news.updated_at.strftime("%d.%m.%Y %H:%M"),
    }


@bp.get("/")
def index():
    return render_template("index.html")


@bp.post("/api/login")
def login():
    data = request.get_json(silent=True)
    if data is None:
        data = request.form or {}
    phone = User.normalize_phone(data.get("phone"))
    user = User.query.filter_by(phone=phone).first()
    if not user or not user.check_password(data.get("password") or ""):
        return jsonify(error="Неверный телефон или пароль"), 401
    session["user_id"] = user.id
    session["active_role"] = "admin" if user.is_admin else user.role
    return jsonify(user=user_json(user), active_role=session["active_role"])


@bp.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.get("/api/me")
def me():
    user = current_user()
    if not user:
        return jsonify(user=None)
    return jsonify(user=user_json(user), active_role=session.get("active_role", user.role))


@bp.post("/api/role")
@auth_required
def switch_role():
    user = current_user()
    role = (request.get_json(silent=True) or {}).get("role")
    if role not in {"admin", "parent"} or (role == "admin" and not user.is_admin):
        return jsonify(error="Недопустимая роль"), 400
    session["active_role"] = role
    return jsonify(active_role=role)


@bp.get("/api/users")
@admin_required
def users():
    return jsonify(users=[user_json(user) for user in User.query.order_by(User.created_at.desc()).all()])


@bp.post("/api/users")
@admin_required
def create_user():
    data = request.form if request.form else (request.get_json(silent=True) or {})
    required = ["full_name", "phone", "role", "password"]
    cleaned = {field: str(data.get(field, "") or "").strip() for field in required}
    if any(not value for value in cleaned.values()):
        return jsonify(error="Заполните все обязательные поля"), 400

    role_aliases = {"parent": "parent", "родитель": "parent", "student": "student", "ученик": "student"}
    role = role_aliases.get(cleaned["role"].lower(), cleaned["role"]) if cleaned["role"] else ""
    if role not in {"parent", "student"}:
        return jsonify(error="Роль должна быть Родитель или Ученик"), 400

    normalized_phone = User.normalize_phone(cleaned["phone"])
    if not normalized_phone:
        return jsonify(error="Введите корректный номер телефона"), 400
    user = User(full_name=cleaned["full_name"], phone=normalized_phone, role=role)
    user.set_password(cleaned["password"])
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="Такой номер телефона уже используется"), 409
    return jsonify(user=user_json(user)), 201


@bp.put("/api/users/<int:user_id>")
@admin_required
def update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify(error="Пользователь не найден"), 404
    data = request.get_json(silent=True) or {}
    for field in ("full_name", "role"):
        if field in data and str(data[field]).strip():
            setattr(user, field, str(data[field]).strip())
    if "phone" in data and str(data["phone"]).strip():
        normalized_phone = User.normalize_phone(data["phone"])
        if not normalized_phone:
            return jsonify(error="Введите корректный номер телефона"), 400
        user.phone = normalized_phone
    if data.get("password"):
        user.set_password(data["password"])
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="Такой номер телефона уже используется"), 409
    return jsonify(user=user_json(user))


@bp.get("/api/news")
@auth_required
def news():
    user = current_user()
    query = News.query.order_by(News.created_at.desc())
    if not user or not user.is_admin:
        query = query.filter_by(status="published")
    return jsonify(news=[news_json(item) for item in query.all()])


@bp.post("/api/news")
@admin_required
def create_news():
    data = request.form if request.form else (request.get_json(silent=True) or {})
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    status = (data.get("status") or "draft").strip()
    if not title or not description:
        return jsonify(error="Укажите заголовок и описание новости"), 400
    if status not in {"draft", "published"}:
        return jsonify(error="Некорректный статус новости"), 400

    image = request.files.get("image") if hasattr(request, "files") else None
    image_name = None
    image_path = None
    if image and image.filename:
        image_name = secure_filename(image.filename)
        image_path = f"{uuid4().hex}_{image_name}"
        upload_folder = current_app.config.get("UPLOAD_FOLDER", os.path.join(os.getcwd(), "uploads"))
        os.makedirs(upload_folder, exist_ok=True)
        image.save(os.path.join(upload_folder, image_path))

    news_item = News(title=title, description=description, status=status, image_name=image_name, image_path=image_path)
    db.session.add(news_item)
    db.session.commit()
    return jsonify(news=news_json(news_item)), 201


@bp.patch("/api/news/<int:news_id>")
@admin_required
def update_news(news_id):
    news_item = db.session.get(News, news_id)
    if not news_item:
        return jsonify(error="Новость не найдена"), 404

    data = request.form if request.form else (request.get_json(silent=True) or {})
    if "title" in data and str(data.get("title") or "").strip():
        news_item.title = str(data["title"]).strip()
    if "description" in data and str(data.get("description") or "").strip():
        news_item.description = str(data["description"]).strip()
    if "status" in data and str(data.get("status") or "").strip() in {"draft", "published"}:
        news_item.status = str(data["status"]).strip()

    image = request.files.get("image") if hasattr(request, "files") else None
    if image and image.filename:
        image_name = secure_filename(image.filename)
        image_path = f"{uuid4().hex}_{image_name}"
        upload_folder = current_app.config.get("UPLOAD_FOLDER", os.path.join(os.getcwd(), "uploads"))
        os.makedirs(upload_folder, exist_ok=True)
        image.save(os.path.join(upload_folder, image_path))
        news_item.image_name = image_name
        news_item.image_path = image_path

    db.session.commit()
    return jsonify(news=news_json(news_item))


@bp.get("/api/tasks")
@auth_required
def tasks():
    return jsonify(tasks=[task_json(task) for task in Task.query.order_by(Task.created_at.desc()).all()])


@bp.post("/api/tasks")
@admin_required
def create_task():
    data = request.get_json(silent=True) or {}
    if not (data.get("title") or "").strip():
        return jsonify(error="Укажите название задачи"), 400
    task = Task(title=data["title"].strip(), description=(data.get("description") or "").strip())
    db.session.add(task)
    db.session.commit()
    return jsonify(task=task_json(task)), 201


@bp.patch("/api/tasks/<int:task_id>")
@admin_required
def update_task(task_id):
    task = db.session.get(Task, task_id)
    data = request.get_json(silent=True) or {}
    if not task or data.get("status") not in STATUS_LABELS:
        return jsonify(error="Задача или статус не найдены"), 404
    task.status = data["status"]
    db.session.commit()
    return jsonify(task=task_json(task))


@bp.get("/api/reports")
@admin_required
def reports():
    reports_data = []
    for report in ExpenseReport.query.order_by(ExpenseReport.created_at.desc()).all():
        reports_data.append({"id": report.id, "income": float(report.income), "items": report.expense_items or [], "total_expenses": report.total_expenses, "balance": report.balance, "receipt_name": report.receipt_name})
    return jsonify(reports=reports_data)


@bp.post("/api/reports")
@admin_required
def create_report():
    try:
        income = float(request.form.get("income", "0"))
        items = json.loads(request.form.get("items", "[]"))
    except (TypeError, ValueError):
        return jsonify(error="Проверьте суммы"), 400
    if income < 0 or not isinstance(items, list):
        return jsonify(error="Некорректные данные отчетности"), 400
    normalized = []
    for item in items:
        try:
            amount = float(item.get("amount", 0))
            if not item.get("title") or amount < 0:
                raise ValueError
            normalized.append({"title": item["title"].strip(), "amount": amount})
        except (AttributeError, TypeError, ValueError):
            return jsonify(error="Каждая статья должна иметь название и сумму"), 400
    receipt = request.files.get("receipt")
    receipt_name = None
    receipt_path = None
    if receipt and receipt.filename:
        receipt_name = secure_filename(receipt.filename)
        receipt_path = f"{uuid4().hex}_{receipt_name}"
        upload_folder = current_app.config.get("UPLOAD_FOLDER", os.path.join(os.getcwd(), "uploads"))
        os.makedirs(upload_folder, exist_ok=True)
        receipt.save(os.path.join(upload_folder, receipt_path))
    report = ExpenseReport(income=income, expense_items=normalized, receipt_name=receipt_name, receipt_path=receipt_path)
    db.session.add(report)
    db.session.commit()
    return jsonify(report={"income": income, "items": normalized, "total_expenses": report.total_expenses, "balance": report.balance}), 201


@bp.get("/uploads/<path:filename>")
def uploaded_file(filename):
    upload_folder = current_app.config.get("UPLOAD_FOLDER", os.path.join(os.getcwd(), "uploads"))
    return send_from_directory(upload_folder, filename)
