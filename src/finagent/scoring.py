"""Score agent answers against FinanceBench gold answers.

Numeric questions (most of FinanceBench) are scored automatically: correct if
any number in the prediction matches a gold number within 1%, allowing unit
and percent/ratio rescaling ("$1.58 billion" == "$1577.00" in millions).
Yes/no questions are scored on polarity. Other text answers can be scored by
an optional LLM judge; without one they are marked "needs_review" rather
than guessed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .grounding import answer_numbers
from .llm import LLMClient, extract_json
from .numbers import close

_YES = re.compile(r"^\s*(yes|yeah|correct|true)\b", re.I)
_NO = re.compile(r"^\s*(no|not|false)\b|\b(did not|does not|didn't|doesn't|has not|no longer|not)\b", re.I)


@dataclass
class Score:
    verdict: str  # "correct" | "incorrect" | "needs_review"
    method: str   # "numeric" | "yes_no" | "judge" | "none"
    page_hit: bool | None = None

    @property
    def correct(self) -> bool:
        return self.verdict == "correct"


def _scaled(x: float) -> list[float]:
    return [x * f for f in (1, 100, 0.01, 1000, 0.001, 1e6, 1e-6)]


def numeric_match(gold: str, pred_text: str, pred_value: float | None = None, rel: float = 0.01) -> bool | None:
    g = answer_numbers(gold)
    if not g:
        return None
    preds = answer_numbers(pred_text) + ([pred_value] if pred_value is not None else [])
    preds += [abs(p) for p in preds]
    return any(close(p, s, rel=rel, abs_tol=0.005) for p in preds for gv in g for s in _scaled(gv))


def yes_no(gold: str, pred: str) -> bool | None:
    g_yes, g_no = bool(_YES.match(gold)), bool(re.match(r"^\s*no\b", gold, re.I))
    if not (g_yes or g_no):
        return None
    p_yes = bool(_YES.match(pred))
    p_no = bool(_NO.search(pred)) and not p_yes
    return (g_yes and p_yes) or (g_no and p_no)


JUDGE_PROMPT = """You are grading an answer to a question about a company's SEC filing.
Question: {q}
Gold answer: {gold}
Candidate answer: {pred}
Is the candidate answer factually consistent with the gold answer (same key facts and numbers; extra detail is fine)?
Reply with JSON: {{"correct": true or false, "reason": "<10 words>"}}"""


def judge(q: str, gold: str, pred: str, client: LLMClient) -> bool:
    raw = client.complete("You are a strict, fair grader.", [{"role": "user", "content": JUDGE_PROMPT.format(q=q, gold=gold, pred=pred)}])
    try:
        return bool(extract_json(raw).get("correct"))
    except (json.JSONDecodeError, ValueError):
        return False


def score(question: str, gold: str, pred: str, pred_value: float | None, gold_pages: list[int], pred_pages: list[int],
          question_type: str | None = None, judge_client: LLMClient | None = None) -> Score:
    page_hit = bool(set(gold_pages) & set(pred_pages)) if gold_pages else None
    if not pred or pred.lower().startswith("i could not find"):
        return Score("incorrect", "none", page_hit)

    yn = yes_no(gold, pred)
    if yn is not None:
        # gold yes/no answers often add supporting detail ("No. ... in 2024 it acquired X for $120M");
        # the polarity is the answer
        return Score("correct" if yn else "incorrect", "yes_no", page_hit)

    is_numeric_q = question_type == "metrics-generated" or (answer_numbers(gold) and len(gold) < 60)
    num = numeric_match(gold, pred, pred_value)
    if num is not None and is_numeric_q:
        return Score("correct" if num else "incorrect", "numeric", page_hit)
    if judge_client is not None:
        return Score("correct" if judge(question, gold, pred, judge_client) else "incorrect", "judge", page_hit)
    if num:  # text answer whose key number matches: count it, but flag the method
        return Score("correct", "numeric", page_hit)
    return Score("needs_review", "none", page_hit)
