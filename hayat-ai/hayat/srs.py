"""Spaced repetition (SM-2 variant).

Each learning item carries a small state: ease, interval and repetitions.
A review grade moves the item forward (longer interval) or back to the start.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Grades the learner can give after an exercise.
AGAIN, HARD, GOOD, EASY = 1, 3, 4, 5
GRADES = {"1": AGAIN, "2": HARD, "3": GOOD, "4": EASY}

# An item whose interval reaches this many days counts as "mastered".
MASTERED_INTERVAL = 21


@dataclass
class SrsState:
    ease: float = 2.5
    interval_days: int = 0
    repetitions: int = 0
    lapses: int = 0
    due_date: date | None = None

    @property
    def mastered(self) -> bool:
        return self.interval_days >= MASTERED_INTERVAL


def schedule(state: SrsState, grade: int, today: date) -> SrsState:
    """Return the new state after a review with ``grade`` (1-5)."""
    if grade < HARD:
        # Forgotten: start again tomorrow, ease drops.
        return SrsState(
            ease=max(1.3, state.ease - 0.2),
            interval_days=1,
            repetitions=0,
            lapses=state.lapses + 1,
            due_date=today + timedelta(days=1),
        )

    repetitions = state.repetitions + 1
    if repetitions == 1:
        interval = 1
    elif repetitions == 2:
        interval = 3
    else:
        interval = round(state.interval_days * state.ease)
    if grade == HARD:
        interval = max(1, round(interval * 0.6))
    elif grade == EASY:
        interval = round(interval * 1.3) + 1

    ease = state.ease + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    return SrsState(
        ease=max(1.3, ease),
        interval_days=interval,
        repetitions=repetitions,
        lapses=state.lapses,
        due_date=today + timedelta(days=interval),
    )
