"""Deterministic analyst: answers common 10-K questions without an LLM.

It recognises the question shape (a reported line item, a named ratio, a
growth rate, a "which segment grew fastest" comparison, or a text lookup),
then calls the same tools the LLM agent uses, so its trace looks the same.
It is the offline mode, the CI baseline, and the LLM agent's fallback.
"""
from __future__ import annotations

import re

from .finance import ALIASES, Metric, detect_metric, find_items
from .numbers import YEAR, convert, fmt_money
from .schemas import AgentAnswer, Citation, ToolCall
from .tools import Toolbox

_WORD_NUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4}
_UNIT_ASK = [(r"usd\s*billions|in billions|\$\s*billions", "billions"),
             (r"usd\s*millions|in millions|\$\s*millions", "millions"),
             (r"usd\s*thousands|in thousands|\$\s*thousands", "thousands")]
_STOP = set("the a an of to and or in on for is are be by with what which who when how does do did this that it any its "
            "company company's fiscal year fy".split())


def _years(q: str) -> list[str]:
    seen = []
    for y in YEAR.findall(q):
        if y not in seen:
            seen.append(y)
    return seen


def _decimals(q: str) -> int | None:
    m = re.search(r"(\w+) decimal place", q, re.I)
    if not m:
        return None
    w = m.group(1).lower()
    return int(w) if w.isdigit() else _WORD_NUM.get(w)


def _unit_asked(q: str) -> str | None:
    for rx, u in _UNIT_ASK:
        if re.search(rx, q, re.I):
            return u
    return None


def _concepts_in(q: str) -> list[str]:
    ql = q.lower()
    found = []
    for alias in sorted(ALIASES, key=len, reverse=True):
        if re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", ql):
            c = ALIASES[alias]
            if c not in found:
                found.append(c)
            ql = ql.replace(alias, " ")
    return found


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _tok(s: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _STOP and len(w) > 2}


_METRIC_LABELS = {
    "roa": "return on assets (ROA)", "roe": "return on equity (ROE)", "capex_pct_revenue": "capital expenditure as % of revenue",
    "dividend_payout": "dividend payout ratio", "debt_to_equity": "debt-to-equity ratio",
    "free_cash_flow": "free cash flow", "fixed_asset_turnover": "fixed asset turnover ratio",
    "inventory_turnover": "inventory turnover ratio", "asset_turnover": "asset turnover ratio",
}

_YES_NO_Q = re.compile(r"^\s*(is|was|were|are|did|does|do|has|have|had|can|will)\b", re.I)
_NEGATION = re.compile(r"\b(not|no|never|none|neither|nor|without|did not|didn't|does not|doesn't|has not|hasn't)\b", re.I)


def _yes_no(q: str, sent: str) -> str | None:
    """'Was the facility drawn?' + 'The facility was undrawn.' -> 'No'. Only for yes/no questions."""
    if not _YES_NO_Q.match(q):
        return None
    s = sent.lower()
    negated = bool(_NEGATION.search(s))
    for w in re.findall(r"[a-z]{4,}", q.lower()):
        if re.search(rf"\b(un|non-?|in){w}\b", s):  # drawn -> undrawn, recurring -> nonrecurring
            negated = True
    return "No" if negated else "Yes"


