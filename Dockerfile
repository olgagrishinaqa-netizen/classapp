FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN adduser --disabled-password --gecos '' appuser
WORKDIR /app

# Сразу настраиваем права на рабочую директорию для нашего пользователя
RUN chown appuser:appuser /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем файлы проекта с автоматическим назначением прав пользователю appuser
COPY --chown=appuser:appuser . .

USER appuser

ENV FLASK_CONFIG=config.ProdConfig
EXPOSE 8000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:create_app()"]
