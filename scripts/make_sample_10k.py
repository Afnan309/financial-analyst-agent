"""Generate a fictional 10-K PDF plus FinanceBench-format questions with exact gold answers.

    python scripts/make_sample_10k.py

Writes:
    samples/NORTHWIND_2025_10K.pdf
    samples/northwind_questions.jsonl   (same schema as financebench_open_source.jsonl)

Every total is computed here, so the statements tie out and each gold answer
is derived from the same numbers that are printed on the page.
"""
from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
OUT_PDF = ROOT / "samples" / "NORTHWIND_2025_10K.pdf"
OUT_Q = ROOT / "samples" / "northwind_questions.jsonl"
DOC = "NORTHWIND_2025_10K"
CO = "Northwind Robotics, Inc."

Y3 = ["2025", "2024", "2023"]
Y2 = ["2025", "2024"]

# ------------------------------------------------------------------ numbers
IS = {
    "Net sales": [4210.0, 3785.6, 3402.1],
    "Cost of sales": [2526.0, 2309.2, 2109.3],
    "Research and development": [336.8, 302.8, 272.2],
    "Selling, general and administrative": [589.4, 548.9, 510.3],
    "Interest expense, net": [-48.2, -51.6, -55.0],
    "Other income (expense), net": [6.4, 3.1, -2.2],
    "Provision for income taxes": [150.4, 126.8, 102.0],
}
SHARES_BASIC = [180.9, 182.6, 183.7]
SHARES_DILUTED = [182.4, 184.1, 185.0]
gp = [s - c for s, c in zip(IS["Net sales"], IS["Cost of sales"])]
opinc = [g - r - s for g, r, s in zip(gp, IS["Research and development"], IS["Selling, general and administrative"])]
pretax = [o + i + x for o, i, x in zip(opinc, IS["Interest expense, net"], IS["Other income (expense), net"])]
ni = [p - t for p, t in zip(pretax, IS["Provision for income taxes"])]

BS_A = {
    "Cash and cash equivalents": [None, 644.0],  # 2025 filled in from the cash flow statement below
    "Accounts receivable, net": [701.3, 640.8],
    "Inventories": [588.9, 552.1],
    "Prepaid expenses and other current assets": [94.2, 88.6],
}
BS_A2 = {
    "Property, plant and equipment, net": [1206.7, 1118.4],
    "Goodwill": [640.0, 640.0],
    "Intangible assets, net": [212.6, 248.9],
    "Other assets": [133.5, 121.2],
}
BS_L = {
    "Accounts payable": [412.7, 389.5],
    "Accrued liabilities": [298.4, 271.0],
    "Current portion of long-term debt": [75.0, 75.0],
}
BS_L2 = {"Long-term debt": [925.0, 1000.0], "Other long-term liabilities": [186.2, 179.3]}
APIC = [1050.0, 1020.0]
AOCI = [-32.5, -41.0]


DA = [168.3, 155.0, 142.7]
SBC = [61.2, 55.4, 48.9]
WC = [-82.1, -64.7, -51.2]
cfo = [ni[i] + DA[i] + SBC[i] + WC[i] for i in range(3)]
CAPEX = [-256.6, -231.0, -205.4]
ACQ = [0.0, -120.0, 0.0]
OTH_INV = [4.1, 2.8, 1.5]
cfi = [CAPEX[i] + ACQ[i] + OTH_INV[i] for i in range(3)]
DEBT_REPAY = [-75.0, -75.0, -50.0]
DIVS = [-145.6, -128.0, -112.3]
BUYBACK = [-180.0, -150.0, -90.0]
OPTIONS = [21.3, 18.0, 15.2]
cff = [DEBT_REPAY[i] + DIVS[i] + BUYBACK[i] + OPTIONS[i] for i in range(3)]
fx = [-2.4, 1.8, -1.2]  # effect of exchange rates on cash
# Roll cash forward/back from the 2024 balance sheet so the cash flow statement ties out
_c2024 = 644.0
_c2025 = round(_c2024 + cfo[0] + cfi[0] + cff[0] + fx[0], 1)
_c2023 = round(_c2024 - (cfo[1] + cfi[1] + cff[1] + fx[1]), 1)
_c2022 = round(_c2023 - (cfo[2] + cfi[2] + cff[2] + fx[2]), 1)
CASH_END = [_c2025, _c2024, _c2023]
CASH_BEGIN = [_c2024, _c2023, _c2022]

