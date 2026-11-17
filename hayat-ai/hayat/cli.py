"""Command line: hayat add | review | lesson | practice | report | goal | list."""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date
from pathlib import Path

from .db import Store, home_dir


def cmd_add(store: Store, args) -> int:
    from .agents import language, learning, transcription, video
    from .llm import Claude

    transcript_file = Path(args.transcript) if args.transcript else None
    src = None
    with tempfile.TemporaryDirectory(prefix="hayat-") as tmp:
        if transcript_file is None:
            print("🎬 Video Agent: جاري جلب الفيديو...")
            src = video.fetch(args.source, Path(tmp))
        print("📝 Transcription Agent: جاري التفريغ...")
        tr = transcription.transcribe(src, transcript_file, args.lang, args.whisper_model)
    title = src.title if src else Path(args.source).stem
    print(f"   ({tr.method}, {len(tr.text.split())} كلمة)")

    print("🧠 Language Agent: جاري استخراج التعابير والأفعال والقواعد...")
    lesson = language.build_lesson(Claude(), tr.text, title, tr.language or args.lang)

    print("📚 Learning Agent: جاري الحفظ بالذاكرة...")
    saved = learning.save_lesson(store, lesson, args.source, tr.text)
    print(f"\n✅ درس #{saved.video_id}: {lesson.title}")
    print(f"   {saved.new_items} عنصر جديد · {saved.known_items} بتعرفهم من قبل")
    print(f"   اقرأ الدرس: hayat lesson {saved.video_id}   ·   ابدأ التدريب: hayat review")
    return 0


def cmd_lesson(store: Store, args) -> int:
    import json

    from .agents.learning import render_lesson

    row = store.video(args.video_id) if args.video_id else (store.videos() or [None])[0]
    if row is None:
        print("ما في دروس بعد. أضف فيديو: hayat add <link>")
        return 1
    print(render_lesson(json.loads(row["lesson_json"])))
    store.log("lesson", row["id"])
    return 0


def cmd_review(store: Store, args) -> int:
    from .agents.learning import run_review

    run_review(store, date.today(), args.limit)
    return 0


def cmd_practice(store: Store, args) -> int:
    from .agents.language import build_practice
    from .llm import Claude

    weak = store.weak_items(8)
    if not weak:
        print("ما في نقاط ضعف مسجّلة بعد - راجع شوي أول: hayat review")
        return 0
    text = build_practice(Claude(), [dict(w) for w in weak], weak[0]["language"])
    print(f"# {text.title}\n")
    for line in text.dialogue:
        print(f"- {line.original}\n  🔊 {line.pronunciation}\n  {line.translation_ar}")
    print("\n💡 " + "\n💡 ".join(text.tips_ar))
    store.log("practice", None, text.title)
    return 0


def cmd_report(store: Store, args) -> int:
    from .report import build_report, render_report

    day = date.fromisoformat(args.date) if args.date else date.today()
    text = render_report(build_report(store, day))
    print(text)
    reports = home_dir() / "reports"
    reports.mkdir(exist_ok=True)
    out = reports / f"{day.isoformat()}.md"
    out.write_text(text, encoding="utf-8")
    print(f"(محفوظ في {out})")
    return 0


def cmd_goal(store: Store, args) -> int:
    updates = {"daily_new": args.daily_new, "daily_reviews": args.daily_reviews,
               "target_mastered": args.target, "target_date": args.by}
    for key, value in updates.items():
        if value is not None:
            if key == "target_date":
                date.fromisoformat(value)
            store.set_setting(key, str(value))
    print(f"🎯 كل يوم: {store.setting('daily_new')} جديد · {store.setting('daily_reviews')} مراجعة")
    print(f"🏁 الهدف: {store.setting('target_mastered')} عنصر مُتقَن"
          + (f" قبل {store.setting('target_date')}" if store.setting("target_date") else ""))
    return 0


def cmd_list(store: Store, args) -> int:
    rows = store.videos()
    if not rows:
        print("ما في دروس بعد.")
    for row in rows:
        print(f"#{row['id']}  [{row['language']}]  {row['title']}  ·  {row['created_at'][:10]}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hayat", description="Hayat AI - تعلّم اللغة المحكية من فيديوهات الحياة")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="حوّل فيديو (رابط أو ملف) لدرس")
    a.add_argument("source", help="رابط TikTok/Instagram/YouTube أو مسار ملف فيديو")
    a.add_argument("--transcript", help="ملف نص/ترجمة جاهز (txt/vtt/srt) بدل التفريغ")
    a.add_argument("--lang", help="لغة الفيديو (مثلاً en, fr, nl, de, es) - اختياري")
    a.add_argument("--whisper-model", default="small", help="حجم موديل Whisper المحلي")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("lesson", help="اعرض درس")
    l.add_argument("video_id", nargs="?", type=int)
    l.set_defaults(func=cmd_lesson)

    r = sub.add_parser("review", help="جلسة مراجعة وتمارين ذكية")
    r.add_argument("--limit", type=int)
    r.set_defaults(func=cmd_review)

    sub.add_parser("practice", help="حوار جديد مبني على نقاط ضعفك").set_defaults(func=cmd_practice)

    rp = sub.add_parser("report", help="تقرير آخر اليوم: شو شفت وشو تعلمت وهل إنت على الطريق")
    rp.add_argument("--date", help="YYYY-MM-DD (الافتراضي: اليوم)")
    rp.set_defaults(func=cmd_report)

    g = sub.add_parser("goal", help="حدّد هدفك اليومي والكبير")
    g.add_argument("--daily-new", type=int)
    g.add_argument("--daily-reviews", type=int)
    g.add_argument("--target", type=int, help="عدد العناصر المُتقَنة المطلوب")
    g.add_argument("--by", help="تاريخ الهدف YYYY-MM-DD")
    g.set_defaults(func=cmd_goal)

    sub.add_parser("list", help="كل الدروس").set_defaults(func=cmd_list)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    store = Store()
    try:
        return args.func(store, args)
    except Exception as exc:  # show a friendly one-line error, not a traceback
        from .agents.transcription import TranscriptionError
        from .agents.video import VideoError
        from .llm import LLMError

        if isinstance(exc, (VideoError, TranscriptionError, LLMError, ValueError)):
            print(f"❌ {exc}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
