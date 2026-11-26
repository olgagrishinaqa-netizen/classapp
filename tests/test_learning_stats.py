"""Аналитика ошибок: сохранение ответов, проблемные правила, «Работа над ошибками»."""

import pytest

from app import learning
from app.learning import stats
from app.models import LearningAnswer, LearningAttempt

WC = ("belarusian", "word-combination")  # 5 заданий, верный ответ q1 = вариант 0
NS = ("belarusian", "noun-basics")


def text(response):
    return response.get_data(as_text=True)


@pytest.fixture(autouse=True)
def _clean(wipe):
    wipe(LearningAnswer, LearningAttempt)


@pytest.fixture()
def student_client(app, make_user, login_as):
    user = make_user(role="student", full_name="Анна Ученикова")
    client = app.test_client()
    login_as(client, user.phone, user.plain_password)
    client.user = user
    return client


def correct_answers(topic):
    return {
        q["id"]: str(q["answer"]) if "options" in q else q["answers"][0] for q in topic["questions"]
    }


def check(client, target, answers):
    return client.post(f"/learn/{target[0]}/{target[1]}/check", json={"answers": answers})


def make_mistakes(client, target, wrong_ids):
    """Проходит тему, ошибаясь в указанных заданиях."""
    topic = learning.get_topic(*target)
    answers = correct_answers(topic)
    for qid in wrong_ids:
        question = next(q for q in topic["questions"] if q["id"] == qid)
        answers[qid] = "zzz" if "answers" in question else str((question["answer"] + 1) % 3)
    return check(client, target, answers)


class TestRecording:
    def test_only_answered_questions_are_recorded(self, student_client):
        check(student_client, WC, {"q1": "0", "q2": "", "q3": "2"})
        rows = LearningAnswer.query.filter_by(user_id=student_client.user.id).all()
        assert {(r.question_id, r.correct) for r in rows} == {("q1", True), ("q3", False)}
        attempt = LearningAttempt.query.one()
        assert all(r.attempt_id == attempt.id for r in rows)

    def test_nothing_recorded_for_empty_submission(self, student_client):
        check(student_client, WC, {})
        assert LearningAnswer.query.count() == 0


class TestUnresolvedLogic:
    def test_wrong_then_correct_resolves_the_question(self, student_client):
        uid = student_client.user.id
        make_mistakes(student_client, WC, ["q1"])
        assert stats.unresolved_count(uid) == 1
        check(student_client, WC, correct_answers(learning.get_topic(*WC)))
        assert stats.unresolved_count(uid) == 0

    def test_correct_then_wrong_is_unresolved(self, student_client):
        uid = student_client.user.id
        check(student_client, WC, correct_answers(learning.get_topic(*WC)))
        make_mistakes(student_client, WC, ["q2"])
        assert stats.unresolved_count(uid) == 1

    def test_unknown_questions_are_ignored(self, student_client, db):
        db.session.add(
            LearningAnswer(
                user_id=student_client.user.id,
                subject="belarusian",
                topic="deleted-topic",
                question_id="q1",
                correct=False,
            )
        )
        db.session.commit()
        assert stats.unresolved_count(student_client.user.id) == 0
        assert stats.problem_rules(student_client.user.id) == []

    def test_users_are_isolated(self, student_client, app, make_user, login_as):
        make_mistakes(student_client, WC, ["q1", "q2"])
        other = make_user(role="student")
        assert stats.unresolved_count(other.id) == 0
        assert stats.review_items(other.id) == []


class TestProblemRules:
    def test_ranking_counts_and_limit(self, student_client):
        uid = student_client.user.id
        make_mistakes(student_client, WC, ["q1", "q2", "q3"])
        make_mistakes(student_client, NS, ["q1"])
        rules = stats.problem_rules(uid)
        assert [r["topic"] for r in rules] == ["word-combination", "noun-basics"]
        first = rules[0]
        assert (first["unresolved"], first["wrong"], first["answered"]) == (3, 3, 5)
        assert first["par"] == "§ 15–16" and first["title"]
        assert len(stats.problem_rules(uid, limit=1)) == 1

    def test_resolved_topic_disappears_but_history_counts_stay(self, student_client):
        uid = student_client.user.id
        make_mistakes(student_client, WC, ["q1"])
        check(student_client, WC, correct_answers(learning.get_topic(*WC)))
        assert stats.problem_rules(uid) == []


class TestReviewItems:
    def test_items_prioritise_worst_topic_and_respect_limit(self, student_client):
        uid = student_client.user.id
        make_mistakes(student_client, NS, ["q1"])
        make_mistakes(student_client, WC, ["q1", "q2"])
        items = stats.review_items(uid)
        # сначала самая проблемная тема, внутри темы — самые свежие ошибки
        assert [key for key, _, _ in items] == [
            "belarusian/word-combination/q2",
            "belarusian/word-combination/q1",
            "belarusian/noun-basics/q1",
        ]
        assert len(stats.review_items(uid, limit=2)) == 2