BS_A["Cash and cash equivalents"][0] = CASH_END[0]
tca = [round(sum(v[i] for v in BS_A.values()), 1) for i in range(2)]
ta = [round(tca[i] + sum(v[i] for v in BS_A2.values()), 1) for i in range(2)]
tcl = [round(sum(v[i] for v in BS_L.values()), 1) for i in range(2)]
tl = [round(tcl[i] + sum(v[i] for v in BS_L2.values()), 1) for i in range(2)]
re_ = [round(ta[i] - tl[i] - APIC[i] - AOCI[i], 1) for i in range(2)]  # retained earnings plugs the balance
teq = [round(APIC[i] + re_[i] + AOCI[i], 1) for i in range(2)]

SEG = {"Industrial Robots": [2315.5, 2120.0], "Logistics Automation": [1263.0, 1060.0], "Services": [631.5, 605.6]}
assert abs(sum(v[0] for v in SEG.values()) - IS["Net sales"][0]) < 1e-6
assert abs(sum(v[1] for v in SEG.values()) - IS["Net sales"][1]) < 1e-6


def f(v: float) -> str:
    if abs(v) < 1e-9:
        return "—"
    s = f"{abs(v):,.1f}"
    return f"({s})" if v < 0 else s


# ------------------------------------------------------------------- render
class Doc:
    def __init__(self, path: Path):
        self.c = canvas.Canvas(str(path), pagesize=LETTER)
        self.c.setTitle(f"{CO} Form 10-K 2025 (fictional sample)")
        self.page = 0
        self.y = 720.0

    def new_page(self):
        if self.y < 720:
            self.footer()
            self.c.showPage()
            self.page += 1
        self.y = 720.0

    def footer(self):
        self.c.setFont("Helvetica", 8)
        self.c.drawCentredString(306, 30, f"{self.page + 1}")
        self.c.drawString(72, 42, "Fictional company. Sample document generated for software testing.")

    def title(self, text, size=13):
        self.c.setFont("Helvetica-Bold", size)
        self.c.drawString(72, self.y, text)
        self.y -= size + 10

    def para(self, text, size=10):
        self.c.setFont("Helvetica", size)
        for line in simpleSplit(text, "Helvetica", size, 468):
            self.c.drawString(72, self.y, line)
            self.y -= size + 4
        self.y -= 6

    def header_row(self, cols, xs=(400, 470, 540)):
        self.c.setFont("Helvetica-Bold", 9)
        for col, x in zip(cols, xs[-len(cols):]):
            self.c.drawRightString(x, self.y, col)
        self.y -= 15

    def row(self, label, vals, bold=False, xs=(400, 470, 540), fmt=f):
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        self.c.drawString(80 if not bold else 72, self.y, label)
        for v, x in zip(vals, xs[-len(vals):]):
            self.c.drawRightString(x, self.y, fmt(v) if not isinstance(v, str) else v)
        self.y -= 14

    def save(self):
        self.footer()
        self.c.save()


