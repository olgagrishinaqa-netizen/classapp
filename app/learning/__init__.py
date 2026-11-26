"""Раздел ученика: тесты по учебным предметам с подсказками из правил.

Содержание заданий лежит в модулях предметов (russian.py, belarusian.py, math.py,
english.py). Здесь — загрузка каталога и проверка ответов. Правильные ответы и
подсказки в браузер не отдаются: клиент видит их только после проверки на сервере,
и подсказка показывается лишь для неверно решённых заданий.
"""

from . import belarusian, english, math, russian

_MODULES = (russian, belarusian, math, english)


def _build_catalog():
    catalog = {}
    for module in _MODULES:
        subject = dict(module.SUBJECT)
        topics = {}
        for topic_data in module.TOPICS:
            topic = {k: v for k, v in topic_data.items() if k != "questions"}
            topic["subject"] = subject["slug"]
            topic["questions"] = [
                {**question, "id": f"q{number}"}
                for number, question in enumerate(topic_data["questions"], start=1)
            ]
            topics[topic["slug"]] = topic
        subject["topics"] = topics
        catalog[subject["slug"]] = subject
    return catalog


CATALOG = _build_catalog()


def get_subject(slug):
    return CATALOG.get(slug)


def get_topic(subject_slug, topic_slug):
    subject = CATALOG.get(subject_slug)
    return subject["topics"].get(topic_slug) if subject else None


def public_question(question):
    """Вопрос без ответа и подсказки — то, что можно отдать в браузер."""
    kind = "choice" if "options" in question else "input"
    data = {"id": question["id"], "text": question["text"], "kind": kind}
    if kind == "choice":
        data["options"] = list(question["options"])
    return data


def normalize_answer(value):
    """Приводит ответ к виду для сравнения: регистр, ё/е, лишние пробелы."""
    text = str(value or "").strip().lower().replace("ё", "е")
    return " ".join(text.split())


def _is_correct(question, answer):
    if answer is None or answer == "":
        return False
    if "options" in question:
        try:
            index = int(answer)
        except (TypeError, ValueError):
            return False
        return index == question["answer"]
    normalized = normalize_answer(answer).replace(" / ", "/").replace(" /", "/").replace("/ ", "/")
    return normalized in {normalize_answer(a) for a in question["answers"]}


def check_answers(topic, answers):
    """Проверяет ответы ученика. answers — словарь {id вопроса: ответ}.

    Возвращает (score, results): для каждого вопроса — correct, answered и
    hint (только для неверных ответов на заданные вопросы)."""
    answers = answers if isinstance(answers, dict) else {}
    results = []
    score = 0
    for question in topic["questions"]:
        answer = answers.get(question["id"])
        answered = answer is not None and str(answer).strip() != ""
        correct = _is_correct(question, answer)
        score += int(correct)
        result = {"id": question["id"], "correct": correct, "answered": answered}
        if answered and not correct:
            result["hint"] = question["hint"]
        results.append(result)
    return score, results
