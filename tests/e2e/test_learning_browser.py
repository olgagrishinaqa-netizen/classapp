"""Раздел «Учёба» в браузере: карточка подсказки с правилом и вторая попытка."""

import pytest
from playwright.sync_api import expect

from app.models import User

pytestmark = pytest.mark.e2e

PASSWORD = "secret123"


@pytest.fixture()
def student_page(page, login, seed):
    def create(db):
        user = User(full_name="Анна Ученикова", phone="375297770030", role="student")
        user.set_password(PASSWORD)
        db.session.add(user)

    seed(create)
    login("297770030", PASSWORD)
    page.wait_for_url("**/dashboard")
    return page


class TestHintCard:
    def test_student_sees_sections_and_paragraphs(self, student_page):
        student_page.goto("/learn/belarusian")
        expect(student_page.get_by_role("heading", name="Сінтаксіс і пунктуацыя")).to_be_visible()
        expect(student_page.get_by_text("§ 28", exact=True)).to_be_visible()

    def test_wrong_answer_shows_rule_example_why_and_retry(self, student_page):
        student_page.goto("/learn/belarusian/word-combination")
        box = student_page.locator("[data-question=q1]")
        box.get_by_label("лісце падае", exact=True).check()  # неверно: это грамматическая основа
        student_page.get_by_role("button", name="Проверить", exact=True).first.click()

        feedback = box.locator(".quiz-feedback")
        expect(feedback).to_contain_text("Вот правило:")
        expect(feedback).to_contain_text("Пример.")
        expect(feedback).to_contain_text("Почему так:")
        expect(feedback).to_contain_text("Попробуй похожее задание:")
        # неотвеченные задания не получают подсказку
        expect(student_page.locator("[data-question=q2] .quiz-feedback")).to_contain_text(
            "Выбери или впиши ответ."
        )

    def test_retry_accepts_right_and_rejects_wrong_answer(self, student_page):
        student_page.goto("/learn/belarusian/word-combination")
        box = student_page.locator("[data-question=q1]")
        box.get_by_label("лісце падае", exact=True).check()
        student_page.get_by_role("button", name="Проверить", exact=True).first.click()
        feedback = box.locator(".quiz-feedback")
        expect(feedback).to_contain_text("Попробуй похожее задание:")

        feedback.get_by_label("восень", exact=True).check()  # неверно
        feedback.get_by_role("button", name="Проверить").click()
        expect(feedback).to_contain_text("Пока неверно")

        feedback.get_by_label("залатая восень", exact=True).check()  # верно
        feedback.get_by_role("button", name="Проверить").click()
        expect(feedback).to_contain_text("Верно! Теперь вернись к заданию выше")

    def test_all_correct_shows_success(self, student_page):
        student_page.goto("/learn/belarusian/word-combination")
        right = {
            "q1": "жоўтае лісце",
            "q2": "паехаць",
            "q3": "галоўнае слова",
            "q4": "прыметнікам",
            "q5": "не, гэта дзейнік і выказнік (граматычная аснова)",
        }
        for qid, label in right.items():
            student_page.locator(f"[data-question={qid}]").get_by_label(label, exact=True).check()
        student_page.get_by_role("button", name="Проверить", exact=True).first.click()
        expect(student_page.locator("#quiz-summary")).to_contain_text("Отлично!")
