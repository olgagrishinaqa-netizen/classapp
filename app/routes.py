import json
import os
from datetime import datetime, timezone
from functools import wraps
from uuid import uuid4

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from sqlalchemy import case
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from .extensions import db
from .forms import (
    ExpenseForm,
    LoginForm,
    NewsForm,
    PaymentForm,
    RegisterForm,
    RoleForm,
    UserManagementForm,
    UserRoleForm,
)
from .models import Expense, ExpenseReport, News, Payment, Task, User

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
    return redirect(url_for("main.dashboard_page" if current_user() else "main.login_page"))


@bp.route("/login", methods=["GET", "POST"])
def login_page():
    if current_user():
        return redirect(url_for("main.tasks_page"))

    form = LoginForm()
    if form.validate_on_submit():
        phone = User.normalize_phone(form.username.data)
        user = User.query.filter_by(phone=phone).first()
        if user and user.check_password(form.password.data):
            user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.commit()
            session["user_id"] = user.id
            session["active_role"] = "admin" if user.is_admin else user.role
            return redirect(url_for("main.dashboard_page"))
        flash("Неверный номер телефона или пароль.", "error")
    return render_template("login.html", form=form, show_navigation=False)


@bp.route("/register", methods=["GET", "POST"])
def register_page():
    if current_user():
        return redirect(url_for("main.tasks_page"))

    form = RegisterForm()
    if form.validate_on_submit():
        phone = User.normalize_phone(form.username.data)
        if not phone:
            form.username.errors.append("Введите корректный номер телефона.")
        elif User.query.filter_by(phone=phone).first():
            form.username.errors.append("Этот номер телефона уже зарегистрирован.")
        else:
            user = User(full_name=form.full_name.data.strip(), phone=phone, role="parent")
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash("Аккаунт создан. Теперь войдите в приложение.", "success")
            return redirect(url_for("main.login_page"))
    return render_template("register.html", form=form, show_navigation=False)


@bp.post("/logout")
def logout_page():
    session.clear()
    flash("Вы вышли из аккаунта.", "success")
    return redirect(url_for("main.login_page"))


def page_user():
    """Return the authenticated user and the session-selected presentation role."""
    user = current_user()
    if not user:
        return None, None
    active_role = session.get("active_role", user.role)
    if active_role == "admin" and not user.is_admin:
        active_role = user.role
        session["active_role"] = active_role
    return user, active_role


@bp.get("/dashboard")
def dashboard_page():
    user, active_role = page_user()
    if not user:
        return redirect(url_for("main.login_page"))

    active_task_count = Task.query.filter(Task.status != "done").count()
    latest_news = News.query.filter_by(status="published").order_by(News.created_at.desc()).first()
    month_start = datetime.now(timezone.utc).replace(
        tzinfo=None, day=1, hour=0, minute=0, second=0, microsecond=0
    )
    monthly_expenses = sum(
        float(expense.amount) for expense in Expense.query.filter(Expense.created_at >= month_start).all()
    )
    return render_template(
        "dashboard.html",
        user=user,
        current_user=user,
        active_role=active_role,
        active_task_count=active_task_count,
        monthly_expenses=monthly_expenses,
        latest_news=latest_news,
    )


@bp.route("/news", methods=["GET", "POST"])
def news_page():
    user, active_role = page_user()
    if not user:
        return redirect(url_for("main.login_page"))

    form = NewsForm()
    can_manage = user.is_admin and active_role == "admin"
    if form.validate_on_submit():
        if not can_manage:
            flash("Публиковать новости может только администратор.", "error")
        else:
            db.session.add(
                News(
                    title=form.title.data.strip(),
                    description=form.description.data.strip(),
                    status=form.status.data,
                )
            )
            db.session.commit()
            flash("Новость сохранена.", "success")
            return redirect(url_for("main.news_page"))

    query = News.query.order_by(News.created_at.desc())
    if not can_manage:
        query = query.filter_by(status="published")
    return render_template(
        "news.html",
        user=user,
        current_user=user,
        active_role=active_role,
        can_manage_news=can_manage,
        form=form,
        news_items=query.all(),
    )


@bp.post("/news/<int:news_id>/delete")
def delete_news_page(news_id):
    user, active_role = page_user()
    if not user:
        return redirect(url_for("main.login_page"))
    if not user.is_admin or active_role != "admin":
        flash("Удалять новости может только администратор.", "error")
        return redirect(url_for("main.news_page"))
    news_item = db.session.get(News, news_id)
    if not news_item:
        flash("Новость не найдена.", "error")
    else:
        db.session.delete(news_item)
        db.session.commit()
        flash("Новость удалена.", "success")
    return redirect(url_for("main.news_page"))


