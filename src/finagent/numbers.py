"""Parsing numbers the way they appear in financial filings.

    "1,234.5"  -> 1234.5        "(1,234)" -> -1234      "$ 98" -> 98
    "—" / "-"  -> 0             "12.5%"   -> 12.5       "4.2 billion" -> 4.2 (unit billions)
"""
from __future__ import annotations

import re

DASHES = {"—", "–", "-", "--", "—-"}

# A single numeric cell, optionally with $ / % / parentheses
NUM_TOKEN = re.compile(r"\(?\$?\s?-?\d[\d,]*(?:\.\d+)?\)?%?|(?<!\w)[—–](?!\w)")
YEAR = re.compile(r"\b(?:FY\s?)?((?:19|20)\d{2})\b")

UNIT_PATTERNS = [
    (re.compile(r"in\s+billions|\(\s*billions|\$\s*billions", re.I), "billions"),
    (re.compile(r"in\s+millions|\(\s*millions|\$\s*millions|\(millions\)", re.I), "millions"),
    (re.compile(r"in\s+thousands|\(\s*thousands|\$\s*thousands|\(thousands\)", re.I), "thousands"),
]
UNIT_SCALE = {"units": 1.0, "thousands": 1e3, "millions": 1e6, "billions": 1e9}


def parse_number(tok: str) -> float | None:
    t = tok.strip()
    if t in DASHES:
        return 0.0
    neg = t.startswith("(") and t.endswith(")") or t.startswith("(") and t.endswith(")%")
    t = t.strip("()$% ").replace(",", "").replace("$", "").strip()
    if t.startswith("-"):
        neg, t = True, t[1:]
    if not t or not re.fullmatch(r"\d+(?:\.\d+)?", t):
        return None
    v = float(t)
    return -v if neg else v


def numbers_in(text: str) -> list[float]:
    """Every number in free text (used by the grounding guard)."""
    out = []
    for m in re.finditer(r"-?\$?\(?\d[\d,]*(?:\.\d+)?\)?", text):
        v = parse_number(m.group(0))
        if v is not None:
            out.append(v)
    return out


def detect_unit(text: str) -> str:
    for rx, unit in UNIT_PATTERNS:
        if rx.search(text):
            return unit
    return "units"


def convert(value: float, from_unit: str, to_unit: str) -> float:
    return value * UNIT_SCALE[from_unit] / UNIT_SCALE[to_unit]


def fmt_money(value: float, unit: str) -> str:
    """4210.0, 'millions' -> '$4,210 million'"""
    unit_word = {"units": "", "thousands": " thousand", "millions": " million", "billions": " billion"}[unit]
    s = f"{abs(value):,.2f}".rstrip("0").rstrip(".")
    return f"{'-' if value < 0 else ''}${s}{unit_word}"


def close(a: float, b: float, rel: float = 0.01, abs_tol: float = 0.011) -> bool:
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))
