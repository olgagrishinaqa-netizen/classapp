"""Раздел ученика «Учёба»: каталог, доступ по ролям, проверка ответов, подсказки, прогресс."""

import pytest

from app import learning
from app.models import LearningAttempt

SUBJECTS = {"russian", "belarusian", "math", "english"}


def text(response):
    return response.get_data(as_text=True)


@pytest.fixture()
def student_client(app, make_user, login_as):
    user = make_user(role="student", full_name="Анна Ученикова")
    client = app.test_client()
    login_as(client, user.phone, user.plain_password)
    client.user = user
    return client


@pytest.fixture(autouse=True)
def _clean_attempts(wipe):
    wipe(LearningAttempt)


def correct_answers(topic):
    answers = {}
    for q in topic["questions"]:
        answers[q["id"]] = str(q["answer"]) if "options" in q else q["answers"][0]
    return answers


class TestCatalog:
    def test_four_subjects(self):
        assert set(learning.CATALOG) == SUBJECTS

    @pytest.mark.parametrize("subject", sorted(SUBJECTS))
    def test_each_subject_has_topics_with_rule_and_questions(self, subject):
        topics = learning.CATALOG[subject]["topics"]
        assert len(topics) >= 5
        for topic in topics.values():
            assert topic["rule"].strip()
            assert len(topic["questions"]) >= 5

    def test_every_question_is_well_formed(self):
        for subject in learning.CATALOG.values():
            for topic in subject["topics"].values():
                ids = [q["id"] for q in topic["questions"]]
                assert len(ids) == len(set(ids))
                for q in topic["questions"]:
                    assert q["text"].strip() and q["hint"].strip(), (topic["slug"], q["id"])
                    if "options" in q:
                        assert len(set(q["options"])) == len(q["options"]), q["text"]
                        assert 0 <= q["answer"] < len(q["options"]), q["text"]
                    else:
                        assert q["answers"], q["text"]

    def test_belarusian_follows_textbook_structure(self):
        subject = learning.CATALOG["belarusian"]
        titles = [section["title"] for section in subject["sections"]]
        assert titles == [
            "Маўленне",
            "Паўтарэнне вывучанага ў I–IV класах",
            "Тэкст",
            "Сінтаксіс і пунктуацыя",
        ]
        for topic in subject["topics"].values():
            assert topic["par"].startswith("§"), topic["slug"]
            assert topic["example"].strip(), topic["slug"]
            # правило и все задания — на белорусском (в белорусском алфавите есть і, ў)
            assert any(ch in topic["rule"] for ch in "іўІЎ"), topic["slug"]

    def test_every_belarusian_question_has_a_valid_retry(self):
        for topic in learning.CATALOG["belarusian"]["topics"].values():
            for q in topic["questions"]:
                retry = q["retry"]
                assert retry["id"] == f"{q['id']}r"
                assert retry["text"].strip() != q["text"].strip()
                if "options" in retry:
                    assert 0 <= retry["answer"] < len(retry["options"]), retry["text"]
                else:
                    assert retry["answers"], retry["text"]

    def test_default_section_for_subjects_without_sections(self):
        math_sections = learning.CATALOG["math"]["sections"]
        assert [s["title"] for s in math_sections] == ["Темы"]
        assert len(math_sections[0]["topics"]) == 5

    def test_public_question_hides_answer_and_hint(self):
        topic = learning.get_topic("math", "order-of-operations")
        for q in topic["questions"]:
            public = learning.public_question(q)
            assert set(public) <= {"id", "text", "kind", "options"}

    def test_unknown_subject_and_topic(self):
        assert learning.get_subject("physics") is None
        assert learning.get_topic("math", "nope") is None
        assert learning.get_topic("nope", "nope") is None