def build() -> dict[str, int]:
    d = Doc(OUT_PDF)
    pages: dict[str, int] = {}

    # p0 cover
    d.title("UNITED STATES SECURITIES AND EXCHANGE COMMISSION", 12)
    d.para("Washington, D.C. 20549")
    d.title("FORM 10-K", 16)
    d.para("ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934 "
           "For the fiscal year ended December 31, 2025")
    d.title(CO.upper(), 14)
    d.para("Commission file number 001-00000. A fictional Delaware corporation created for software demonstrations. "
           "None of the people, products or figures in this document are real.")

    # p1 TOC
    d.new_page()
    d.title("TABLE OF CONTENTS")
    for line in ["Item 1. Business", "Item 1A. Risk Factors", "Item 7. Management's Discussion and Analysis",
                 "Item 7A. Quantitative and Qualitative Disclosures About Market Risk",
                 "Item 8. Financial Statements and Supplementary Data", "Item 9A. Controls and Procedures"]:
        d.para(line)

    # p2 business
    d.new_page()
    pages["business"] = d.page
    d.title("Item 1. Business")
    d.para(f"{CO} designs and manufactures industrial robots, warehouse logistics automation systems and related "
           "software and services. We operate three reportable segments: Industrial Robots, Logistics Automation and "
           "Services. We sell primarily to automotive, electronics, e-commerce and third-party logistics customers.")
    d.para("As of December 31, 2025 we had approximately 9,800 employees, of whom about 1,900 work in research and "
           "development. We manufacture in four plants and assemble systems close to customers.")

    # p3 risk factors
    d.new_page()
    pages["risk"] = d.page
    d.title("Item 1A. Risk Factors")
    d.para("We depend on a small number of large customers. Our largest customer, a global e-commerce company, accounted "
           "for 18% of our net sales in fiscal 2025 and 15% in fiscal 2024. The loss of this customer, or a significant "
           "reduction in its orders, could materially reduce our revenue and profitability.")
    d.para("Our supply chain relies on single-source suppliers for certain precision gearboxes and vision sensors. "
           "Disruptions at these suppliers could delay shipments and increase costs.")
    d.para("Our indebtedness could limit our flexibility. Our senior notes bear interest at a fixed rate of 4.25% per year "
           "and contain covenants that restrict additional borrowing above certain leverage levels.")

    # p4 MD&A results
    d.new_page()
    pages["mdna"] = d.page
    d.title("Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations")
    growth = (IS["Net sales"][0] / IS["Net sales"][1] - 1) * 100
    d.para(f"Net sales increased {growth:.1f}% to ${IS['Net sales'][0]:,.1f} million in fiscal 2025, driven by strong "
           "demand for warehouse automation from e-commerce customers. Logistics Automation was our fastest-growing "
           "segment. Gross margin improved to "
           f"{gp[0] / IS['Net sales'][0] * 100:.1f}% from {gp[1] / IS['Net sales'][1] * 100:.1f}% on better pricing and "
           "lower component costs.")
    d.para("Net sales by segment (in millions)")
    d.header_row(Y2 + ["% change"])
    for k, v in SEG.items():
        d.row(k, [v[0], v[1], f"{(v[0] / v[1] - 1) * 100:.1f}%"])
    d.row("Total net sales", [IS["Net sales"][0], IS["Net sales"][1],
                              f"{growth:.1f}%"], bold=True)

    # p5 liquidity
    d.new_page()
    pages["liquidity"] = d.page
    d.title("Liquidity and Capital Resources")
    d.para(f"Cash and cash equivalents were ${BS_A['Cash and cash equivalents'][0]:,.1f} million at December 31, 2025. "
           f"Net cash provided by operating activities was ${cfo[0]:,.1f} million. Capital expenditures were "
           f"${-CAPEX[0]:,.1f} million, mainly for a new assembly line for logistics systems. We expect capital "
           "expenditures of approximately $280 million in fiscal 2026.")
    d.para(f"We returned ${-DIVS[0] - BUYBACK[0]:,.1f} million to shareholders in fiscal 2025 through dividends of "
           f"${-DIVS[0]:,.1f} million and share repurchases of ${-BUYBACK[0]:,.1f} million. We did not complete any "
           f"acquisitions in fiscal 2025. In fiscal 2024 we acquired Vector Grip Ltd. for ${-ACQ[1]:,.1f} million in cash.")
    d.para("Item 7A. Quantitative and Qualitative Disclosures About Market Risk. Our long-term debt bears fixed interest "
           "rates, so changes in market interest rates do not affect our interest expense.")

    # p6 income statement
    d.new_page()
    pages["is"] = d.page
    d.title("Item 8. Financial Statements and Supplementary Data")
    d.title("CONSOLIDATED STATEMENTS OF OPERATIONS", 11)
    d.para("(In millions, except per share amounts)", 9)
    d.header_row(["Years ended December 31,"], xs=(540,))
    d.header_row(Y3)
    d.row("Net sales", IS["Net sales"])
    d.row("Cost of sales", IS["Cost of sales"])
    d.row("Gross profit", gp, bold=True)
    d.row("Research and development", IS["Research and development"])
    d.row("Selling, general and administrative", IS["Selling, general and administrative"])
    d.row("Operating income", opinc, bold=True)
    d.row("Interest expense, net", IS["Interest expense, net"])
    d.row("Other income (expense), net", IS["Other income (expense), net"])
    d.row("Income before income taxes", pretax, bold=True)
    d.row("Provision for income taxes", IS["Provision for income taxes"])
    d.row("Net income", ni, bold=True)
    d.y -= 6
    d.row("Earnings per share - basic", [n / s for n, s in zip(ni, SHARES_BASIC)], fmt=lambda v: f"{v:.2f}")
    d.row("Earnings per share - diluted", [n / s for n, s in zip(ni, SHARES_DILUTED)], fmt=lambda v: f"{v:.2f}")
    d.row("Weighted-average shares - basic", SHARES_BASIC)
    d.row("Weighted-average shares - diluted", SHARES_DILUTED)

    # p7 balance sheet
    d.new_page()
    pages["bs"] = d.page
    d.title("CONSOLIDATED BALANCE SHEETS", 11)
    d.para("(In millions)", 9)
    d.header_row(["December 31,"], xs=(540,))
    d.header_row(Y2, xs=(470, 540))
    for k, v in BS_A.items():
        d.row(k, v, xs=(470, 540))
    d.row("Total current assets", tca, bold=True, xs=(470, 540))
    for k, v in BS_A2.items():
        d.row(k, v, xs=(470, 540))
    d.row("Total assets", ta, bold=True, xs=(470, 540))
    d.y -= 4
    for k, v in BS_L.items():
        d.row(k, v, xs=(470, 540))
    d.row("Total current liabilities", tcl, bold=True, xs=(470, 540))
    for k, v in BS_L2.items():
        d.row(k, v, xs=(470, 540))
    d.row("Total liabilities", tl, bold=True, xs=(470, 540))
    d.row("Common stock and additional paid-in capital", APIC, xs=(470, 540))
    d.row("Retained earnings", re_, xs=(470, 540))
    d.row("Accumulated other comprehensive loss", AOCI, xs=(470, 540))
    d.row("Total stockholders' equity", teq, bold=True, xs=(470, 540))
    d.row("Total liabilities and stockholders' equity", [tl[i] + teq[i] for i in range(2)], bold=True, xs=(470, 540))

    # p8 cash flow
    d.new_page()
    pages["cf"] = d.page
    d.title("CONSOLIDATED STATEMENTS OF CASH FLOWS", 11)
    d.para("(In millions)", 9)
    d.header_row(Y3)
    d.row("Net income", ni)
    d.row("Depreciation and amortization", DA)
    d.row("Stock-based compensation", SBC)
    d.row("Changes in operating assets and liabilities", WC)
    d.row("Net cash provided by operating activities", cfo, bold=True)
    d.row("Purchases of property, plant and equipment", CAPEX)
    d.row("Acquisitions, net of cash acquired", ACQ)
    d.row("Other investing activities", OTH_INV)
    d.row("Net cash used in investing activities", cfi, bold=True)
    d.row("Repayments of long-term debt", DEBT_REPAY)
    d.row("Dividends paid", DIVS)
    d.row("Repurchases of common stock", BUYBACK)
    d.row("Proceeds from exercise of stock options", OPTIONS)
    d.row("Net cash used in financing activities", cff, bold=True)
    d.row("Effect of exchange rate changes on cash", fx)
    d.row("Net increase in cash and cash equivalents", [CASH_END[i] - CASH_BEGIN[i] for i in range(3)], bold=True)
    d.row("Cash and cash equivalents, beginning of year", CASH_BEGIN)
    d.row("Cash and cash equivalents, end of year", CASH_END, bold=True)

    # p9 notes
    d.new_page()
    pages["notes"] = d.page
    d.title("NOTES TO CONSOLIDATED FINANCIAL STATEMENTS", 11)
    d.para("Note 7. Debt. Long-term debt consists of 4.25% senior notes with a total principal amount of "
           f"${BS_L['Current portion of long-term debt'][0] + BS_L2['Long-term debt'][0]:,.1f} million at December 31, 2025. "
           "Scheduled principal payments are $75.0 million in 2026, $75.0 million in 2027, $300.0 million in 2028, "
           "$250.0 million in 2029 and $300.0 million thereafter.")
    eff = [IS["Provision for income taxes"][i] / pretax[i] * 100 for i in range(3)]
    d.para(f"Note 9. Income Taxes. Our effective tax rate was {eff[0]:.1f}% in fiscal 2025, {eff[1]:.1f}% in fiscal 2024 "
           f"and {eff[2]:.1f}% in fiscal 2023. The decrease in 2025 reflects higher research and development tax credits.")
    d.para("Note 12. Segment Information. Segment operating income was $512.4 million for Industrial Robots, "
           "$214.7 million for Logistics Automation and $96.3 million for Services in fiscal 2025, before unallocated "
           "corporate costs of $65.6 million.")
    d.save()
    return pages


