"""Learning Agent: store lessons in memory, plan sessions, run reviews.

It adapts to you: items you get wrong come back sooner and first, and for each
item it picks the exercise type you struggle with most.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

from ..db import Store
from ..schemas import Lesson
from ..srs import AGAIN, GOOD, GRADES, HARD, schedule


@dataclass
class SaveResult:
    video_id: int
    new_items: int
    known_items: int


def save_lesson(store: Store, lesson: Lesson, source: str, transcript: str) -> SaveResult:
    lang = lesson.language
    video_id = store.add_video(source, lesson.title, lang, transcript, lesson.model_dump())
    ids: dict[str, int] = {}
    new = known = 0

    def add(kind, text, *args, **kwargs):
        nonlocal new, known
        item_id, created = store.add_item(video_id, kind, lang, text, *args, **kwargs)
        ids[text] = item_id
        new, known = (new + 1, known) if created else (new, known + 1)
        return created

    for e in lesson.expressions:
        add("expression", e.text, e.meaning_ar, e.pronunciation, e.example, e.example_ar,
            {"literal_ar": e.literal_ar, "usage_note_ar": e.usage_note_ar})
    for v in lesson.verbs:
        add("verb", v.infinitive, v.meaning_ar, v.pronunciation, v.example, v.example_ar,
            {"form_in_video": v.form_in_video, "tense": v.tense, "person": v.person,
             "ending": v.ending, "ending_rule_ar": v.ending_rule_ar,
             "conjugation": [c.model_dump() for c in v.conjugation]})
    for g in lesson.grammar:
        add("grammar", g.point, g.explanation_ar, "", g.example, g.example_ar)

    for ex in lesson.exercises:
        item_id = ids.get(ex.target)
        if item_id is not None:
            store.add_exercise(item_id, ex.type, ex.prompt, ex.answer, ex.hint_ar)
    return SaveResult(video_id, new, known)


def render_lesson(lesson: dict) -> str:
    """Markdown view of a stored lesson."""
    out = [f"# {lesson['title']}", "", lesson["summary_ar"], "",
           f"> {lesson['register_note_ar']}", "", "## النص", ""]
    for line in lesson["lines"]:
        out += [f"- **{line['original']}**", f"  - 🔊 {line['pronunciation']}",
                f"  - {line['translation_ar']}"]
    out += ["", "## التعابير (كلمات من الحياة)", ""]
    for e in lesson["expressions"]:
        out += [f"### {e['text']}  —  {e['meaning_ar']}",
                f"🔊 {e['pronunciation']} · حرفيًا: {e['literal_ar']}", "",
                f"{e['example']}  ←  {e['example_ar']}", "", f"💡 {e['usage_note_ar']}", ""]
    out += ["## الأفعال ونهاياتها", ""]
    for v in lesson["verbs"]:
        out += [f"### {v['infinitive']} → **{v['form_in_video']}**  ({v['meaning_ar']})",
                f"الزمن: {v['tense']} · الضمير: {v['person']} · النهاية: **{v['ending']}**",
                f"🔊 {v['pronunciation']}", "", v["ending_rule_ar"], "",
                "| الضمير | الصيغة | النطق |", "|---|---|---|"]
        out += [f"| {c['person']} | {c['form']} | {c['pronunciation']} |" for c in v["conjugation"]]
        out += ["", f"{v['example']}  ←  {v['example_ar']}", ""]
    out += ["## القواعد (المكياج)", ""]
    for g in lesson["grammar"]:
        out += [f"### {g['point']}", g["explanation_ar"], "",
                f"{g['example']}  ←  {g['example_ar']}", ""]
    return "\n".join(out)


# -- sessions -----------------------------------------------------------------

def reviews_done_today(store: Store, today: date) -> int:
    return store.conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE substr(reviewed_at, 1, 10) = ?", (today.isoformat(),)
    ).fetchone()[0]


def new_started_today(store: Store, today: date) -> int:
    return store.conn.execute(
        "SELECT COUNT(*) FROM srs WHERE substr(first_seen, 1, 10) = ?", (today.isoformat(),)
    ).fetchone()[0]


def plan_session(store: Store, today: date, limit: int | None = None) -> list:
    """Due reviews (weakest first), then new items up to today's goal."""
    review_budget = max(0, int(store.setting("daily_reviews")) - reviews_done_today(store, today))
    new_budget = max(0, int(store.setting("daily_new")) - new_started_today(store, today))
    items = list(store.due_items(today, review_budget)) + list(store.new_items(new_budget))
    return items[:limit] if limit is not None else items


def pick_exercise(store: Store, item_id: int):
    """The exercise type with the highest error rate; unseen types first."""
    exercises = store.exercises_for(item_id)
    if not exercises:
        return None
    stats = store.wrong_count_by_type(item_id)

    def score(ex):
        wrong, n = stats.get(ex["type"], (0, 0))
        return (n == 0, wrong / n if n else 0)

    return max(exercises, key=score)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'")
    text = re.sub(r"[^\w' ]+", " ", text)
    return " ".join(text.split())


def check_answer(given: str, expected: str) -> bool:
    return normalize(given) == normalize(expected)


def grade_review(store: Store, item_id: int, exercise_id: int | None, grade: int,
                 correct: bool, seconds: float = 0.0, now: datetime | None = None) -> None:
    now = now or datetime.now()
    state = schedule(store.srs_state(item_id), grade, now.date())
    store.record_review(item_id, exercise_id, grade, correct, state, seconds, now)


def run_review(store: Store, today: date, limit: int | None = None,
               ask: Callable[[str], str] = input, say: Callable[[str], None] = print) -> int:
    items = plan_session(store, today, limit)
    if not items:
        say("✅ ما في مراجعات اليوم. أضف فيديو جديد: hayat add <link>")
        return 0
    say(f"📚 جلسة اليوم: {len(items)} عنصر. اكتب جوابك، أو Enter لتشوف الجواب، أو q للخروج.\n")
    done = 0
    for item in items:
        ex = pick_exercise(store, item["id"])
        if ex is None:
            ex_type, prompt, answer, hint = "recall", f"شو معنى: {item['text']}", item["meaning_ar"], ""
        else:
            ex_type, prompt, answer, hint = ex["type"], ex["prompt"], ex["answer"], ex["hint_ar"]
        say(f"[{ex_type}] {prompt}")
        if hint:
            say(f"  💡 {hint}")
        start = time.monotonic()
        given = ask("> ").strip()
        if given.lower() == "q":
            break
        seconds = time.monotonic() - start

        if ex_type in ("shadowing", "recall") or not given:
            say(f"  الجواب: {answer}")
            if item["pronunciation"]:
                say(f"  🔊 {item['pronunciation']}")
            raw = ask("  قيّم حالك: 1=نسيت 2=صعب 3=تمام 4=سهل > ").strip()
            grade = GRADES.get(raw, GOOD)
            correct = grade >= GOOD
        else:
            correct = check_answer(given, answer)
            if correct:
                say("  ✅ صح!")
                grade = GOOD
            else:
                say(f"  ❌ الصحيح: {answer}")
                if item["pronunciation"]:
                    say(f"  🔊 {item['pronunciation']}")
                grade = AGAIN if ask("  كنت قريب؟ (y/n) > ").strip().lower() != "y" else HARD
        grade_review(store, item["id"], ex["id"] if ex else None, grade, correct, seconds)
        done += 1
        say("")
    store.log("review", None, f"{done} items")
    say(f"🎉 خلصت {done} مراجعة. شوف تقريرك: hayat report")
    return done
