"""WTForms-формы classapp: аутентификация, управление пользователями/учениками,
новости, учёт взносов и расходов."""

from decimal import Decimal

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import DateField, DecimalField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, EqualTo, Length, NumberRange, Optional


class LoginForm(FlaskForm):
    """Вход по номеру телефона и паролю."""

    username = StringField("Номер телефона", validators=[DataRequired(), Length(max=32)])
    password = PasswordField("Пароль", validators=[DataRequired()])
    submit = SubmitField("Войти")


class RegisterForm(FlaskForm):
    """Самостоятельная регистрация нового аккаунта (всегда с ролью parent)."""

    full_name = StringField("Имя и фамилия", validators=[DataRequired(), Length(max=160)])
    username = StringField("Номер телефона", validators=[DataRequired(), Length(max=32)])
    password = PasswordField("Пароль", validators=[DataRequired(), Length(min=6, max=128)])
    password_confirm = PasswordField(
        "Повторите пароль", validators=[DataRequired(), EqualTo("password", "Пароли должны совпадать")]
    )
    submit = SubmitField("Создать аккаунт")


class ExpenseForm(FlaskForm):
    """Добавление/редактирование расхода, опционально с чеком."""

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
    """Фиксация взноса родителя; choices для user_id заполняются во view."""

    user_id = SelectField("Плательщик", coerce=int, validators=[DataRequired()])
    amount = DecimalField(
        "Сумма взноса",
        validators=[DataRequired(), NumberRange(min=Decimal("0.01"))],
        places=2,
    )
    submit = SubmitField("Зафиксировать взнос")


class NewsForm(FlaskForm):
    """Создание/редактирование новости с публикацией или сохранением в черновик."""

    title = StringField("Заголовок", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Текст новости", validators=[DataRequired()])
    status = SelectField(
        "Статус",
        choices=[("published", "Опубликовать"), ("draft", "Сохранить как черновик")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Опубликовать новость")


class RoleForm(FlaskForm):
    """Переключение активной роли интерфейса (parent/admin) на /profile."""

    role = SelectField(
        "Режим интерфейса",
        choices=[("parent", "Родитель"), ("admin", "Администратор")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Сменить роль")


class UserRoleForm(FlaskForm):
    """Смена роли другого пользователя администратором."""

    role = SelectField(
        "Роль",
        choices=[("parent", "Родитель"), ("student", "Ученик"), ("admin", "Администратор")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Сохранить")


class UserManagementForm(FlaskForm):
    """Создание/редактирование пользователя администратором (пароль опционален
    при редактировании — пустое значение сохраняет текущий пароль)."""

    last_name = StringField("Фамилия", validators=[DataRequired(), Length(max=80)])
    first_name = StringField("Имя", validators=[DataRequired(), Length(max=80)])
    middle_name = StringField("Отчество", validators=[Length(max=80)])
    phone = StringField("Телефон", validators=[DataRequired(), Length(max=32)])
    role = SelectField(
        "Роль",
        choices=[("parent", "Родитель"), ("student", "Ученик"), ("admin", "Администратор")],
        validators=[DataRequired()],
    )
    password = PasswordField("Пароль", validators=[Optional(), Length(min=6, max=128)])
    submit = SubmitField("Сохранить пользователя")


class StudentForm(FlaskForm):
    """Добавление ученика в состав класса."""

    last_name = StringField(
        "Фамилия",
        validators=[
            DataRequired(message="Пожалуйста, укажите фамилию ученика."),
            Length(max=64, message="Фамилия не должна превышать 64 символа."),
        ],
    )
    first_name = StringField(
        "Имя",
        validators=[
            DataRequired(message="Пожалуйста, укажите имя ученика."),
            Length(max=64, message="Имя не должно превышать 64 символа."),
        ],
    )
    birth_date = DateField(
        "Дата рождения",
        validators=[Optional()],
        format="%Y-%m-%d",
    )
    submit = SubmitField("Создать ученика")