@bp.route("/news/<int:news_id>/edit", methods=["GET", "POST"])
def edit_news_page(news_id):
    user, active_role = page_user()
    if not user:
        return redirect(url_for("main.login_page"))
    if not user.is_admin or active_role != "admin":
        flash("Редактировать новости может только администратор.", "error")
        return redirect(url_for("main.news_page"))
    news_item = db.session.get(News, news_id)
    if not news_item:
        flash("Новость не найдена.", "error")
        return redirect(url_for("main.news_page"))
    form = NewsForm(obj=news_item)
    if form.validate_on_submit():
        news_item.title = form.title.data.strip()
        news_item.description = form.description.data.strip()
        news_item.status = form.status.data
        db.session.commit()
        flash("Новость обновлена.", "success")
        return redirect(url_for("main.news_page"))
    return render_template(
        "news_edit.html",
        user=user,
        current_user=user,
        active_role=active_role,
        form=form,
        news_item=news_item,
    )


@bp.route("/users", methods=["GET", "POST"])
def users_page():
    user, active_role = page_user()
    if not user:
        return redirect(url_for("main.login_page"))
    if not user.is_admin or active_role != "admin":
        flash("Доступ к пользователям разрешен только администратору.", "error")
        return redirect(url_for("main.dashboard_page"))

    form = UserManagementForm()
    if request.method == "POST":
        if request.form.get("action") != "create_user":
            flash("Неизвестное действие.", "error")
        elif not form.validate_on_submit():
            flash("Проверьте заполнение обязательных полей.", "error")
        else:
            phone = User.normalize_phone(form.phone.data)
            if not phone.startswith("375") or len(phone) != 12:
                form.phone.errors.append("Введите номер в формате +375 (XX) XXX-XX-XX.")
            elif User.query.filter_by(phone=phone).first():
                form.phone.errors.append("Этот номер телефона уже зарегистрирован.")
            else:
                full_name = " ".join(
                    part.strip()
                    for part in (form.last_name.data, form.first_name.data, form.middle_name.data or "")
                    if part.strip()
                )
                new_user = User(full_name=full_name, phone=phone, role=form.role.data)
                if form.password.data:
                    new_user.set_password(form.password.data)
                else:
                    form.password.errors.append("Укажите пароль не короче 6 символов.")
                if not form.password.errors:
                    db.session.add(new_user)
                    db.session.commit()
                    flash("Пользователь создан.", "success")
                    return redirect(url_for("main.users_page"))

    selected_role = request.args.get("role_filter")
    query = User.query
    if selected_role in {"parent", "student"}:
        query = query.filter_by(role=selected_role)
    role_order = case((User.role == "admin", 0), else_=1)
    users_list = query.order_by(role_order, User.full_name.asc()).all()
    return render_template(
        "users.html",
        user=user,
        current_user=user,
        active_role=active_role,
        users=users_list,
        selected_role=selected_role,
        form=form,
        role_form=UserRoleForm(),
    )


@bp.post("/users/edit/<int:user_id>")
def edit_user_page(user_id):
    user, active_role = page_user()
    if not user:
        return redirect(url_for("main.login_page"))
    if not user.is_admin or active_role != "admin":
        flash("Редактировать пользователей может только администратор.", "error")
        return redirect(url_for("main.dashboard_page"))

    target_user = db.session.get(User, user_id)
    if not target_user:
        flash("Пользователь не найден.", "error")
        return redirect(url_for("main.users_page"))
    form = UserManagementForm()
    if not form.validate_on_submit():
        flash("Проверьте заполнение обязательных полей.", "error")
        return redirect(url_for("main.users_page"))

    phone = User.normalize_phone(form.phone.data)
    existing_user = User.query.filter_by(phone=phone).first()
    if not phone.startswith("375") or len(phone) != 12:
        flash("Введите номер в формате +375 (XX) XXX-XX-XX.", "error")
    elif existing_user and existing_user.id != target_user.id:
        flash("Этот номер телефона уже зарегистрирован.", "error")
    elif target_user.is_admin and form.role.data != "admin" and User.query.filter_by(role="admin").count() == 1:
        flash("Нельзя изменить роль последнего администратора.", "error")
    else:
        target_user.full_name = " ".join(
            part.strip()
            for part in (form.last_name.data, form.first_name.data, form.middle_name.data or "")
            if part.strip()
        )
        target_user.phone = phone
        target_user.role = form.role.data
        if form.password.data:
            target_user.set_password(form.password.data)
        db.session.commit()
        flash("Данные пользователя обновлены.", "success")
    return redirect(url_for("main.users_page"))