def questions(pages: dict[str, int]) -> list[dict]:
    r2 = lambda v: round(v, 2)  # noqa: E731
    rev, cogs = IS["Net sales"], IS["Cost of sales"]
    debt = [BS_L["Current portion of long-term debt"][i] + BS_L2["Long-term debt"][i] for i in range(2)]
    seg_growth = {k: (v[0] / v[1] - 1) * 100 for k, v in SEG.items()}
    top_seg = max(seg_growth, key=seg_growth.get)

    rows = [
        ("metrics-generated", "What is Northwind Robotics' FY2025 total net sales? Answer in USD millions.",
         f"${rev[0]:,.1f} million", [pages["is"]]),
        ("metrics-generated", "What is the FY2025 capital expenditure amount (in USD millions) for Northwind Robotics? Use the cash flow statement.",
         f"${-CAPEX[0]:,.1f} million", [pages["cf"]]),
        ("metrics-generated", "What is Northwind Robotics' FY2023 net income in USD millions?",
         f"${ni[2]:,.1f} million", [pages["is"]]),
        ("metrics-generated", "What is Northwind Robotics' FY2025 gross margin as a percentage? Round to one decimal place.",
         f"{gp[0] / rev[0] * 100:.1f}%", [pages["is"]]),
        ("metrics-generated", "What is Northwind Robotics' FY2025 operating margin as a percentage? Round to one decimal place.",
         f"{opinc[0] / rev[0] * 100:.1f}%", [pages["is"]]),
        ("metrics-generated", "What was the year-over-year growth rate of Northwind Robotics' net sales from FY2024 to FY2025? Round to two decimal places.",
         f"{(rev[0] / rev[1] - 1) * 100:.2f}%", [pages["is"]]),
        ("metrics-generated", "What is Northwind Robotics' FY2025 current ratio? Current ratio is total current assets divided by total current liabilities. Round to two decimal places.",
         f"{r2(tca[0] / tcl[0]):.2f}", [pages["bs"]]),
        ("metrics-generated", "What is Northwind Robotics' FY2025 effective tax rate? Round to one decimal place.",
         f"{IS['Provision for income taxes'][0] / pretax[0] * 100:.1f}%", [pages["is"]]),
        ("metrics-generated", "What is Northwind Robotics' FY2025 free cash flow (operating cash flow minus capital expenditures) in USD millions?",
         f"${cfo[0] + CAPEX[0]:,.1f} million", [pages["cf"]]),
        ("metrics-generated", "What is Northwind Robotics' FY2025 dividend payout ratio (dividends paid divided by net income)? Round to two decimal places.",
         f"{r2(-DIVS[0] / ni[0]):.2f}", [pages["cf"], pages["is"]]),
        ("metrics-generated", "What is Northwind Robotics' FY2025 capital expenditure as a percentage of net sales? Round to one decimal place.",
         f"{-CAPEX[0] / rev[0] * 100:.1f}%", [pages["cf"], pages["is"]]),
        ("metrics-generated", "What is Northwind Robotics' FY2025 return on assets? Return on assets is FY2025 net income divided by the average total assets between FY2024 and FY2025. Round to two decimal places, as a percentage.",
         f"{ni[0] / ((ta[0] + ta[1]) / 2) * 100:.2f}%", [pages["is"], pages["bs"]]),
        ("metrics-generated", "What is Northwind Robotics' FY2025 fixed asset turnover ratio? Fixed asset turnover is FY2025 net sales divided by the average PP&E (net) between FY2024 and FY2025. Round to two decimal places.",
         f"{r2(rev[0] / ((BS_A2['Property, plant and equipment, net'][0] + BS_A2['Property, plant and equipment, net'][1]) / 2)):.2f}",
         [pages["is"], pages["bs"]]),
        ("metrics-generated", "What is Northwind Robotics' FY2025 debt-to-equity ratio? Use total debt (current portion plus long-term debt) divided by total stockholders' equity. Round to two decimal places.",
         f"{r2(debt[0] / teq[0]):.2f}", [pages["bs"]]),
        ("metrics-generated", "What is Northwind Robotics' FY2025 inventory turnover ratio? Inventory turnover is FY2025 cost of sales divided by average inventories between FY2024 and FY2025. Round to two decimal places.",
         f"{r2(cogs[0] / ((BS_A['Inventories'][0] + BS_A['Inventories'][1]) / 2)):.2f}", [pages["is"], pages["bs"]]),
        ("domain-relevant", "Which of Northwind Robotics' segments grew the fastest in FY2025?",
         f"{top_seg}, up {seg_growth[top_seg]:.1f}% year over year.", [pages["mdna"]]),
        ("novel-generated", "What share of Northwind Robotics' FY2025 net sales came from its largest customer?",
         "18% of net sales.", [pages["risk"]]),
        ("novel-generated", "What interest rate do Northwind Robotics' senior notes carry?",
         "A fixed rate of 4.25% per year.", [pages["risk"], pages["notes"]]),
        ("novel-generated", "How much of Northwind Robotics' long-term debt principal is scheduled to be repaid in 2028?",
         "$300.0 million.", [pages["notes"]]),
        ("domain-relevant", "Did Northwind Robotics complete any acquisitions in FY2025?",
         f"No. It made no acquisitions in fiscal 2025; in fiscal 2024 it acquired Vector Grip Ltd. for ${-ACQ[1]:,.1f} million.",
         [pages["liquidity"], pages["cf"]]),
    ]
    out = []
    for i, (qtype, q, ans, ev_pages) in enumerate(rows, 1):
        out.append({
            "financebench_id": f"northwind_{i:03d}", "company": CO, "doc_name": DOC, "question_type": qtype,
            "question_reasoning": None, "domain_question_num": None, "question": q, "answer": ans,
            "justification": None, "dataset_subset_label": "SAMPLE",
            "evidence": [{"evidence_text": "", "doc_name": DOC, "evidence_page_num": p, "evidence_text_full_page": ""}
                         for p in ev_pages],
            "gics_sector": "Industrials", "doc_type": "10k", "doc_period": 2025,
        })
    return out


if __name__ == "__main__":
    OUT_PDF.parent.mkdir(exist_ok=True)
    pg = build()
    qs = questions(pg)
    OUT_Q.write_text("\n".join(json.dumps(q) for q in qs) + "\n")
    print(f"wrote {OUT_PDF.name} ({max(pg.values()) + 1} pages) and {len(qs)} questions")
    print("cash:", CASH_END, CASH_BEGIN, "| assets:", ta, "| equity:", teq)