class TestCheckAnswers:
    def test_all_correct(self):
        topic = learning.get_topic("math", "order-of-operations")
        score, results = learning.check_answers(topic, correct_answers(topic))
        assert score == len(topic["questions"])
        assert all(r["correct"] and "hint" not in r for r in results)

    def test_wrong_answer_gets_hint(self):
        topic = learning.get_topic("math", "order-of-operations")
        score, results = learning.check_answers(topic, {"q1": "0"})
        assert score == 0
        assert results[0]["hint"] == topic["questions"][0]["hint"]

    def test_unanswered_has_no_hint(self):
        topic = learning.get_topic("math", "order-of-operations")
        _, results = learning.check_answers(topic, {"q1": "  "})
        assert results[0]["answered"] is False and "hint" not in results[0]

    def test_normalization_case_yo_and_spaces(self):
        assert learning.normalize_answer("  ЗЁМЛЯ   Тест ") == "земля тест"

    def test_choice_with_garbage_index_is_wrong(self):
        topic = learning.get_topic("english", "verb-to-be")
        choice_q = next(q for q in topic["questions"] if "options" in q)
        score, results = learning.check_answers(topic, {choice_q["id"]: "abc"})
        assert score == 0

    def test_fraction_answer_spacing_tolerated(self):
        topic = learning.get_topic("math", "common-fractions")
        q = next(q for q in topic["questions"] if "answers" in q and "6/9" in q["answers"])
        _, results = learning.check_answers(topic, {q["id"]: " 2 / 3 "})
        assert next(r for r in results if r["id"] == q["id"])["correct"]

    def test_non_dict_answers_are_ignored(self):
        topic = learning.get_topic("math", "order-of-operations")
        score, _ = learning.check_answers(topic, ["x"])
        assert score == 0

    def test_every_typed_primary_answer_is_accepted(self):
        for subject in learning.CATALOG.values():
            for topic in subject["topics"].values():
                score, _ = learning.check_answers(topic, correct_answers(topic))
                assert score == len(topic["questions"]), topic["slug"]


class TestAccess:
    @pytest.mark.parametrize("path", ["/learn", "/learn/math", "/learn/math/order-of-operations"])
    def test_anonymous_redirected_to_login(self, client, path):
        response = client.get(path)
        assert response.status_code == 302 and response.headers["Location"].endswith("/login")

    @pytest.mark.parametrize("path", ["/learn", "/learn/math", "/learn/math/order-of-operations"])
    def test_parent_is_refused(self, parent_client, path):
        page = text(parent_client.get(path, follow_redirects=True))
        assert "доступен только ученикам" in page

    def test_parent_cannot_check(self, parent_client):
        response = parent_client.post("/learn/math/order-of-operations/check", json={"answers": {}})
        assert response.status_code == 403

    def test_anonymous_cannot_check(self, client):
        response = client.post("/learn/math/order-of-operations/check", json={"answers": {}})
        assert response.status_code == 401

    def test_admin_may_open(self, admin_client):
        assert admin_client.get("/learn").status_code == 200


class TestPages:
    def test_index_lists_four_subjects(self, student_client):
        page = text(student_client.get("/learn"))
        for title in ("Русский язык", "Белорусский язык", "Математика", "Английский язык"):
            assert title in page

    def test_subject_page_lists_topics(self, student_client):
        page = text(student_client.get("/learn/math"))
        assert "Обыкновенные дроби" in page and "не пройдено" in page

    def test_unknown_subject_and_topic_redirect(self, student_client):
        assert "Такого предмета нет" in text(
            student_client.get("/learn/art", follow_redirects=True)
        )
        assert "Такой темы нет" in text(
            student_client.get("/learn/math/nope", follow_redirects=True)
        )

    def test_topic_page_shows_rule_but_not_answers_or_hints(self, student_client):
        topic = learning.get_topic("russian", "paired-consonants")
        page = text(student_client.get("/learn/russian/paired-consonants"))
        assert topic["rule"][:40] in page
        for q in topic["questions"]:
            assert q["text"] in page
            assert q["hint"] not in page

    def test_student_sees_navigation_item(self, student_client):
        assert "Учёба" in text(student_client.get("/dashboard"))

    def test_parent_has_no_learning_link(self, parent_client):
        assert "/learn" not in text(parent_client.get("/dashboard"))


