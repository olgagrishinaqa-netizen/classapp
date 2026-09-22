"""Общие расширения Flask, инициализируемые без привязки к конкретному app-объекту."""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