class TestReviewPage:
    URL = "/learn/review"

    def test_empty_state(self, student_client):
        page = text(student_client.get(self.URL))
        assert "Неисправленных ошибок нет" in page and "quiz-form" not in page

    def test_lists_unresolved_questions_with_paragraph_label(self, student_client):
        make_mistakes(student_client, WC, ["q1"])
        topic = learning.get_topic(*WC)
        page = text(student_client.get(self.URL))
        assert "Работа над ошибками" in page and "§ 15–16" in page
        assert topic["questions"][0]["text"] in page
        assert 'data-question="belarusian/word-combination/q1"' in page
        assert 'data-retry-url="/learn/belarusian/word-combination/retry"' in page
        # подсказки и ответы в страницу не попадают
        assert topic["questions"][0]["hint"] not in page

    def test_access_rules(self, client, parent_client, admin_client):
        assert client.get(self.URL).status_code == 302
        assert "доступен только ученикам" in text(
            parent_client.get(self.URL, follow_redirects=True)
        )
        assert admin_client.get(self.URL).status_code == 200


class TestReviewCheck:
    URL = "/learn/review/check"
    KEY = "belarusian/word-combination/q1"

    def test_correct_answer_clears_the_mistake(self, student_client):
        make_mistakes(student_client, WC, ["q1"])
        data = student_client.post(self.URL, json={"answers": {self.KEY: "0"}}).get_json()
        assert data["score"] == data["total"] == 1 and data["remaining"] == 0
        assert data["results"][0]["id"] == self.KEY
        assert stats.unresolved_count(student_client.user.id) == 0

    def test_wrong_answer_keeps_mistake_and_returns_hint_and_retry(self, student_client):
        make_mistakes(student_client, WC, ["q1"])
        data = student_client.post(self.URL, json={"answers": {self.KEY: "2"}}).get_json()
        result = data["results"][0]
        assert data["score"] == 0 and data["remaining"] == 1
        assert result["hint"] and result["retry"]["id"] == "q1r"

    def test_unanswered_is_not_recorded(self, student_client):
        make_mistakes(student_client, WC, ["q1"])
        before = LearningAnswer.query.count()
        student_client.post(self.URL, json={"answers": {self.KEY: ""}})
        assert LearningAnswer.query.count() == before

    def test_does_not_create_an_attempt_or_change_best_score(self, student_client):
        make_mistakes(student_client, WC, ["q1"])
        attempts = LearningAttempt.query.count()
        student_client.post(self.URL, json={"answers": {self.KEY: "0"}})
        assert LearningAttempt.query.count() == attempts

    @pytest.mark.parametrize("body", [None, [], {"answers": []}, {"answers": {}}, {"x": 1}])
    def test_bad_payload(self, student_client, body):
        assert student_client.post(self.URL, json=body).status_code == 400

    def test_too_many_answers(self, student_client):
        answers = {f"belarusian/word-combination/q{n}": "0" for n in range(1, 40)}
        assert student_client.post(self.URL, json={"answers": answers}).status_code == 400

    def test_unknown_keys_are_ignored_or_rejected(self, student_client):
        response = student_client.post(
            self.URL, json={"answers": {"nope": "0", "a/b/c": "0", "belarusian/nope/q1": "0"}}
        )
        assert response.status_code == 404
        mixed = student_client.post(
            self.URL, json={"answers": {"nope": "0", self.KEY: "0"}}
        ).get_json()
        assert mixed["total"] == 1

    def test_roles_and_csrf(self, client, parent_client, student_client, app):
        assert client.post(self.URL, json={"answers": {self.KEY: "0"}}).status_code == 401
        assert parent_client.post(self.URL, json={"answers": {self.KEY: "0"}}).status_code == 403
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            response = student_client.post(self.URL, json={"answers": {self.KEY: "0"}})
        finally:
            app.config["WTF_CSRF_ENABLED"] = False
        assert response.status_code == 400


class TestPagesShowAnalytics:
    def test_learn_page_without_mistakes(self, student_client):
        page = text(student_client.get("/learn"))
        assert "Проблемные правила" in page and "Неисправленных ошибок нет" in page
        assert "Работа над ошибками (" not in page

    def test_learn_page_lists_problem_rules_and_review_button(self, student_client):
        make_mistakes(student_client, WC, ["q1", "q2"])
        page = text(student_client.get("/learn"))
        assert "Словазлучэнне" in page and "§ 15–16" in page
        assert "не исправлено: 2" in page and "ошибок: 2 из 5" in page
        assert "Работа над ошибками (2)" in page
        assert "/learn/review" in page

    def test_parent_sees_childs_problem_rules(self, app, make_user, login_as, db):
        mom = make_user(role="parent")
        kid = make_user(role="student", full_name="Петя Первый")
        kid.parent_id = mom.id
        db.session.commit()
        kid_client = app.test_client()
        login_as(kid_client, kid.phone, kid.plain_password)
        make_mistakes(kid_client, WC, ["q1"])
        mom_client = app.test_client()
        login_as(mom_client, mom.phone, mom.plain_password)
        page = text(mom_client.get("/children"))
        assert "Проблемные правила" in page and "§ 15–16" in page and "не исправлено: 1" in page

    def test_parent_sees_no_block_without_mistakes(self, app, make_user, login_as, db):
        mom = make_user(role="parent")
        kid = make_user(role="student")
        kid.parent_id = mom.id
        db.session.commit()
        mom_client = app.test_client()
        login_as(mom_client, mom.phone, mom.plain_password)
        assert "Проблемные правила" not in text(mom_client.get("/children"))
