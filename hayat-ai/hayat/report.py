"""Daily report: what you watched, what you learned, and whether you're on track."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from .db import Store

PACE_WINDOW_DAYS = 14


@dataclass
class DailyReport:
    day: date
    videos: list[tuple[str, str]] = field(default_factory=list)  # (title, source)
    new_items: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, text, meaning)
    reviews: int = 0
    correct: int = 0
    minutes: float = 0.0
    weak: list[tuple[str, str]] = field(default_factory=list)
    total_items: int = 0
    mastered: int = 0
    mastered_today: int = 0
    streak: int = 0
    daily_new_goal: int = 0
    daily_review_goal: int = 0
    target_mastered: int = 0
    target_date: date | None = None
    pace_per_day: float = 0.0
    projected_date: date | None = None
    needed_per_day: float | None = None

    @property
    def accuracy(self) -> float:
        return self.correct / self.reviews if self.reviews else 0.0

    @property
    def on_track(self) -> bool | None:
        if not self.target_date:
            return None
        if self.mastered >= self.target_mastered:
            return True
        return self.projected_date is not None and self.projected_date <= self.target_date


def _active_days(store: Store) -> set[date]:
    rows = store.conn.execute(
        "SELECT substr(reviewed_at, 1, 10) AS d FROM reviews "
        "UNION SELECT substr(created_at, 1, 10) FROM activity WHERE kind = 'video'"
    ).fetchall()
    return {date.fromisoformat(r["d"]) for r in rows}


def _streak(active: set[date], day: date) -> int:
    # Today still counts if you haven't studied yet - the streak breaks tomorrow.
    cursor = day if day in active else day - timedelta(days=1)
    streak = 0
    while cursor in active:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def build_report(store: Store, day: date | None = None) -> DailyReport:
    day = day or date.today()
    d = day.isoformat()
    q = store.conn.execute
    r = DailyReport(day=day)

    r.videos = [(row["title"], row["source"]) for row in
                q("SELECT title, source FROM videos WHERE substr(created_at, 1, 10) = ?", (d,))]
    r.new_items = [(row["kind"], row["text"], row["meaning_ar"]) for row in q(
        "SELECT i.kind, i.text, i.meaning_ar FROM items i JOIN srs s ON s.item_id = i.id "
        "WHERE substr(s.first_seen, 1, 10) = ? ORDER BY s.first_seen", (d,))]
    row = q("SELECT COUNT(*) AS n, COALESCE(SUM(correct), 0) AS ok, COALESCE(SUM(seconds), 0) AS s "
            "FROM reviews WHERE substr(reviewed_at, 1, 10) = ?", (d,)).fetchone()
    r.reviews, r.correct, r.minutes = row["n"], row["ok"], row["s"] / 60
    r.weak = [(w["text"], w["meaning_ar"]) for w in store.weak_items(5)]

    r.total_items = q("SELECT COUNT(*) FROM items").fetchone()[0]
    r.mastered = q("SELECT COUNT(*) FROM srs WHERE mastered_at IS NOT NULL "
                   "AND substr(mastered_at, 1, 10) <= ?", (d,)).fetchone()[0]
    r.mastered_today = q("SELECT COUNT(*) FROM srs WHERE substr(mastered_at, 1, 10) = ?",
                         (d,)).fetchone()[0]
    r.streak = _streak(_active_days(store), day)

    r.daily_new_goal = int(store.setting("daily_new"))
    r.daily_review_goal = int(store.setting("daily_reviews"))
    r.target_mastered = int(store.setting("target_mastered"))
    target = store.setting("target_date")
    r.target_date = date.fromisoformat(target) if target else None

    # Pace: items started over the last two weeks. An item is mastered roughly
    # a month after you start it, so learning pace predicts mastery pace.
    first = q("SELECT MIN(substr(first_seen, 1, 10)) FROM srs").fetchone()[0]
    window = min(PACE_WINDOW_DAYS, (day - date.fromisoformat(first)).days + 1) if first else 1
    since = (day - timedelta(days=window - 1)).isoformat()
    started = q("SELECT COUNT(*) FROM srs WHERE substr(first_seen, 1, 10) BETWEEN ? AND ?",
                (since, d)).fetchone()[0]
    r.pace_per_day = started / max(window, 1)
    remaining = max(0, r.target_mastered - r.mastered)
    if remaining == 0:
        r.projected_date = day
    elif r.pace_per_day > 0:
        r.projected_date = day + timedelta(days=math.ceil(remaining / r.pace_per_day) + 21)
    if r.target_date and remaining:
        days_left = (r.target_date - day).days - 21
        r.needed_per_day = remaining / days_left if days_left > 0 else None
    return r


def _bar(value: int, goal: int, width: int = 10) -> str:
    filled = min(width, round(width * value / goal)) if goal else width
    return "█" * filled + "░" * (width - filled) + f" {value}/{goal}"


def render_report(r: DailyReport) -> str:
    out = [f"# 📊 تقرير يوم {r.day.isoformat()}", ""]

    out += ["## 🎬 شو شفت اليوم", ""]
    out += [f"- {t}  ({s})" for t, s in r.videos] or ["- ما شفت فيديو جديد اليوم."]

    out += ["", "## 🧠 شو تعلمت اليوم", ""]
    labels = {"expression": "تعبير", "verb": "فعل", "grammar": "قاعدة"}
    out += [f"- [{labels.get(k, k)}] **{t}** — {m}" for k, t, m in r.new_items] \
        or ["- ما بلّشت عناصر جديدة اليوم."]

    out += ["", "## 🔁 المراجعة", "",
            f"- مراجعات: {r.reviews} · دقّة: {r.accuracy:.0%} · وقت: {r.minutes:.0f} دقيقة",
            f"- أتقنت اليوم: {r.mastered_today} · مجموع المُتقَن: {r.mastered} من {r.total_items}",
            f"- 🔥 سلسلة الأيام: {r.streak}"]

    out += ["", "## 🎯 هدف اليوم", "",
            f"- عناصر جديدة: {_bar(len(r.new_items), r.daily_new_goal)}",
            f"- مراجعات:     {_bar(r.reviews, r.daily_review_goal)}"]

    if r.weak:
        out += ["", "## ⚠️ نقاط ضعفك (رح ترجعلك أكتر)", ""]
        out += [f"- **{t}** — {m}" for t, m in r.weak]

    out += ["", "## 🏁 الهدف الكبير", ""]
    if r.target_date is None:
        out += [f"- الهدف: {r.target_mastered} عنصر مُتقَن. حدّد تاريخ: "
                "hayat goal --target 1000 --by 2027-06-01"]
    else:
        out += [f"- الهدف: {r.target_mastered} عنصر مُتقَن قبل {r.target_date.isoformat()}",
                f"- سرعتك الحالية: {r.pace_per_day:.1f} عنصر جديد باليوم"]
        if r.projected_date:
            out.append(f"- بهالسرعة بتوصل تقريبًا: {r.projected_date.isoformat()}")
        if r.on_track:
            out.append("- ✅ إنت على الطريق الصح. كمّل هيك!")
        elif r.needed_per_day is not None:
            out.append(f"- ⚠️ لتحقق هدفك لازم تتعلم ~{math.ceil(r.needed_per_day)} عنصر جديد باليوم "
                       f"وتراجعهم كل يوم.")
        else:
            out.append("- ⚠️ الوقت ما بيكفي لهالهدف بهالتاريخ. فكّر تمدّد التاريخ أو تصغّر الهدف.")
    return "\n".join(out) + "\n"
