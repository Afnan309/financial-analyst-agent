"""Financial vocabulary: how line items are named across filings, and how common
metrics are computed from them.

Companies label the same thing differently ("Net sales", "Total revenues",
"Revenue"). ``CONCEPTS`` maps a canonical concept to the label patterns seen in
real 10-Ks, so both the offline planner and the LLM's ``find_line_item`` tool
land on the right row.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import LineItem

CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (r"^total (net )?(revenues?|sales)", r"^(net )?(revenues?|sales)$", r"^total net sales$", r"^net sales$",
                r"^revenues?,? net$", r"^net revenues?$"),
    "cost_of_revenue": (r"^(total )?cost of (goods sold|sales|revenues?|products sold)",),
    "gross_profit": (r"^gross (profit|margin)$",),
    "rnd": (r"^research and development",),
    "sga": (r"^selling, general and administrative",),
    "operating_income": (r"^operating (income|profit)", r"^income from operations", r"^operating income \(loss\)"),
    "interest_expense": (r"^interest expense",),
    "pretax_income": (r"^income before (provision for )?(income )?taxes", r"^earnings before income taxes"),
    "income_tax": (r"^(provision for|benefit from|\(benefit\) provision for) income taxes", r"^income tax (expense|provision)"),
    "net_income": (r"^net (income|earnings)$", r"^net income attributable to", r"^net (income|earnings) \(loss\)"),
    "eps_diluted": (r"diluted", r"^earnings per share.*diluted"),
    "eps_basic": (r"^earnings per share.*basic", r"basic"),
    "cash": (r"^cash and cash equivalents$", r"^cash and cash equivalents, end of (year|period)"),
    "receivables": (r"^accounts receivable", r"^(trade )?receivables"),
    "inventory": (r"^inventor(y|ies)",),
    "current_assets": (r"^total current assets",),
    "ppe": (r"^property, plant and equipment,? net", r"^property and equipment,? net", r"^net property, plant"),
    "total_assets": (r"^total assets$",),
    "accounts_payable": (r"^accounts payable",),
    "current_liabilities": (r"^total current liabilities",),
    "current_debt": (r"^current portion of long-term debt", r"^short-term (debt|borrowings)", r"^current maturities of long-term debt"),
    "long_term_debt": (r"^long-term debt",),
    "total_liabilities": (r"^total liabilities$",),
    "equity": (r"^total (stockholders'?|shareholders'?) equity", r"^total equity$"),
    "cfo": (r"^net cash (provided by|from|provided by \(used in\)) operating activities",),
    "capex": (r"^(purchases?|acquisitions?|additions?) (of|to) property,? (plant )?and equipment", r"^capital expenditures",
              r"^purchases of property, plant and equipment"),
    "dividends": (r"^(cash )?dividends paid", r"^payments? of dividends"),
    "buybacks": (r"^(repurchases?|purchases?) of (common|treasury) stock",),
    "dna": (r"^depreciation and amortization", r"^depreciation, amortization"),
}

# Plain-English names users and questions use -> concept
ALIASES = {
    "revenue": "revenue", "revenues": "revenue", "sales": "revenue", "net sales": "revenue", "total revenue": "revenue",
    "top line": "revenue", "cogs": "cost_of_revenue", "cost of goods sold": "cost_of_revenue", "cost of sales": "cost_of_revenue",
    "cost of revenue": "cost_of_revenue", "gross profit": "gross_profit", "r&d": "rnd", "research and development": "rnd",
    "sg&a": "sga", "operating income": "operating_income", "ebit": "operating_income", "operating profit": "operating_income",
    "pretax income": "pretax_income", "income before taxes": "pretax_income", "income tax": "income_tax",
    "tax expense": "income_tax", "net income": "net_income", "net earnings": "net_income", "profit": "net_income",
    "eps": "eps_diluted", "diluted eps": "eps_diluted", "cash": "cash", "cash and cash equivalents": "cash",
    "accounts receivable": "receivables", "receivables": "receivables", "inventory": "inventory", "inventories": "inventory",
    "current assets": "current_assets", "pp&e": "ppe", "ppe": "ppe", "property, plant and equipment": "ppe",
    "fixed assets": "ppe", "total assets": "total_assets", "accounts payable": "accounts_payable",
    "current liabilities": "current_liabilities", "long-term debt": "long_term_debt", "total liabilities": "total_liabilities",
    "equity": "equity", "shareholders' equity": "equity", "stockholders' equity": "equity",
    "operating cash flow": "cfo", "cash from operations": "cfo", "cash flow from operations": "cfo",
    "capex": "capex", "capital expenditure": "capex", "capital expenditures": "capex", "dividends": "dividends",
    "dividends paid": "dividends", "share repurchases": "buybacks", "buybacks": "buybacks",
    "depreciation and amortization": "dna", "d&a": "dna",
}

_STATEMENT_PREF = {"income_statement": 3, "balance_sheet": 3, "cash_flow": 3, None: 0}
_CONCEPT_STATEMENT = {
    **dict.fromkeys(["revenue", "cost_of_revenue", "gross_profit", "rnd", "sga", "operating_income", "interest_expense",
                     "pretax_income", "income_tax", "net_income", "eps_diluted", "eps_basic"], "income_statement"),
    **dict.fromkeys(["receivables", "inventory", "current_assets", "ppe", "total_assets", "accounts_payable",
                     "current_liabilities", "current_debt", "long_term_debt", "total_liabilities", "equity"], "balance_sheet"),
    **dict.fromkeys(["cfo", "capex", "dividends", "buybacks", "dna"], "cash_flow"),
}


def concept_for(name: str) -> str | None:
    n = name.lower().strip().rstrip("s") if name.lower().strip() not in ALIASES else name.lower().strip()
    if name.lower().strip() in ALIASES:
        return ALIASES[name.lower().strip()]
    if n in ALIASES:
        return ALIASES[n]
    if name in CONCEPTS:
        return name
    for concept, pats in CONCEPTS.items():
        if any(re.search(p, name.strip(), re.I) for p in pats):
            return concept
    return None


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z&]+", s.lower()) if len(w) > 2 and w not in {"the", "and", "net", "total"}}


def find_items(items: list[LineItem], name: str, period: str | None = None, k: int = 3) -> list[LineItem]:
    """Best-matching line items for a concept or free-text label."""
    concept = concept_for(name)
    scored: list[tuple[float, LineItem]] = []
    for it in items:
        if period and it.value_for(period) is None:
            continue
        score = 0.0
        if concept:
            for rank, p in enumerate(CONCEPTS.get(concept, ())):
                if re.search(p, it.label, re.I):
                    score = max(score, 10 - rank)
            if score and _CONCEPT_STATEMENT.get(concept) == it.statement:
                score += 5  # the line from the primary statement beats the MD&A copy
        q, lab = _tokens(name), _tokens(it.label)
        if q and lab:
            score += 4 * len(q & lab) / len(q | lab)
        score += 0.5 * (_STATEMENT_PREF.get(it.statement, 0) > 0)
        if score >= 2:
            scored.append((score, it))
    scored.sort(key=lambda t: (-t[0], t[1].page))
    return [it for _, it in scored[:k]]


# --------------------------------------------------------------------- metrics
@dataclass(frozen=True)
class Metric:
    key: str
    pattern: str            # regex on the question
    inputs: tuple[str, ...]  # concepts, prefixed "avg:" when the formula uses an average of two years
    formula: str            # python expression over a, b, c ...
    percent: bool = False
    sign_abs: tuple[int, ...] = ()  # indexes of inputs to take abs() of (capex, dividends are negative in cash flows)


METRICS: tuple[Metric, ...] = (
    Metric("gross_margin", r"gross (profit )?margin", ("gross_profit", "revenue"), "a / b", True),
    Metric("operating_margin", r"operating (profit )?margin|ebit margin", ("operating_income", "revenue"), "a / b", True),
    Metric("net_margin", r"net (profit |income )?margin|profit margin", ("net_income", "revenue"), "a / b", True),
    Metric("effective_tax_rate", r"effective tax rate", ("income_tax", "pretax_income"), "a / b", True),
    Metric("current_ratio", r"current ratio", ("current_assets", "current_liabilities"), "a / b"),
    Metric("quick_ratio", r"quick ratio", ("current_assets", "inventory", "current_liabilities"), "(a - b) / c"),
    Metric("free_cash_flow", r"free cash flow", ("cfo", "capex"), "a - b", sign_abs=(1,)),
    Metric("dividend_payout", r"(dividend )?payout ratio", ("dividends", "net_income"), "a / b", sign_abs=(0,)),
    Metric("capex_pct_revenue", r"capital expenditures? as a percentage of|capex as a (percentage|%) of|capex.{0,20}revenue",
           ("capex", "revenue"), "a / b", True, sign_abs=(0,)),
    Metric("roa", r"return on assets|\broa\b", ("net_income", "avg:total_assets"), "a / b", True),
    Metric("roe", r"return on (equity|shareholders)|\broe\b", ("net_income", "avg:equity"), "a / b", True),
    Metric("fixed_asset_turnover", r"fixed asset turnover", ("revenue", "avg:ppe"), "a / b"),
    Metric("asset_turnover", r"(?<!fixed )asset turnover", ("revenue", "avg:total_assets"), "a / b"),
    Metric("inventory_turnover", r"inventory turnover", ("cost_of_revenue", "avg:inventory"), "a / b"),
    Metric("debt_to_equity", r"debt[- ]to[- ]equity", ("current_debt", "long_term_debt", "equity"), "(a + b) / c"),
    Metric("interest_coverage", r"interest coverage", ("operating_income", "interest_expense"), "a / b", sign_abs=(1,)),
)


def detect_metric(question: str) -> Metric | None:
    q = question.lower()
    for m in METRICS:
        if re.search(m.pattern, q):
            return m
    return None
