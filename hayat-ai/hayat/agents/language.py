"""Language Agent: turn a transcript into a real-life spoken-language lesson."""

from __future__ import annotations

from ..llm import LLM
from ..schemas import Lesson, PracticeText

SYSTEM = """\
You are Hayat, a coach who teaches the language people actually speak in daily life.
The learner is an Arabic speaker. Write every explanation in clear, simple Arabic
(Levantine-friendly). Keep target-language text exactly as spoken.

Teaching philosophy - follow it in everything you produce:
- Language = words + "makeup". The words (expressions, chunks, verbs) come first;
  grammar is only the makeup that makes them fit. Teach whole chunks people say,
  not isolated dictionary words, so the brain can answer automatically without
  translating.
- Colloquial first: slang, contractions, fillers, and how natives really pronounce
  things (linking, dropped sounds). Mention when something is informal or rude.
- Verbs: always show the ending that carries person and tense, what kind of
  ending it is, how it sounds, and how it changes with the tense.
- Pronunciation: write it in Arabic letters so an Arabic speaker can read it
  aloud, as close as possible to the real spoken sound.
"""

LESSON_TASK = """\
Turn this transcript of a real video into a lesson.

Video title: {title}
Language hint: {language}

Transcript:
<transcript>
{transcript}
</transcript>

Produce:
- lines: every spoken line with pronunciation (Arabic letters) and Arabic translation.
  Fix obvious transcription errors silently.
- expressions: the 5-15 most useful real-life chunks/phrases from the video.
- verbs: every important verb form in the video with its ending, tense, person,
  the rule behind the ending (Arabic), and a short conjugation table for that tense.
- grammar: only the 1-4 grammar points ("makeup") needed to understand the video.
- exercises: 2-3 exercises per expression and per verb. Types:
  cloze (a sentence with ___ where the chunk goes; answer = the chunk),
  translate (Arabic sentence -> answer in the target language),
  verb_ending (ask for the correct form for a person/tense; answer = the form),
  shadowing (a line to repeat aloud; answer = the line).
  `target` must equal the item's `text` (expressions), `infinitive` (verbs) or
  `point` (grammar) exactly.
"""

PRACTICE_TASK = """\
The learner keeps making mistakes with these items (language: {language}):

{items}

Write a short, natural everyday dialogue (8-14 lines) that reuses all of them in
new situations, the way people really talk. Then give 2-4 short tips in Arabic
about the mistakes they are likely making.
"""


def build_lesson(llm: LLM, transcript: str, title: str, language: str | None) -> Lesson:
    task = LESSON_TASK.format(title=title, language=language or "detect it", transcript=transcript)
    return llm.structured(SYSTEM, task, Lesson, effort="medium")


def build_practice(llm: LLM, items: list[dict], language: str) -> PracticeText:
    listing = "\n".join(f"- {i['text']} ({i['meaning_ar']})" for i in items)
    return llm.structured(SYSTEM, PRACTICE_TASK.format(language=language, items=listing),
                          PracticeText, effort="low")