class TestCheckEndpoint:
    URL = "/learn/math/order-of-operations/check"

    def test_perfect_score_is_saved(self, student_client, db):
        topic = learning.get_topic("math", "order-of-operations")
        data = student_client.post(self.URL, json={"answers": correct_answers(topic)}).get_json()
        assert data["score"] == data["total"] == 6
        attempt = LearningAttempt.query.filter_by(user_id=student_client.user.id).one()
        assert (attempt.subject, attempt.topic, attempt.score, attempt.total) == (
            "math",
            "order-of-operations",
            6,
            6,
        )

    def test_mistake_returns_hint_from_rule(self, student_client):
        topic = learning.get_topic("math", "order-of-operations")
        answers = correct_answers(topic)
        answers["q1"] = "36"
        data = student_client.post(self.URL, json={"answers": answers}).get_json()
        assert data["score"] == 5
        first = data["results"][0]
        assert not first["correct"] and "умножение" in first["hint"]
        assert all("hint" not in r for r in data["results"][1:])

    def test_response_never_leaks_answers(self, student_client):
        data = student_client.post(self.URL, json={"answers": {}}).get_json()
        assert all(set(r) <= {"id", "correct", "answered", "hint"} for r in data["results"])

    def test_progress_shows_best_result(self, student_client):
        topic = learning.get_topic("math", "order-of-operations")
        student_client.post(self.URL, json={"answers": correct_answers(topic)})
        student_client.post(self.URL, json={"answers": {}})
        page = text(student_client.get("/learn/math"))
        assert "6/6" in page
        assert "Пройдено тем: 1 из 5" in text(student_client.get("/learn"))

    def test_progress_is_per_student(self, student_client, app, make_user, login_as):
        topic = learning.get_topic("math", "order-of-operations")
        student_client.post(self.URL, json={"answers": correct_answers(topic)})
        other = make_user(role="student")
        other_client = app.test_client()
        login_as(other_client, other.phone, other.plain_password)
        assert "не пройдено" in text(other_client.get("/learn/math"))

    @pytest.mark.parametrize("body", [None, {"answers": "x"}, {"nope": 1}, []])
    def test_bad_payload(self, student_client, body):
        response = student_client.post(self.URL, json=body)
        assert response.status_code == 400

    def test_unknown_topic_404(self, student_client):
        assert (
            student_client.post("/learn/math/nope/check", json={"answers": {}}).status_code == 404
        )

    def test_csrf_enforced_when_enabled(self, student_client, app):
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            response = student_client.post(self.URL, json={"answers": {}})
        finally:
            app.config["WTF_CSRF_ENABLED"] = False
        assert response.status_code == 400