class Planner:
    name = "offline"

    def __init__(self, tools: Toolbox):
        self.t = tools

    # ------------------------------------------------------------------ entry
    def answer(self, question: str) -> AgentAnswer:
        steps: list[ToolCall] = []
        years = _years(question)
        for handler in (self._metric, self._growth, self._which_grew, self._line_item):
            res = handler(question, years, steps)
            if res is not None:
                return res
        return self._text(question, steps)

    # ---------------------------------------------------------------- helpers
    def _get(self, concept: str, year: str | None, steps: list[ToolCall]):
        steps.append(self.t.find_line_item(concept, year))
        best = find_items(self.t.items, concept, year, k=1)
        if not best:
            return None
        it = best[0]
        got = it.value_for(year)
        if got is None:
            return None
        return it, got[0], got[1]

    def _calc(self, expr: str, steps: list[ToolCall]) -> float | None:
        call = self.t.calculate(expr)
        steps.append(call)
        return call.numbers[0] if call.numbers else None

    def _done(self, q, text, value, unit, cite_pages, steps, warnings=None) -> AgentAnswer:
        cites = [Citation(page=p, excerpt=self.t.filing.pages[p].text[:240]) for p in sorted(set(cite_pages))]
        return AgentAnswer(question=q, answer=text, value=value, unit=unit, citations=cites, steps=steps,
                           grounded=True, warnings=warnings or [], provider=self.name)

    # --------------------------------------------------------------- handlers
    def _metric(self, q: str, years: list[str], steps: list[ToolCall]) -> AgentAnswer | None:
        m: Metric | None = detect_metric(q)
        if m is None:
            return None
        year = max(years) if years else None
        letters = "abcdefgh"
        values, pages = [], []
        for i, inp in enumerate(m.inputs):
            avg = inp.startswith("avg:")
            concept = inp[4:] if avg else inp
            got = self._get(concept, year, steps)
            if got is None:
                return None
            it, y, v = got
            pages.append(it.page)
            if avg:
                prev = str(int(y) - 1)
                pv = it.value_for(prev)
                if pv is None:
                    return None
                v = self._calc(f"({v} + {pv[1]}) / 2", steps)
            if i in m.sign_abs:
                v = abs(v)
            values.append(v)
            year = year or y
        expr = m.formula
        for letter, v in zip(letters, values):
            expr = re.sub(rf"\b{letter}\b", f"({v})", expr)
        if m.percent:
            expr = f"({expr}) * 100"
        result = self._calc(expr, steps)
        if result is None:
            return None
        d = _decimals(q)
        d = d if d is not None else 2
        result = round(result, d)
        label = _METRIC_LABELS.get(m.key, m.key.replace("_", " "))
        if m.key == "free_cash_flow":
            unit = self.t.items[0].unit if self.t.items else "units"
            return self._done(q, f"FY{year} {label}: {fmt_money(result, unit)}", result, f"USD {unit}", pages, steps)
        text = f"FY{year} {label}: {result:.{d}f}{'%' if m.percent else ''}"
        return self._done(q, text, result, "%" if m.percent else "ratio", pages, steps)

    def _growth(self, q: str, years: list[str], steps: list[ToolCall]) -> AgentAnswer | None:
        if len(years) < 2 or not re.search(r"grow|growth|change|increase|decrease|decline", q, re.I):
            return None
        concepts = _concepts_in(q)
        if not concepts:
            return None
        y_new, y_old = max(years), min(years)
        got_new, got_old = self._get(concepts[0], y_new, steps), self._get(concepts[0], y_old, steps)
        if not got_new or not got_old:
            return None
        (it, _, new), (_, _, old) = got_new, got_old
        d = _decimals(q)
        if re.search(r"rate|percent|%|growth", q, re.I):
            pct = self._calc(f"({new} - {old}) / abs({old}) * 100", steps)
            d = 2 if d is None else d
            pct = round(pct, d)
            return self._done(q, f"{it.label} changed {pct:+.{d}f}% from FY{y_old} ({old:,.1f}) to FY{y_new} ({new:,.1f}).",
                              pct, "%", [it.page], steps)
        diff = self._calc(f"{new} - {old}", steps)
        return self._done(q, f"{it.label} changed by {fmt_money(diff, it.unit)} from FY{y_old} to FY{y_new}.",
                          diff, f"USD {it.unit}", [it.page], steps)

    def _which_grew(self, q: str, years: list[str], steps: list[ToolCall]) -> AgentAnswer | None:
        """'Which segment grew the fastest?' -> compute growth for every row in the relevant table."""
        if not re.search(r"\bwhich\b", q, re.I) or not re.search(r"gr[eo]w|growth|fastest|increase", q, re.I):
            return None
        topic = _tok(re.sub(r"(?i)\b(which|grew|grow|growth|fastest|most|largest|highest)\b", " ", q))
        company = _tok(self.t.filing.pages[0].text[:400]) if self.t.filing.pages else set()
        topic -= company
        # pages that hold a comparable table, ranked by how often they mention the topic ("segment")
        table_pages = sorted({it.page for it in self.t.items if len(it.values) >= 2})
        ranked = sorted(table_pages, key=lambda p: -sum(self.t.filing.pages[p].text.lower().count(w) for w in topic))
        call = self.t.read_page(ranked[0] + 1) if ranked else self.t.search_filing(q, k=3)
        steps.append(call)
        year = max(years) if years else None
        best = None
        for page in call.pages:
            rows = [it for it in self.t.items if it.page == page and not it.label.lower().startswith("total")]
            for it in rows:
                cur = it.value_for(year)
                if cur is None:
                    continue
                prev = it.value_for(str(int(cur[0]) - 1))
                if prev is None or prev[1] == 0:
                    continue
                g = self._calc(f"({cur[1]} - {prev[1]}) / abs({prev[1]}) * 100", steps)
                if best is None or g > best[0]:
                    best = (g, it, cur[0])
            if best:
                break
        if best is None:
            return None
        g, it, y = best
        return self._done(q, f"{it.label}, up {g:.1f}% year over year in FY{y}.", round(g, 1), "%", [it.page], steps)

    def _line_item(self, q: str, years: list[str], steps: list[ToolCall]) -> AgentAnswer | None:
        concepts = _concepts_in(q)
        if not concepts or not re.search(r"\b(what|how much)\b.*\b(is|was|were|are)\b|amount", q, re.I):
            return None
        year = max(years) if years else None
        got = self._get(concepts[0], year, steps)
        if got is None:
            return None
        it, y, v = got
        if concepts[0] in ("capex", "dividends", "buybacks") and v < 0:
            v = abs(v)
        want = _unit_asked(q) or it.unit
        if want != it.unit and it.unit != "units":
            v = round(convert(v, it.unit, want), 4)
        return self._done(q, f"FY{y} {it.label.lower()}: {fmt_money(v, want)}", v, f"USD {want}", [it.page], steps)

    def _text(self, q: str, steps: list[ToolCall]) -> AgentAnswer:
        call = self.t.search_filing(q, k=4)
        steps.append(call)
        qt = _tok(q)
        years = set(_years(q))
        wants_amount = bool(re.search(r"\bhow (much|many)\b|\bamount\b|\bwhat (percentage|share|rate)\b", q, re.I))
        best = (0.0, None, "")
        for rank, block in enumerate(call.output.split("\n\n[p.")):
            m = re.match(r"\[?p\.(\d+)", block if block.startswith("[") else "[p." + block)
            page = int(m.group(1)) - 1 if m else None
            header, _, body = block.partition("]\n")
            section = header.split("|", 1)[-1] if "|" in header else ""
            # words naming the section ("risk factors") match every sentence in it, so score on the rest
            q_eff = (qt - _tok(section)) or qt
            body = re.sub(r"^\s*item\s+\w+\.\s+[A-Z][\w ,'&]{0,60}?(?=\s+[A-Z][a-z]+\s)", "", body, flags=re.I)
            for sent in re.split(r"(?<=[.;])\s+(?=[A-Z$(])", body.replace("\n", " ")):
                if len(sent.split()) < 6:
                    continue  # headings and fragments are not answers
                st = _tok(sent)
                matched = len(q_eff & st)
                if matched < 2 and matched / (len(q_eff) or 1) < 0.5:
                    continue  # one shared word ("annual") is not evidence
                score = matched / (len(q_eff) or 1) - 0.04 * rank
                score += 0.25 * len(years & set(YEAR.findall(sent)))  # the year asked about is a strong signal
                if wants_amount and re.search(r"\d", sent):
                    score += 0.1
                if score > best[0]:
                    best = (score, page, sent.strip())
        score, page, sent = best
        if page is None or score < 0.3:
            return AgentAnswer(question=q, answer="I could not find this in the filing.", steps=steps, grounded=False,
                               warnings=["no supporting passage found"], provider=self.name)
        # "How much ... in 2028?" over a list like "$75.0 million in 2027, $300.0 million in 2028" -> pick that amount
        amt = r"\$[\d,]+(?:\.\d+)?(?:\s*(?:million|billion|thousand))?"
        for y in years:
            mm = re.search(rf"((?:{amt}\s*(?:to|-|and)\s*)?{amt})\s+(?:in|for|during)\s+(?:fiscal\s+)?{y}\b", sent)
            if mm:
                return self._done(q, f"{mm.group(1)} in {y}. Source: \"{sent}\"", None, None, [page], steps)
        polarity = _yes_no(q, sent)
        if polarity:
            return self._done(q, f"{polarity}. The filing says: \"{sent}\"", None, None, [page], steps)
        return self._done(q, sent, None, None, [page], steps)

