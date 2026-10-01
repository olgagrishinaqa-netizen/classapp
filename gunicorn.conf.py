"""Конфигурация gunicorn: корректные метрики Prometheus при нескольких воркерах.

Каждый воркер пишет метрики в файлы PROMETHEUS_MULTIPROC_DIR, а /metrics
агрегирует их, поэтому счётчики больше не «прыгают» между воркерами.
"""

import os
import shutil

multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")


def on_starting(server):
    """Чистим каталог метрик от прошлого запуска, пока воркеры не стартовали."""
    if not multiproc_dir:
        return
    shutil.rmtree(multiproc_dir, ignore_errors=True)
    os.makedirs(multiproc_dir, exist_ok=True)


def child_exit(server, worker):
    """Убираем данные завершившегося воркера из gauge-метрик."""
    if not multiproc_dir:
        return
    from prometheus_flask_exporter.multiprocess import GunicornPrometheusMetrics

    GunicornPrometheusMetrics.mark_process_dead_on_child_exit(worker.pid)
