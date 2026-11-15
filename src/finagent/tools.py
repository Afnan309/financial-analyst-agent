"""The agent's tools. Each call returns text for the model plus the pages and
numbers it exposed, which feed citations and the grounding guard."""
from __future__ import annotations

from typing import Any

from .calculator import CalcError, calculate
from .finance import CONCEPTS, find_items
from .index import FilingIndex
from .ingest import Filing
from .numbers import numbers_in
from .schemas import LineItem, ToolCall
from .tables import extract_line_items

TOOL_SPECS = {
    "find_line_item": {
        "description": "Look up a line item in the financial statements (income statement, balance sheet, cash flow). "
                       "Returns values for every fiscal year with the page. Use for any reported number.",
        "args": {"name": "line item or concept, e.g. 'revenue', 'capex', 'total current assets'",
                 "period": "optional fiscal year, e.g. '2025'"},
    },
    "search_filing": {
        "description": "Full-text search of the filing (MD&A, risk factors, notes). Returns the best passages with pages. "
                       "Use for qualitative questions and numbers that are not in the main statements.",
        "args": {"query": "what to look for", "k": "optional number of passages (default 4)"},
    },
    "calculate": {
        "description": "Evaluate an arithmetic expression exactly. ALWAYS use this for any math (ratios, growth, averages).",
        "args": {"expression": "e.g. '(4210.0 - 3785.6) / 3785.6 * 100'"},
    },
    "read_page": {
        "description": "Read the full text of one page (1-indexed, as shown in citations like p.7).",
        "args": {"page": "page number"},
    },
}


def _fmt_item(it: LineItem) -> str:
    vals = "; ".join(f"FY{k}={v:,.2f}" for k, v in sorted(it.values.items(), reverse=True))
    unit = "" if it.unit == "units" else f", USD {it.unit}"
    return f"[p.{it.page + 1} {it.statement or 'table'}{unit}] {it.label}: {vals}"


class Toolbox:
    def __init__(self, filing: Filing, index: FilingIndex | None = None, items: list[LineItem] | None = None):
        self.filing = filing
        self.index = index or FilingIndex(filing)
        self.items = items if items is not None else extract_line_items(filing)

    # ---------------------------------------------------------------- overview
    def overview(self) -> str:
        years = sorted({y for it in self.items for y in it.values}, reverse=True)
        units = sorted({it.unit for it in self.items if it.statement})
        stmts = {}
        for it in self.items:
            if it.statement:
                stmts.setdefault(it.statement, it.page + 1)
        where = ", ".join(f"{k.replace('_', ' ')} p.{v}" for k, v in stmts.items()) or "not detected"
        return (f"Document: {self.filing.name}, {len(self.filing.pages)} pages. Fiscal years in tables: "
                f"{', '.join(years) or 'unknown'}. Statement units: {', '.join(units) or 'unknown'}. Statements: {where}.")

    # ------------------------------------------------------------------- tools
    def run(self, tool: str, args: dict[str, Any]) -> ToolCall:
        try:
            if tool == "find_line_item":
                return self.find_line_item(str(args.get("name", "")), args.get("period"))
            if tool == "search_filing":
                return self.search_filing(str(args.get("query", "")), int(args.get("k", 4) or 4))
            if tool == "calculate":
                return self.calculate(str(args.get("expression", "")))
            if tool == "read_page":
                return self.read_page(int(args.get("page", 1)))
            return ToolCall(tool=tool, args=args, output=f"Unknown tool '{tool}'. Use one of {list(TOOL_SPECS)}.")
        except (TypeError, ValueError) as e:
            return ToolCall(tool=tool, args=args, output=f"Error: {e}")

    def find_line_item(self, name: str, period: str | None = None) -> ToolCall:
        period = str(period).replace("FY", "").strip() if period else None
        hits = find_items(self.items, name, period)
        if not hits and period:
            hits = find_items(self.items, name)
        if not hits:
            known = ", ".join(sorted(CONCEPTS))
            return ToolCall(tool="find_line_item", args={"name": name, "period": period},
                            output=f"No line item matched '{name}'. Try search_filing, or one of: {known}")
        nums = [v for it in hits for v in it.values.values()]
        return ToolCall(tool="find_line_item", args={"name": name, "period": period},
                        output="\n".join(_fmt_item(it) for it in hits), pages=sorted({it.page for it in hits}), numbers=nums)

    def search_filing(self, query: str, k: int = 4) -> ToolCall:
        hits = self.index.search(query, k=min(max(k, 1), 8))
        if not hits:
            return ToolCall(tool="search_filing", args={"query": query}, output="No matching passages.")
        parts = [f"[p.{c.page + 1} | {c.section or 'n/a'}]\n{c.text}" for c, _ in hits]
        text = "\n\n".join(parts)
        return ToolCall(tool="search_filing", args={"query": query}, output=text,
                        pages=sorted({c.page for c, _ in hits}), numbers=numbers_in(text))

    def calculate(self, expression: str) -> ToolCall:
        try:
            v = calculate(expression)
        except CalcError as e:
            return ToolCall(tool="calculate", args={"expression": expression}, output=f"Error: {e}")
        return ToolCall(tool="calculate", args={"expression": expression}, output=f"{expression} = {v:.6g}", numbers=[v])

    def read_page(self, page: int) -> ToolCall:
        idx = page - 1
        if not 0 <= idx < len(self.filing.pages):
            return ToolCall(tool="read_page", args={"page": page}, output=f"Page {page} does not exist (1-{len(self.filing.pages)}).")
        p = self.filing.pages[idx]
        text = p.text[:4000]
        return ToolCall(tool="read_page", args={"page": page}, output=f"[p.{page} | {p.section or 'n/a'}]\n{text}",
                        pages=[idx], numbers=numbers_in(text))