@bp.post("/users/delete/<int:user_id>")
def delete_user_page(user_id):
    user, active_role = page_user()
    if not user:
        return redirect(url_for("main.login_page"))
    if not user.is_admin or active_role != "admin":
        flash("Удалять пользователей может только администратор.", "error")
        return redirect(url_for("main.dashboard_page"))

    target_user = db.session.get(User, user_id)
    if not target_user:
        flash("Пользователь не найден.", "error")
    elif target_user.id == user.id:
        flash("Нельзя удалить собственный аккаунт.", "error")
    elif target_user.is_admin and User.query.filter_by(role="admin").count() == 1:
        flash("Нельзя удалить последнего администратора.", "error")
    elif target_user.payments:
        flash("Нельзя удалить пользователя с историей взносов.", "error")
    else:
        db.session.delete(target_user)
        db.session.commit()
        flash("Пользователь удален.", "success")
    return redirect(url_for("main.users_page"))


@bp.post("/users/<int:user_id>/role")
def update_user_role_page(user_id):
    user, active_role = page_user()
    if not user:
        return redirect(url_for("main.login_page"))
    if not user.is_admin or active_role != "admin":
        flash("Изменять роли может только администратор.", "error")
        return redirect(url_for("main.dashboard_page"))
    form = UserRoleForm()
    target_user = db.session.get(User, user_id)
    if not target_user:
        flash("Пользователь не найден.", "error")
    elif form.validate_on_submit():
        target_user.role = form.role.data
        db.session.commit()
        flash("Роль пользователя обновлена.", "success")
    else:
        flash("Выберите корректную роль.", "error")
    return redirect(url_for("main.users_page"))


@bp.route("/profile", methods=["GET", "POST"])
def profile_page():
    user, active_role = page_user()
    if not user:
        return redirect(url_for("main.login_page"))

    form = RoleForm()
    form.role.data = active_role
    return render_template(
        "profile.html",
        user=user,
        current_user=user,
        active_role=active_role,
        form=form,
    )


@bp.post("/change_role")
def change_role():
    user = current_user()
    if not user:
        return redirect(url_for("main.login_page"))
    form = RoleForm()
    if not form.validate_on_submit():
        flash("Выберите корректную роль.", "error")
    elif form.role.data == "admin" and not user.is_admin:
        flash("Режим администратора недоступен для этого аккаунта.", "error")
    else:
        session["active_role"] = form.role.data
        flash(f"Включен режим: {ROLE_LABELS[form.role.data]}.", "success")
    return redirect(url_for("main.profile_page"))


@bp.get("/tasks")
def tasks_page():
    user = current_user()
    if not user:
        return redirect(url_for("main.login_page"))
    tasks_list = Task.query.order_by(Task.created_at.desc()).all()
    return render_template(
        "tasks.html",
        user=user,
        active_tasks=[task for task in tasks_list if task.status != "done"],
        completed_tasks=[task for task in tasks_list if task.status == "done"],
    )


@bp.post("/tasks/<int:task_id>/complete")
def complete_task_page(task_id):
    user = current_user()
    if not user:
        return redirect(url_for("main.login_page"))
    task = db.session.get(Task, task_id)
    if not task:
        flash("Задача не найдена.", "error")
    elif not user.is_admin:
        flash("Изменять статус задач может только администратор.", "error")
    else:
        task.status = "done" if task.status != "done" else "created"
        db.session.commit()
        flash("Статус задачи обновлен.", "success")
    return redirect(url_for("main.tasks_page"))


