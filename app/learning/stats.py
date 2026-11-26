"""Аналитика ошибок ученика: «проблемные правила» и «Работа над ошибками».

Правило = тема (параграф учебника). Задание считается неисправленным, если ПОСЛЕДНИЙ
сохранённый ответ на него был неверным; верный ответ в любом тесте (по теме или в работе над
ошибками) снимает его с учёта. Ответы на задания, которых уже нет в каталоге, игнорируются.
"""

from collections import defaultdict

from sqlalchemy import case, func, select

from ..extensions import db
from ..models import LearningAnswer
from . import find_question, get_topic, review_key

REVIEW_SIZE = 10


def _latest_wrong_rows(user_id):
    """Строки LearningAnswer — последние ответы по каждому заданию, если они неверные."""
    latest_ids = (
        select(func.max(LearningAnswer.id))
        .where(LearningAnswer.user_id == user_id)
        .group_by(LearningAnswer.subject, LearningAnswer.topic, LearningAnswer.question_id)
    )
    return (
        db.session.query(LearningAnswer)
        .filter(LearningAnswer.id.in_(latest_ids), LearningAnswer.correct.is_(False))
        .order_by(LearningAnswer.id.desc())
        .all()
    )


def unresolved_by_topic(user_id):
    """{(предмет, тема): [строки LearningAnswer]} только для существующих в каталоге заданий."""
    grouped = defaultdict(list)
    for row in _latest_wrong_rows(user_id):
        if find_question(review_key(row.subject, row.topic, row.question_id)):
            grouped[(row.subject, row.topic)].append(row)
    return grouped


def problem_rules(user_id, limit=5):
    """Темы-правила с неисправленными ошибками, самые проблемные — первыми.

    Элемент: subject, topic (slug), title, par, unresolved (сколько заданий не исправлено),
    wrong и answered (ошибок и ответов за всё время)."""
    unresolved = unresolved_by_topic(user_id)
    if not unresolved:
        return []
    totals = {
        (subject, topic): (answered, wrong or 0)
        for subject, topic, answered, wrong in db.session.query(
            LearningAnswer.subject,
            LearningAnswer.topic,
            func.count(LearningAnswer.id),
            func.sum(case((LearningAnswer.correct.is_(False), 1), else_=0)),
        )
        .filter(LearningAnswer.user_id == user_id)
        .group_by(LearningAnswer.subject, LearningAnswer.topic)
    }
    rules = []
    for (subject, topic_slug), rows in unresolved.items():
        topic = get_topic(subject, topic_slug)
        answered, wrong = totals.get((subject, topic_slug), (len(rows), len(rows)))
        rules.append(
            {
                "subject": subject,
                "topic": topic_slug,
                "title": topic["title"],
                "par": topic["par"],
                "unresolved": len(rows),
                "wrong": int(wrong),
                "answered": int(answered),
            }
        )
    rules.sort(key=lambda rule: (-rule["unresolved"], -rule["wrong"], rule["title"]))
    return rules[:limit]


def unresolved_count(user_id):
    return sum(len(rows) for rows in unresolved_by_topic(user_id).values())


def review_items(user_id, limit=REVIEW_SIZE):
    """Задания для «Работы над ошибками»: [(ключ, тема, задание)]. Сначала из самых
    проблемных тем, внутри темы — самые свежие ошибки."""
    unresolved = unresolved_by_topic(user_id)
    ordered_topics = sorted(unresolved.items(), key=lambda item: (-len(item[1]), -item[1][0].id))
    items = []
    for (subject, topic_slug), rows in ordered_topics:
        for row in rows:
            topic, question = find_question(review_key(subject, topic_slug, row.question_id))
            items.append((review_key(subject, topic_slug, question["id"]), topic, question))
            if len(items) >= limit:
                return items
    return items
