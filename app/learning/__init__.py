"""Раздел ученика: тесты по учебным предметам с подсказками из правил.

Содержание заданий лежит в модулях предметов (russian.py, belarusian.py, math.py,
english.py). Здесь — загрузка каталога и проверка ответов. Правильные ответы и
подсказки в браузер не отдаются: клиент видит их только после проверки на сервере,
и подсказка показывается лишь для неверно решённых заданий.

Структура каталога: предмет -> раздел (глава учебника) -> тема (параграф). У темы есть
правило с примером; у задания — пояснение «почему так» (hint) и необязательное
аналогичное задание `retry` для второй попытки после ошибки.
"""

from . import belarusian, english, math, russian

_MODULES = (russian, belarusian, math, english)
DEFAULT_SECTION = "Темы"


def _build_catalog():
    catalog = {}
    for module in _MODULES:
        subject = dict(module.SUBJECT)
        topics = {}
        sections = []
        for topic_data in module.TOPICS:
            topic = {k: v for k, v in topic_data.items() if k != "questions"}
            topic["subject"] = subject["slug"]
            topic.setdefault("section", DEFAULT_SECTION)
            topic.setdefault("par", "")
            topic.setdefault("example", "")
            topic["questions"] = [
                {**question, "id": f"q{number}"}
                for number, question in enumerate(topic_data["questions"], start=1)
            ]
            for question in topic["questions"]:
                if "retry" in question:
                    question["retry"] = {**question["retry"], "id": f"{question['id']}r"}
            topics[topic["slug"]] = topic
            if not sections or sections[-1]["title"] != topic["section"]:
                sections.append({"title": topic["section"], "topics": []})
            sections[-1]["topics"].append(topic)
        subject["topics"] = topics
        subject["sections"] = sections
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


def check_retry(topic, question_id, answer):
    """Проверяет ответ на аналогичное задание (вторая попытка). Возвращает True/False,
    либо None, если такого задания нет. Результат нигде не сохраняется."""
    base_id = str(question_id).removesuffix("r")
    for question in topic["questions"]:
        if question["id"] == base_id and "retry" in question:
            return _is_correct(question["retry"], answer)
    return None


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
            if "retry" in question:
                result["retry"] = public_question(question["retry"])
        results.append(result)
    return score, results
