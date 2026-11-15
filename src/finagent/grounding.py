"""Numeric grounding guard.

A financial answer is only trustworthy if each number in it came from the
filing or from an exact calculation over numbers in the filing. This module
checks that, allowing for the transformations analysts legitimately apply:
rounding, sign flips (cash outflows are negative), percent vs. ratio, and
unit changes (millions <-> billions <-> thousands).
"""
from __future__ import annotations

import re

from .numbers import close, numbers_in
from .schemas import ToolCall

_PAGE_REF = re.compile(r"\bp(?:age|\.)\s?\d+", re.I)
_YEAR_REF = re.compile(r"\b(?:FY|fiscal( year)?\s?)?(19|20)\d{2}\b", re.I)


def answer_numbers(text: str) -> list[float]:
    """Numbers in an answer, ignoring page references and years."""
    t = _PAGE_REF.sub(" ", text)
    t = _YEAR_REF.sub(" ", t)
    return [n for n in numbers_in(t) if n != 0]


def _variants(x: float) -> list[float]:
    base = [x, -x]
    out = []
    for b in base:
        out += [b, b * 100, b / 100, b * 1000, b / 1000, b * 1e6, b / 1e6]
    return out


def is_grounded(n: float, ledger: list[float]) -> bool:
    for x in ledger:
        for v in _variants(x):
            if close(n, v, rel=0.006, abs_tol=0.006):
                return True
    return False


def check(answer: str, value: float | None, steps: list[ToolCall]) -> list[float]:
    """Return the numbers in the answer that cannot be traced to any tool output."""
    ledger = [n for s in steps for n in s.numbers]
    nums = answer_numbers(answer)
    if value is not None:
        nums.append(value)
    bad: list[float] = []
    for n in nums:
        if not is_grounded(n, ledger) and n not in bad:
            bad.append(n)
    return bad
