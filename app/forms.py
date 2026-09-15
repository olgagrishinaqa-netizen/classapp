from decimal import Decimal

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import DecimalField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, EqualTo, Length, NumberRange


class LoginForm(FlaskForm):
    username = StringField("Номер телефона", validators=[DataRequired(), Length(max=32)])
    password = PasswordField("Пароль", validators=[DataRequired()])
    submit = SubmitField("Войти")


class RegisterForm(FlaskForm):
    full_name = StringField("Имя и фамилия", validators=[DataRequired(), Length(max=160)])
    username = StringField("Номер телефона", validators=[DataRequired(), Length(max=32)])
    password = PasswordField("Пароль", validators=[DataRequired(), Length(min=6, max=128)])
    password_confirm = PasswordField(
        "Повторите пароль", validators=[DataRequired(), EqualTo("password", "Пароли должны совпадать")]
    )
    submit = SubmitField("Создать аккаунт")


class ExpenseForm(FlaskForm):
    title = StringField("Название расхода", validators=[DataRequired(), Length(max=180)])
    amount = DecimalField(
        "Сумма",
        validators=[DataRequired(), NumberRange(min=Decimal("0.01"))],
        places=2,
    )
    category = StringField("Категория", validators=[Length(max=80)])
    receipt = FileField(
        "Фото или файл чека",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp", "pdf"], "Допустимы JPG, PNG, WEBP или PDF.")],
    )
    submit = SubmitField("Добавить расход")


class PaymentForm(FlaskForm):
    user_id = SelectField("Плательщик", coerce=int, validators=[DataRequired()])
    amount = DecimalField(
        "Сумма взноса",
        validators=[DataRequired(), NumberRange(min=Decimal("0.01"))],
        places=2,
    )
    submit = SubmitField("Зафиксировать взнос")


class NewsForm(FlaskForm):
    title = StringField("Заголовок", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Текст новости", validators=[DataRequired()])
    status = SelectField(
        "Статус",
        choices=[("published", "Опубликовать"), ("draft", "Сохранить как черновик")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Опубликовать новость")


class RoleForm(FlaskForm):
    role = SelectField(
        "Режим интерфейса",
        choices=[("parent", "Родитель"), ("admin", "Администратор")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Сменить роль")


class UserRoleForm(FlaskForm):
    role = SelectField(
        "Роль",
        choices=[("parent", "Родитель"), ("student", "Ученик"), ("admin", "Администратор")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Сохранить")