class TestParentLink:
    """Выбор родителя при создании ученика и просмотр результатов родителем."""

    @pytest.fixture(autouse=True)
    def _users(self, db):
        yield
        from app.models import User

        db.session.rollback()
        User.query.filter(User.phone.like("37570%")).delete(synchronize_session=False)
        db.session.commit()

    def create(self, admin_client, phone, role, parent_id="", name="Новый"):
        return admin_client.post(
            "/users",
            data={
                "action": "create_user",
                "last_name": "Тестов",
                "first_name": name,
                "phone": phone,
                "role": role,
                "password": "secret123",
                "parent_id": parent_id,
            },
            follow_redirects=True,
        )

    def test_parent_list_is_rendered_for_admin(self, admin_client, make_user):
        parent = make_user(role="parent", full_name="Мама Тестова")
        page = text(admin_client.get("/users"))
        assert 'name="parent_id"' in page and "Мама Тестова" in page
        assert f'value="{parent.id}"' in page

    def test_student_requires_parent(self, admin_client):
        page = text(self.create(admin_client, "375701110001", "student"))
        assert "Выберите родителя ученика." in page

    def test_student_created_with_parent(self, admin_client, make_user):
        from app.models import User

        parent = make_user(role="parent")
        page = text(self.create(admin_client, "375701110002", "student", str(parent.id)))
        assert "Пользователь создан." in page
        child = User.query.filter_by(phone="375701110002").one()
        assert child.parent_id == parent.id

    @pytest.mark.parametrize("bad", ["999999", "abc"])
    def test_invalid_parent_rejected(self, admin_client, bad):
        assert "Выберите родителя из списка." in text(
            self.create(admin_client, "375701110003", "student", bad)
        )

    def test_non_parent_cannot_be_chosen(self, admin_client, make_user):
        other_student = make_user(role="student")
        page = text(self.create(admin_client, "375701110004", "student", str(other_student.id)))
        assert "Выберите родителя из списка." in page

    def test_parent_role_ignores_parent_field(self, admin_client, make_user):
        from app.models import User

        parent = make_user(role="parent")
        self.create(admin_client, "375701110005", "parent", str(parent.id))
        assert User.query.filter_by(phone="375701110005").one().parent_id is None

    def test_edit_to_student_and_back(self, admin_client, make_user, db):
        parent = make_user(role="parent")
        target = make_user(role="parent")

        def edit(role, parent_id=""):
            return admin_client.post(
                f"/users/edit/{target.id}",
                data={
                    "last_name": "А",
                    "first_name": "Б",
                    "phone": f"+{target.phone}",
                    "role": role,
                    "parent_id": parent_id,
                },
                follow_redirects=True,
            )

        assert "Выберите родителя ученика." in text(edit("student"))
        assert "обновлены" in text(edit("student", str(parent.id)))
        db.session.refresh(target)
        assert target.parent_id == parent.id
        edit("parent")
        db.session.refresh(target)
        assert target.parent_id is None

    def test_role_change_clears_parent(self, admin_client, make_user, db):
        parent = make_user(role="parent")
        child = make_user(role="student")
        child.parent_id = parent.id
        db.session.commit()
        admin_client.post(f"/users/{child.id}/role", data={"role": "parent"})
        db.session.refresh(child)
        assert child.parent_id is None

    def test_parent_sees_only_own_children_results(self, app, make_user, login_as, db):
        mom, other_mom = make_user(role="parent"), make_user(role="parent")
        kid = make_user(role="student", full_name="Петя Первый")
        stranger = make_user(role="student", full_name="Чужой Ребёнок")
        kid.parent_id, stranger.parent_id = mom.id, other_mom.id
        db.session.commit()
        topic = learning.get_topic("math", "order-of-operations")
        for child in (kid, stranger):
            c = app.test_client()
            login_as(c, child.phone, child.plain_password)
            c.post(
                "/learn/math/order-of-operations/check", json={"answers": correct_answers(topic)}
            )
        mom_client = app.test_client()
        login_as(mom_client, mom.phone, mom.plain_password)
        page = text(mom_client.get("/children"))
        assert "Петя Первый" in page and "Чужой Ребёнок" not in page
        assert "6/6" in page and "Порядок действий" in page and "попыток: 1" in page

    def test_parent_without_children_sees_empty_state(self, parent_client):
        assert "не привязан ни один ученик" in text(parent_client.get("/children"))

    def test_student_cannot_open_children_page(self, student_client):
        page = text(student_client.get("/children", follow_redirects=True))
        assert "доступен родителям" in page

    def test_anonymous_redirected(self, client):
        assert client.get("/children").status_code == 302

    def test_admin_sees_all_students(self, admin_client, make_user):
        make_user(role="student", full_name="Ученик Виден")
        assert "Ученик Виден" in text(admin_client.get("/children"))

    def test_parent_dashboard_link(self, parent_client):
        assert "/children" in text(parent_client.get("/dashboard"))


