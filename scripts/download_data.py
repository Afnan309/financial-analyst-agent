"""Download real data (run this on your own machine; it needs internet).

    # FinanceBench open sample: 150 questions + source PDFs (CC BY-NC 4.0, non-commercial use)
    python scripts/download_data.py financebench

    # Any company's 10-K straight from SEC EDGAR
    export SEC_USER_AGENT="Your Name your.email@example.com"   # SEC requires a contact in the User-Agent
    python scripts/download_data.py edgar --ticker AAPL --year 2024
    python scripts/download_data.py edgar --ticker MSFT --year 2023 --form 10-Q

SEC fair-access rules: identify yourself and stay under 10 requests per second.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
FB_REPO = "https://github.com/patronus-ai/financebench.git"


def financebench(dest: Path = DATA / "financebench") -> None:
    if (dest / "data" / "financebench_open_source.jsonl").exists():
        print(f"already present: {dest}")
        return
    if not shutil.which("git"):
        sys.exit("git is required: install it, or download the repo zip from GitHub into data/financebench")
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", FB_REPO, str(dest)], check=True)
    n = sum(1 for _ in (dest / "data" / "financebench_open_source.jsonl").open())
    print(f"FinanceBench ready: {n} questions, {len(list((dest / 'pdfs').glob('*.pdf')))} PDFs in {dest}")


def _get(url: str, ua: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    time.sleep(0.2)  # stay well under SEC's 10 requests/second limit
    return data


def edgar(ticker: str, year: int, form: str = "10-K", dest: Path = DATA / "edgar") -> Path:
    ua = os.getenv("SEC_USER_AGENT")
    if not ua or "@" not in ua:
        sys.exit('Set SEC_USER_AGENT="Your Name your.email@example.com" (SEC requires a contact address).')
    tickers = json.loads(_get("https://www.sec.gov/files/company_tickers.json", ua))
    match = next((v for v in tickers.values() if v["ticker"].upper() == ticker.upper()), None)
    if not match:
        sys.exit(f"Ticker {ticker} not found in SEC's company list.")
    cik = int(match["cik_str"])
    subs = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", ua))
    recent = subs["filings"]["recent"]
    for i, f in enumerate(recent["form"]):
        report = recent["reportDate"][i] or recent["filingDate"][i]
        if f == form and report.startswith(str(year)):
            acc = recent["accessionNumber"][i].replace("-", "")
            doc = recent["primaryDocument"][i]
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
            dest.mkdir(parents=True, exist_ok=True)
            out = dest / f"{ticker.upper()}_{year}_{form.replace('-', '')}{Path(doc).suffix or '.htm'}"
            out.write_bytes(_get(url, ua))
            print(f"saved {out}  ({match['title']}, period {report})\n  source: {url}")
            return out
    sys.exit(f"No {form} with a report date in {year} among {ticker}'s recent filings.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("financebench")
    e = sub.add_parser("edgar")
    e.add_argument("--ticker", required=True)
    e.add_argument("--year", type=int, required=True, help="fiscal year of the report period")
    e.add_argument("--form", default="10-K", choices=["10-K", "10-Q"])
    a = ap.parse_args()
    if a.cmd == "financebench":
        financebench()
    else:
        edgar(a.ticker, a.year, a.form)


if __name__ == "__main__":
    main()
