from datetime import date, datetime, timedelta

import pytest

from hayat.agents import learning, transcription
from hayat.agents.language import build_lesson
from hayat.db import Store
from hayat.report import build_report, render_report
from hayat.schemas import Lesson, strict_schema
from hayat.srs import AGAIN, EASY, GOOD, MASTERED_INTERVAL, SrsState, schedule

LESSON = {
    "language": "fr",
    "title": "Au café",
    "summary_ar": "حوار قصير بالمقهى",
    "register_note_ar": "كلام عامي",
    "lines": [{"original": "On y va ?", "pronunciation": "أون إي ڤا", "translation_ar": "يلا نروح؟"}],
    "expressions": [{
        "text": "on y va", "meaning_ar": "يلا", "literal_ar": "نحن نذهب هناك",
        "pronunciation": "أون إي ڤا", "example": "Allez, on y va !", "example_ar": "يلا نروح!",
        "usage_note_ar": "كتير شائعة",
    }],
    "verbs": [{
        "infinitive": "aller", "form_in_video": "va", "meaning_ar": "يروح", "tense": "présent",
        "person": "on", "ending": "-a", "ending_rule_ar": "فعل شاذ", "pronunciation": "ڤا",
        "conjugation": [{"person": "je", "form": "vais", "pronunciation": "ڤيه"}],
        "example": "Je vais au café.", "example_ar": "رايح عالمقهى.",
    }],
    "grammar": [{"point": "on = nous", "explanation_ar": "on بالعامية بمعنى نحن",
                 "example": "On mange ?", "example_ar": "منوكل؟"}],
    "exercises": [
        {"type": "cloze", "target": "on y va", "prompt": "Allez, ___ !", "answer": "on y va", "hint_ar": "يلا"},
        {"type": "verb_ending", "target": "aller", "prompt": "aller, on, présent", "answer": "va", "hint_ar": ""},
        {"type": "translate", "target": "unknown item", "prompt": "x", "answer": "y", "hint_ar": ""},
    ],
}


class FakeLLM:
    def __init__(self):
        self.calls = []

    def structured(self, system, user, output, effort="medium"):
        self.calls.append(user)
        return output.model_validate(LESSON)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


def test_srs_progression_and_reset():
    today = date(2026, 1, 1)
    s = SrsState()
    intervals = []
    for _ in range(4):
        s = schedule(s, GOOD, today)
        intervals.append(s.interval_days)
    assert intervals[:2] == [1, 3]
    assert intervals[2] > intervals[1] and intervals[3] > intervals[2]
    failed = schedule(s, AGAIN, today)
    assert failed.interval_days == 1 and failed.repetitions == 0 and failed.lapses == 1
    assert schedule(SrsState(), EASY, today).interval_days > 1


def test_strict_schema_has_no_refs():
    schema = strict_schema(Lesson)
    assert "$ref" not in str(schema) and "$defs" not in schema
    assert schema["additionalProperties"] is False
    verb = schema["properties"]["verbs"]["items"]
    assert verb["properties"]["conjugation"]["items"]["additionalProperties"] is False


def test_parse_vtt_drops_timings_and_rolling_duplicates():
    vtt = """WEBVTT
Kind: captions

00:00:00.000 --> 00:00:01.000
<c>On y va</c>

00:00:01.000 --> 00:00:02.000
On y va

00:00:02.000 --> 00:00:03.000
c'est parti
"""
    assert transcription.parse_vtt(vtt) == "On y va\nc'est parti"


def test_save_lesson_dedupes_and_links_exercises(store):
    lesson = build_lesson(FakeLLM(), "On y va ?", "Au café", "fr")
    first = learning.save_lesson(store, lesson, "https://tiktok.com/x", "On y va ?")
    assert (first.new_items, first.known_items) == (3, 0)
    second = learning.save_lesson(store, lesson, "https://tiktok.com/y", "On y va ?")
    assert (second.new_items, second.known_items) == (0, 3)
    # The exercise with an unknown target is skipped, not attached to a random item.
    assert store.conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0] == 4
    md = learning.render_lesson(lesson.model_dump())
    assert "on y va" in md and "| je | vais | ڤيه |" in md


def test_check_answer_is_forgiving_about_case_accents_punctuation():
    assert learning.check_answer("  On y va!! ", "on y va")
    assert learning.check_answer("cafe", "café")
    assert not learning.check_answer("on va", "on y va")


def test_review_session_adapts_to_mistakes(store):
    learning.save_lesson(store, Lesson.model_validate(LESSON), "src", "t")
    store.set_setting("daily_new", "2")
    today = date.today()
    answers = iter(["wrong answer", "n", "va"])
    out = []
    done = learning.run_review(store, today, ask=lambda _: next(answers), say=out.append)
    assert done == 2
    weak = store.weak_items()
    assert [w["text"] for w in weak] == ["on y va"]
    # The failed item is due again tomorrow and comes first.
    due = store.due_items(today + timedelta(days=1), 10)
    assert due[0]["text"] == "on y va"
    # Daily new-item goal reached: no fresh items left today.
    assert store.new_items(10) and learning.plan_session(store, today) == []


def test_daily_report_shows_watched_learned_and_goal(store):
    learning.save_lesson(store, Lesson.model_validate(LESSON), "https://tiktok.com/x", "t")
    today = date.today()
    store.set_setting("target_mastered", "3")
    store.set_setting("target_date", (today + timedelta(days=60)).isoformat())
    now = datetime.now()
    for item in store.new_items(10):
        learning.grade_review(store, item["id"], None, GOOD, True, 5, now)
    report = build_report(store, today)
    assert report.videos == [("Au café", "https://tiktok.com/x")]
    assert len(report.new_items) == 3
    assert report.reviews == 3 and report.accuracy == 1.0
    assert report.streak == 1
    assert report.projected_date is not None
    text = render_report(report)
    assert "Au café" in text and "on y va" in text and "الهدف الكبير" in text


def test_mastery_counts_toward_goal(store):
    learning.save_lesson(store, Lesson.model_validate(LESSON), "src", "t")
    item = store.new_items(1)[0]
    when = datetime.now() - timedelta(days=90)
    while store.srs_state(item["id"]).interval_days < MASTERED_INTERVAL:
        learning.grade_review(store, item["id"], None, EASY, True, 1, when)
        when += timedelta(days=store.srs_state(item["id"]).interval_days)
    assert build_report(store, date.today()).mastered == 1
