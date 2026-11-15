"""Turn financial statement pages into structured line items.

Works on page *text* rather than PDF table geometry, because 10-K PDFs and
EDGAR HTML both render statement rows as one line: a label followed by one
number per period column. The period columns come from the nearest header
line above that lists two or more fiscal years.

    Total net sales              4,210.0    3,785.2   3,402.9
    -> LineItem(label="Total net sales", values={"2025": 4210.0, "2024": 3785.2, "2023": 3402.9})
"""
from __future__ import annotations

import re
from collections import Counter

from .ingest import Filing
from .numbers import YEAR, detect_unit, parse_number
from .schemas import LineItem

STATEMENT_HINTS = [
    ("income_statement", re.compile(r"statements? of (consolidated )?(operations|income|earnings)|income statements?", re.I)),
    ("balance_sheet", re.compile(r"balance sheets?|statements? of financial (position|condition)", re.I)),
    ("cash_flow", re.compile(r"statements? of (consolidated )?cash flows?", re.I)),
]
_NUM_CELL = re.compile(r"^\(?-?\$?\d[\d,]*(?:\.\d+)?\)?%?$|^[—–-]$")
_NOT_LABEL = re.compile(r"^(page|table of contents|see accompanying|\(in )", re.I)


def _statement_kind(text: str) -> str | None:
    head = text[:600]
    for kind, rx in STATEMENT_HINTS:
        if rx.search(head):
            return kind
    return None


def _year_header(line: str) -> list[str] | None:
    years = YEAR.findall(line)
    # a header is mostly years: "2025 2024 2023" or "Years ended December 31, 2025 2024"
    if len(years) < 2 or len(set(years)) != len(years):
        return None
    rest = re.sub(r"\b\d{1,2}\s*,", "", YEAR.sub("", line))  # drop years and "31," day numbers
    if re.search(r"\d{3,}|\d[\d,]*\.\d", rest):  # other real numbers -> it's a data row
        return None
    return years


def _split_row(line: str) -> tuple[str, list[float]] | None:
    toks = line.replace("$ ", "$").split()
    nums: list[float] = []
    while toks and _NUM_CELL.match(toks[-1]):
        tok = toks.pop()
        v = parse_number(tok)
        if v is None:
            break
        nums.append(v)
    nums.reverse()
    label = " ".join(toks).strip(" .:$")
    label = re.sub(r"\.{2,}", "", label).strip()
    if not nums or not re.search(r"[A-Za-z]{2,}", label) or _NOT_LABEL.match(label):
        return None
    return label, nums


def extract_line_items(filing: Filing) -> list[LineItem]:
    items: list[LineItem] = []
    unit_votes: Counter[str] = Counter()
    pages_units: dict[int, str] = {}
    for p in filing.pages:
        u = detect_unit(p.text)
        pages_units[p.index] = u
        if u != "units" and _statement_kind(p.text):
            unit_votes[u] += 1
    doc_unit = unit_votes.most_common(1)[0][0] if unit_votes else "units"

    for p in filing.pages:
        kind = _statement_kind(p.text)
        unit = pages_units[p.index] if pages_units[p.index] != "units" else (doc_unit if kind else "units")
        years: list[str] | None = None
        pending_label = ""
        for raw in p.text.split("\n"):
            line = raw.strip()
            if not line:
                continue
            hdr = _year_header(line)
            if hdr:
                years = hdr
                pending_label = ""
                continue
            row = _split_row(line)
            if row is None:
                # remember a wrapped label: "Purchases of property, plant and"
                pending_label = line if len(line) < 90 and not line.endswith(".") else ""
                continue
            label, nums = row
            if years is None:
                continue
            if label[:1].islower() and pending_label:
                label = f"{pending_label} {label}"
            pending_label = ""
            if len(nums) == len(years) + 1 and raw.rstrip().endswith("%"):
                nums = nums[:-1]  # drop a trailing "% change" column
            if len(nums) != len(years):
                continue
            # a row whose "numbers" are the years themselves is a header, not data
            if len(nums) > 1 and all(n == int(n) and str(int(n)) in years for n in nums):
                continue
            items.append(LineItem(label=label, values=dict(zip(years, nums)), unit=unit, page=p.index, statement=kind))
    return _dedupe(items)


def _dedupe(items: list[LineItem]) -> list[LineItem]:
    seen, out = set(), []
    for it in items:
        key = (it.label.lower(), tuple(sorted(it.values.items())))
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out
