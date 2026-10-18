"""Structured shapes the Language Agent returns, plus a JSON-schema helper."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Line(_Strict):
    original: str
    pronunciation: str  # Arabic-letter approximation of how it is actually said
    translation_ar: str


class Expression(_Strict):
    text: str
    meaning_ar: str
    literal_ar: str
    pronunciation: str
    example: str
    example_ar: str
    usage_note_ar: str  # when/with whom natives say it, register, tone


class ConjugatedForm(_Strict):
    person: str
    form: str
    pronunciation: str


class Verb(_Strict):
    infinitive: str
    form_in_video: str
    meaning_ar: str
    tense: str
    person: str
    ending: str            # the ending that carries person/tense, e.g. "-ons", "-t", "-ed"
    ending_rule_ar: str    # why this ending, and how it sounds
    pronunciation: str
    conjugation: list[ConjugatedForm]
    example: str
    example_ar: str


class GrammarPoint(_Strict):
    point: str
    explanation_ar: str
    example: str
    example_ar: str


class Exercise(_Strict):
    type: Literal["cloze", "translate", "verb_ending", "shadowing"]
    target: str     # the exact `text` / `infinitive` / `point` of the item it trains
    prompt: str
    answer: str
    hint_ar: str


class Lesson(_Strict):
    language: str   # ISO 639-1 code of the video's language
    title: str
    summary_ar: str
    register_note_ar: str   # how colloquial the speech is, slang, accent notes
    lines: list[Line]
    expressions: list[Expression]
    verbs: list[Verb]
    grammar: list[GrammarPoint]
    exercises: list[Exercise]


class PracticeText(_Strict):
    title: str
    dialogue: list[Line]
    tips_ar: list[str]


def strict_schema(model: type[BaseModel]) -> dict:
    """JSON schema for ``model`` with every ``$ref`` inlined and titles dropped."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)
