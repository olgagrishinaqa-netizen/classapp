import json
import os


def test_app_writes_json_log_file(app):
    app.logger.error("structured log check")

    log_path = app.config["APP_JSON_LOG_PATH"]
    assert os.path.exists(log_path)
    with open(log_path, encoding="utf-8") as log_file:
        entries = [line.strip() for line in log_file.readlines() if line.strip()]

    payload = json.loads(entries[-1])
    assert payload["message"] == "structured log check"
    assert payload["level"] == "ERROR"
    assert "timestamp" in payload
    assert "path" in payload
    assert "line" in payload