class TestRetryAndHintCard:
    TOPIC = ("belarusian", "word-combination")

    def url(self, suffix):
        return f"/learn/{self.TOPIC[0]}/{self.TOPIC[1]}/{suffix}"

    def test_wrong_answer_returns_hint_and_public_retry(self, student_client):
        topic = learning.get_topic(*self.TOPIC)
        answers = correct_answers(topic)
        answers["q1"] = "2"  # заведомо неверный вариант
        data = student_client.post(self.url("check"), json={"answers": answers}).get_json()
        first = data["results"][0]
        assert not first["correct"] and first["hint"] and first["retry"]["id"] == "q1r"
        assert set(first["retry"]) <= {"id", "text", "kind", "options"}
        assert all("retry" not in r for r in data["results"][1:])

    def test_correct_answer_has_no_retry_in_response(self, student_client):
        topic = learning.get_topic(*self.TOPIC)
        data = student_client.post(
            self.url("check"), json={"answers": correct_answers(topic)}
        ).get_json()
        assert all("retry" not in r and "hint" not in r for r in data["results"])

    def test_retry_endpoint_checks_without_saving(self, student_client, db):
        topic = learning.get_topic(*self.TOPIC)
        retry = topic["questions"][0]["retry"]
        right = student_client.post(
            self.url("retry"), json={"id": "q1r", "answer": str(retry["answer"])}
        ).get_json()
        wrong = student_client.post(
            self.url("retry"), json={"id": "q1r", "answer": str((retry["answer"] + 1) % 3)}
        ).get_json()
        assert right == {"correct": True} and wrong == {"correct": False}
        assert LearningAttempt.query.count() == 0

    def test_retry_unknown_question_404(self, student_client):
        response = student_client.post(self.url("retry"), json={"id": "q99r", "answer": "0"})
        assert response.status_code == 404

    def test_retry_unknown_topic_404(self, student_client):
        response = student_client.post("/learn/math/nope/retry", json={"id": "q1r", "answer": "0"})
        assert response.status_code == 404

    @pytest.mark.parametrize("body", [None, [], "x"])
    def test_retry_bad_payload(self, student_client, body):
        assert student_client.post(self.url("retry"), json=body).status_code == 400

    def test_retry_requires_student_role(self, parent_client, client):
        assert (
            parent_client.post(self.url("retry"), json={"id": "q1r", "answer": "0"}).status_code
            == 403
        )
        assert client.post(self.url("retry"), json={"id": "q1r", "answer": "0"}).status_code == 401

    def test_retry_csrf_enforced_when_enabled(self, student_client, app):
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            response = student_client.post(self.url("retry"), json={"id": "q1r", "answer": "0"})
        finally:
            app.config["WTF_CSRF_ENABLED"] = False
        assert response.status_code == 400

    def test_check_retry_helper(self):
        topic = learning.get_topic(*self.TOPIC)
        assert learning.check_retry(topic, "q1r", "0") in (True, False)
        assert learning.check_retry(topic, "nope", "0") is None
        math_topic = learning.get_topic("math", "order-of-operations")
        assert learning.check_retry(math_topic, "q1r", "0") is None  # у математики retry пока нет

    def test_subject_page_groups_topics_by_section_with_paragraphs(self, student_client):
        page = text(student_client.get("/learn/belarusian"))
        assert "Сінтаксіс і пунктуацыя" in page and "§ 28" in page
        assert "Источник тем" in page

    def test_topic_page_shows_paragraph_rule_and_example(self, student_client):
        topic = learning.get_topic(*self.TOPIC)
        page = text(student_client.get("/learn/belarusian/word-combination"))
        assert "§ 15–16" in page and topic["rule"][:30] in page and topic["example"][:20] in page
        assert "data-retry-url" in page
        # ответы и подсказки/аналогичные задания в страницу не попадают
        for q in topic["questions"]:
            assert q["hint"] not in page and q["retry"]["text"] not in page
