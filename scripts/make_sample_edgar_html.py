"""Generate a HELD-OUT fictional 10-K in SEC EDGAR HTML style, plus questions.

Deliberately different from the Northwind PDF the planner was developed on:
  - HTML with <table> cells and page-break styles (the EDGAR format), not PDF
  - amounts in THOUSANDS, not millions
  - different labels: "Total revenues", "Cost of revenues", "Income from operations",
    "Net earnings", "Capital expenditures", "Total shareholders' equity"
  - "$" in its own table cell, negative numbers in parentheses split across cells

    python scripts/make_sample_edgar_html.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples" / "CASCADE_2024_10K.htm"
OUT_Q = ROOT / "samples" / "cascade_questions.jsonl"
DOC = "CASCADE_2024_10K"
CO = "Cascade Foods Corporation"

R = {"Total revenues": [2_481_230, 2_302_118], "Cost of revenues": [1_712_049, 1_611_483]}
OPEX = {"Selling and marketing": [298_310, 276_254], "General and administrative": [171_402, 160_118]}
gp = [R["Total revenues"][i] - R["Cost of revenues"][i] for i in range(2)]
opi = [gp[i] - sum(v[i] for v in OPEX.values()) for i in range(2)]
INTEREST = [-21_870, -24_605]
pretax = [opi[i] + INTEREST[i] for i in range(2)]
TAX = [70_219, 59_877]
net = [pretax[i] - TAX[i] for i in range(2)]

CA = {"Cash and cash equivalents": [184_502, 151_233], "Trade receivables, net": [233_118, 219_870],
      "Inventories": [301_455, 288_920], "Other current assets": [41_200, 38_515]}
NCA = {"Property and equipment, net": [866_410, 823_005], "Goodwill and intangibles": [402_300, 410_850]}
CL = {"Accounts payable": [196_740, 188_310], "Accrued expenses": [122_884, 115_402],
      "Short-term borrowings": [40_000, 55_000]}
NCL = {"Long-term debt, net of current portion": [480_000, 520_000], "Deferred income taxes": [88_120, 81_400]}
tca = [sum(v[i] for v in CA.values()) for i in range(2)]
ta = [tca[i] + sum(v[i] for v in NCA.values()) for i in range(2)]
tcl = [sum(v[i] for v in CL.values()) for i in range(2)]
tl = [tcl[i] + sum(v[i] for v in NCL.values()) for i in range(2)]
eq = [ta[i] - tl[i] for i in range(2)]

DEP = [92_305, 88_140]
WC = [-18_420, -9_870]
cfo = [net[i] + DEP[i] + WC[i] for i in range(2)]
CAPEX = [-131_880, -142_515]
DIV = [-48_600, -45_900]


def money(v: int) -> str:
    return f"({abs(v):,})" if v < 0 else f"{v:,}"


def row(label: str, vals: list[int], dollar: bool = False) -> str:
    cells = "".join(
        f'<td>{"$" if dollar else ""}</td><td style="text-align:right">{money(v).rstrip(")")}</td>'
        f'<td>{")" if v < 0 else ""}</td>' for v in vals)
    return f"<tr><td>{label}</td>{cells}</tr>"


def table(title: str, rows: list[str]) -> str:
    return (f'<p style="text-align:center"><b>{title}</b></p><p style="text-align:center">(In thousands)</p>'
            '<table><tr><td></td><td colspan="3">Fiscal 2024</td><td colspan="3">Fiscal 2023</td></tr>'
            + "".join(rows) + "</table>")


BREAK = '<hr style="page-break-after:always"/>'


def build() -> dict[str, int]:
    pages = []
    pages.append(f"<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p><p>FORM 10-K</p><p>{CO}</p>"
                 "<p>For the fiscal year ended September 28, 2024. Fictional company for software testing.</p>")
    pages.append("<p>Item 1. Business</p><p>Cascade Foods Corporation produces frozen meals and plant-based snacks "
                 "sold through grocery chains and club stores. Our two largest retail customers together represented "
                 "31% of total revenues in fiscal 2024.</p>"
                 "<p>Item 1A. Risk Factors</p><p>Commodity costs for wheat, soy and packaging can rise quickly. "
                 "A 10% increase in commodity costs would have reduced fiscal 2024 gross profit by about $54 million.</p>")
    pages.append("<p>Item 7. Management's Discussion and Analysis</p>"
                 f"<p>Total revenues rose to ${R['Total revenues'][0] / 1000:,.1f} million in fiscal 2024. We opened a new "
                 "plant in Boise, Idaho in fiscal 2024 and plan capital expenditures of $150 million to $160 million "
                 "in fiscal 2025. Our revolving credit facility of $300 million was undrawn at year end.</p>")
    pages.append("<p>Item 8. Financial Statements</p>" + table("CONSOLIDATED STATEMENTS OF INCOME", [
        row("Total revenues", R["Total revenues"], True), row("Cost of revenues", R["Cost of revenues"]),
        row("Gross profit", gp), *[row(k, v) for k, v in OPEX.items()], row("Income from operations", opi),
        row("Interest expense, net", INTEREST), row("Income before income taxes", pretax),
        row("Income tax expense", TAX), row("Net earnings", net, True)]))
    pages.append(table("CONSOLIDATED BALANCE SHEETS", [
        *[row(k, v, k.startswith("Cash")) for k, v in CA.items()], row("Total current assets", tca),
        *[row(k, v) for k, v in NCA.items()], row("Total assets", ta, True),
        *[row(k, v) for k, v in CL.items()], row("Total current liabilities", tcl),
        *[row(k, v) for k, v in NCL.items()], row("Total liabilities", tl),
        row("Total shareholders' equity", eq), row("Total liabilities and shareholders' equity", ta, True)]))
    pages.append(table("CONSOLIDATED STATEMENTS OF CASH FLOWS", [
        row("Net earnings", net, True), row("Depreciation", DEP), row("Changes in working capital", WC),
        row("Net cash provided by operating activities", cfo), row("Capital expenditures", CAPEX),
        row("Dividends paid", DIV)]))
    html = "<html><head><title>Cascade 10-K</title><style>td{padding:2px}</style></head><body>" + BREAK.join(
        f"<div>{p}</div>" for p in pages) + "</body></html>"
    OUT.write_text(html)
    return {"business": 1, "mdna": 2, "is": 3, "bs": 4, "cf": 5}


def questions(pg: dict[str, int]) -> list[dict]:
    rows = [
        ("metrics-generated", "What were Cascade Foods' FY2024 total revenues in USD millions?",
         f"${R['Total revenues'][0] / 1000:,.2f} million", [pg["is"]]),
        ("metrics-generated", "What is Cascade Foods' FY2024 net income in USD thousands?", f"${net[0]:,}", [pg["is"]]),
        ("metrics-generated", "What is Cascade Foods' FY2024 gross margin? Round to one decimal place.",
         f"{gp[0] / R['Total revenues'][0] * 100:.1f}%", [pg["is"]]),
        ("metrics-generated", "What is Cascade Foods' FY2024 operating margin? Round to one decimal place.",
         f"{opi[0] / R['Total revenues'][0] * 100:.1f}%", [pg["is"]]),
        ("metrics-generated", "What is the FY2024 capital expenditure amount for Cascade Foods in USD millions?",
         f"${-CAPEX[0] / 1000:,.2f} million", [pg["cf"]]),
        ("metrics-generated", "What is Cascade Foods' FY2024 quick ratio? Quick ratio is (total current assets minus inventories) divided by total current liabilities. Round to two decimal places.",
         f"{(tca[0] - CA['Inventories'][0]) / tcl[0]:.2f}", [pg["bs"]]),
        ("metrics-generated", "What is Cascade Foods' FY2024 free cash flow in USD thousands?", f"${cfo[0] + CAPEX[0]:,}", [pg["cf"]]),
        ("metrics-generated", "What was Cascade Foods' revenue growth from FY2023 to FY2024 in percent? Round to two decimal places.",
         f"{(R['Total revenues'][0] / R['Total revenues'][1] - 1) * 100:.2f}%", [pg["is"]]),
        ("metrics-generated", "What is Cascade Foods' FY2024 effective tax rate? Round to one decimal place.",
         f"{TAX[0] / pretax[0] * 100:.1f}%", [pg["is"]]),
        ("metrics-generated", "What is Cascade Foods' FY2024 interest coverage ratio (operating income divided by interest expense)? Round to two decimal places.",
         f"{opi[0] / -INTEREST[0]:.2f}", [pg["is"]]),
        ("novel-generated", "What share of Cascade Foods' FY2024 revenue came from its two largest customers?",
         "31% of total revenues.", [pg["business"]]),
        ("novel-generated", "How much does Cascade Foods plan to spend on capital expenditures in fiscal 2025?",
         "$150 million to $160 million.", [pg["mdna"]]),
        ("domain-relevant", "Was Cascade Foods' revolving credit facility drawn at the end of fiscal 2024?",
         "No, the $300 million revolving credit facility was undrawn.", [pg["mdna"]]),
    ]
    return [{"financebench_id": f"cascade_{i:03d}", "company": CO, "doc_name": DOC, "question_type": t, "question": q,
             "answer": a, "evidence": [{"doc_name": DOC, "evidence_page_num": p} for p in ps], "doc_type": "10k",
             "doc_period": 2024, "dataset_subset_label": "SAMPLE_HELDOUT"}
            for i, (t, q, a, ps) in enumerate(rows, 1)]


if __name__ == "__main__":
    pg = build()
    qs = questions(pg)
    OUT_Q.write_text("\n".join(json.dumps(q) for q in qs) + "\n")
    print(f"wrote {OUT.name} and {len(qs)} questions")
