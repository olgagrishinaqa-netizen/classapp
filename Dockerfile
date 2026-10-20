FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Явный uid 1000: на него ссылаются манифесты Kubernetes (runAsUser) и права на каталоги.
RUN adduser --disabled-password --gecos '' --uid 1000 appuser
WORKDIR /app

# Сразу настраиваем права на рабочую директорию для нашего пользователя
RUN chown appuser:appuser /app
RUN mkdir -p /var/log/classapp /tmp/prometheus_multiproc \
    && chown -R appuser:appuser /var/log/classapp /tmp/prometheus_multiproc

COPY requirements.txt .
# setuptools и wheel нужны только для сборки; в рантайме приложению они не требуются, а их встроенные
# копии пакетов дают уязвимости (Trivy). Удаляем из итогового образа.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y setuptools wheel

# Копируем файлы проекта с автоматическим назначением прав пользователю appuser
COPY --chown=appuser:appuser . .

# Copy and set up entrypoint that waits for DB and validates env
COPY --chown=appuser:appuser entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER 1000:1000

ENV FLASK_CONFIG=config.ProdConfig \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
EXPOSE 8000
# Для запуска вне Kubernetes (в K8s работают собственные пробы readiness/liveness).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:create_app()"]
