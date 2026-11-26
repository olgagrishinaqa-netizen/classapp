"""Английский язык, 5 класс: оригинальные задания по темам программы."""

# fmt: off

SUBJECT = {
    "slug": "english",
    "title": "Английский язык",
    "icon": "Eng",
    "description": "Грамматика и лексика",
}


def choice(text, options, answer, hint):
    return {"text": text, "options": options, "answer": answer, "hint": hint}


def typed(text, answers, hint):
    return {"text": text, "answers": answers, "hint": hint}


TOPICS = [
    {
        "slug": "verb-to-be",
        "title": "Глагол to be (am / is / are)",
        "rule": (
            "Глагол to be в настоящем времени: I am, he / she / it is, we / you / they are. "
            "Для множественного числа существительных используется are: my parents are. "
            "Вопрос: Are you a pupil? Отрицание: He is not (isn't) a teacher."
        ),
        "questions": [
            typed("She ___ a pupil. (am / is / are)", ["is"], "С she, he, it используется is."),
            typed("I ___ eleven years old. (am / is / are)", ["am"], "С местоимением I используется am."),
            typed("They ___ my friends. (am / is / are)", ["are"], "С we, you, they используется are."),
            choice("My parents ___ at home.", ["is", "are", "am"], 1, "Parents — множественное число (они), поэтому are."),
            choice("___ you a pupil?", ["Is", "Am", "Are"], 2, "В вопросе глагол ставится перед подлежащим; с you используется are."),
            choice("Выберите верное отрицание: He ___ a teacher.", ["isn't", "aren't", "amn't"], 0, "С he используется is, отрицание — is not (isn't)."),
        ],
    },
    {
        "slug": "plural-nouns",
        "title": "Множественное число существительных",
        "rule": (
            "Обычно множественное число образуется добавлением -s: book — books. "
            "После -s, -x, -ch, -sh добавляется -es: box — boxes, bus — buses. "
            "Если слово оканчивается на согласную + y, то y меняется на -ies: city — cities. "
            "Исключения нужно запомнить: child — children, man — men, woman — women, foot — feet, tooth — teeth."
        ),
        "questions": [
            typed("Напишите множественное число слова: box", ["boxes"], "После -x добавляется -es: boxes."),
            typed("Напишите множественное число слова: child", ["children"], "Это исключение: child — children."),
            typed("Напишите множественное число слова: city", ["cities"], "Согласная + y: y меняется на ies — cities."),
            choice("Выберите правильное множественное число слова «foot»:", ["foots", "feet", "feets"], 1, "Исключение: foot — feet."),
            choice("Выберите правильное множественное число слова «bus»:", ["buss", "buses", "busies"], 1, "После -s добавляется -es: buses."),
            choice("Выберите правильное множественное число слова «man»:", ["mans", "men", "mens"], 1, "Исключение: man — men."),
        ],
    },
    {
        "slug": "present-simple",
        "title": "Present Simple",
        "rule": (
            "Present Simple используется для регулярных действий и фактов. С he, she, it к глаголу "
            "добавляется -s / -es: he works, she goes, it watches. Вопрос и отрицание строятся с do / does: "
            "Does he like pizza? He doesn't like pizza. После does и doesn't глагол стоит в начальной форме "
            "(без -s)."
        ),
        "questions": [
            typed("She ___ (go) to school every day. Напишите правильную форму.", ["goes"], "С she к глаголу go добавляется -es: goes."),
            typed("My brother ___ (watch) TV in the evening. Напишите правильную форму.", ["watches"], "После -ch добавляется -es: watches."),
            choice("___ he like pizza?", ["Do", "Does", "Is"], 1, "В вопросе с he, she, it используется does."),
            choice("He doesn't ___ milk.", ["likes", "like", "liking"], 1, "После doesn't глагол стоит в начальной форме, без -s."),
            choice("They ___ football on Sunday.", ["plays", "play", "playing"], 1, "С they глагол остаётся в начальной форме, без -s: play."),
            choice("Выберите правильное предложение:", ["She read books.", "She reads books.", "She does reads books."], 1, "С she к глаголу добавляется -s: reads."),
        ],
    },
    {
        "slug": "articles-there-is",
        "title": "Артикли a / an и there is / there are",
        "rule": (
            "Артикль a ставится перед словами, которые начинаются с согласного звука (a book, a university), "
            "an — перед словами, которые начинаются с гласного звука (an apple, an hour). "
            "There is используется с единственным числом (There is a book on the table), "
            "there are — со множественным (There are two cats in the room)."
        ),
        "questions": [
            choice("___ apple", ["a", "an"], 1, "Слово apple начинается с гласного звука, поэтому an."),
            choice("___ book", ["a", "an"], 0, "Слово book начинается с согласного звука, поэтому a."),
            choice("___ umbrella", ["a", "an"], 1, "Слово umbrella начинается с гласного звука [ʌ], поэтому an."),
            choice("___ university", ["a", "an"], 0, "Слово university начинается со звука [j] (согласный), поэтому a."),
            choice("There ___ a book on the table.", ["is", "are"], 0, "Книга одна (единственное число), поэтому there is."),
            choice("There ___ two cats in the room.", ["is", "are"], 1, "Две кошки (множественное число), поэтому there are."),
        ],
    },
    {
        "slug": "have-got-can",
        "title": "have got и can",
        "rule": (
            "Для выражения принадлежности используется have got / has got: I have got a dog, "
            "she has got a cat. Отрицание: haven't got / hasn't got. "
            "Can обозначает умение и возможность; после can глагол стоит в начальной форме, "
            "без to и без -s: He can swim. Вопрос: Can you swim? — Yes, I can. / No, I can't."
        ),
        "questions": [
            typed("She ___ got a dog. (have / has)", ["has"], "С she, he, it используется has got."),
            typed("I ___ got a brother. (have / has)", ["have"], "С I, we, you, they используется have got."),
            choice("He ___ got a bike.", ["haven't", "hasn't", "doesn't"], 1, "С he отрицание: hasn't got."),
            choice("___ you swim?", ["Can", "Do", "Are"], 0, "Для вопроса об умении используется can: Can you swim?"),
            choice("Birds ___ fly.", ["can", "cans", "can to"], 0, "Can не изменяется по лицам и не употребляется с to."),
            choice("Выберите правильное предложение:", ["He can swims.", "He can swim.", "He cans swim."], 1, "После can глагол стоит в начальной форме, без -s: He can swim."),
        ],
    },
]