@bp.route("/expenses", methods=["GET", "POST"])
def expenses_page():
    user, active_role = page_user()
    if not user:
        return redirect(url_for("main.login_page"))

    expense_form = ExpenseForm()
    payment_form = PaymentForm()
    parents = User.query.filter_by(role="parent").order_by(User.full_name).all()
    payment_form.user_id.choices = [(parent.id, parent.full_name) for parent in parents]
    can_manage = user.is_admin

    if request.method == "POST":
        if not can_manage:
            flash("Добавлять взносы и расходы может только администратор.", "error")
        elif request.form.get("action") == "add_payment":
            if payment_form.validate_on_submit():
                payer = db.session.get(User, payment_form.user_id.data)
                if not payer or payer.role != "parent":
                    flash("Выберите зарегистрированного родителя.", "error")
                else:
                    db.session.add(Payment(user_id=payer.id, amount=payment_form.amount.data))
                    db.session.commit()
                    flash("Взнос успешно зафиксирован.", "success")
                    return redirect(url_for("main.expenses_page"))
        elif request.form.get("action") == "add_expense":
            if expense_form.validate_on_submit():
                receipt_filename = None
                receipt = expense_form.receipt.data
                if receipt:
                    original_name = secure_filename(receipt.filename)
                    if not original_name:
                        expense_form.receipt.errors.append("Укажите файл с допустимым именем.")
                    else:
                        receipt_filename = f"{uuid4().hex}_{original_name}"
                        receipt_dir = os.path.join(
                            current_app.root_path, "static", "uploads", "receipts"
                        )
                        os.makedirs(receipt_dir, exist_ok=True)
                        receipt.save(os.path.join(receipt_dir, receipt_filename))
                if not expense_form.receipt.errors:
                    db.session.add(
                        Expense(
                            title=expense_form.title.data.strip(),
                            amount=expense_form.amount.data,
                            category=(expense_form.category.data or "Общие").strip(),
                            receipt_path=receipt_filename,
                        )
                    )
                    db.session.commit()
                    flash("Расход успешно добавлен.", "success")
                    return redirect(url_for("main.expenses_page"))
        else:
            flash("Неизвестное действие.", "error")

    total_deposited = db.session.query(
        db.func.coalesce(db.func.sum(Payment.amount), 0)
    ).scalar()
    total_spent = db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0)).scalar()
    current_balance = total_deposited - total_spent
    return render_template(
        "expenses.html",
        user=user,
        current_user=user,
        active_role=active_role,
        can_manage=can_manage,
        expense_form=expense_form,
        payment_form=payment_form,
        expenses=Expense.query.order_by(Expense.created_at.desc()).all(),
        payments=Payment.query.order_by(Payment.created_at.desc()).all(),
        parents=parents,
        total_deposited=total_deposited,
        total_spent=total_spent,
        total_expenses=total_spent,
        current_balance=current_balance,
        balance=current_balance,
    )


@bp.route("/expenses/edit/<int:expense_id>", methods=["GET", "POST"])
def edit_expense_page(expense_id):
    user = current_user()
    if not user:
        return redirect(url_for("main.login_page"))
    if not user.is_admin:
        flash("Редактировать расходы может только администратор.", "error")
        return redirect(url_for("main.expenses_page"))

    expense = db.session.get(Expense, expense_id)
    if not expense:
        flash("Расход не найден.", "error")
        return redirect(url_for("main.expenses_page"))

    form = ExpenseForm(obj=expense)
    if form.validate_on_submit():
        receipt = form.receipt.data
        if receipt:
            original_name = secure_filename(receipt.filename)
            if not original_name:
                form.receipt.errors.append("Укажите файл с допустимым именем.")
            else:
                receipt_filename = f"{uuid4().hex}_{original_name}"
                receipt_dir = os.path.join(current_app.root_path, "static", "uploads", "receipts")
                os.makedirs(receipt_dir, exist_ok=True)
                receipt.save(os.path.join(receipt_dir, receipt_filename))
                expense.receipt_path = receipt_filename
        if not form.receipt.errors:
            expense.title = form.title.data.strip()
            expense.amount = form.amount.data
            expense.category = (form.category.data or "Общие").strip()
            db.session.commit()
            flash("Расход обновлен.", "success")
            return redirect(url_for("main.expenses_page"))

    return render_template("expense_edit.html", user=user, current_user=user, form=form, expense=expense)


@bp.route("/payments/edit/<int:payment_id>", methods=["GET", "POST"])
def edit_payment_page(payment_id):
    user = current_user()
    if not user:
        return redirect(url_for("main.login_page"))
    if not user.is_admin:
        flash("Редактировать взносы может только администратор.", "error")
        return redirect(url_for("main.expenses_page"))

    payment = db.session.get(Payment, payment_id)
    if not payment:
        flash("Взнос не найден.", "error")
        return redirect(url_for("main.expenses_page"))

    parents = User.query.filter_by(role="parent").order_by(User.full_name).all()
    form = PaymentForm(obj=payment)
    form.user_id.choices = [(parent.id, parent.full_name) for parent in parents]
    if form.validate_on_submit():
        payer = db.session.get(User, form.user_id.data)
        if not payer or payer.role != "parent":
            form.user_id.errors.append("Выберите зарегистрированного родителя.")
        else:
            payment.user_id = payer.id
            payment.amount = form.amount.data
            db.session.commit()
            flash("Взнос обновлен.", "success")
            return redirect(url_for("main.expenses_page"))

    return render_template("payment_edit.html", user=user, current_user=user, form=form, payment=payment)


@bp.post("/api/login")
def login():
    data = request.get_json(silent=True)
    if data is None:
        data = request.form or {}
    phone = User.normalize_phone(data.get("phone"))
    user = User.query.filter_by(phone=phone).first()
    if not user or not user.check_password(data.get("password") or ""):
        return jsonify(error="Неверный телефон или пароль"), 401
    user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
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
