"""Command line.

    finagent ask samples/NORTHWIND_2025_10K.pdf "What is the FY2025 operating margin?" --trace
    finagent ask data/edgar/AAPL_2024_10K.htm "How much did Apple spend on R&D?" --provider claude
    finagent extract samples/NORTHWIND_2025_10K.pdf --csv line_items.csv
    finagent chat samples/NORTHWIND_2025_10K.pdf
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from . import __version__
from .agent import AnalystAgent
from .llm import PROVIDERS
from .tables import extract_line_items


def _print_answer(ans, trace: bool) -> None:
    print(ans.answer)
    if ans.citations:
        print("Sources: " + ", ".join(c.label for c in ans.citations))
    if not ans.grounded:
        print("⚠ unverified answer")
    for w in ans.warnings:
        print(f"  note: {w}")
    if trace:
        print("\nAgent trace:")
        for i, s in enumerate(ans.steps, 1):
            first = s.output.splitlines()[0] if s.output else ""
            print(f"  {i}. {s.tool}({', '.join(f'{k}={v!r}' for k, v in s.args.items())}) -> {first[:110]}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="finagent", description="10-K financial analyst agent")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("file", type=Path, help="10-K / 10-Q as PDF or EDGAR .htm")
    common.add_argument("--provider", choices=PROVIDERS, default="offline")
    common.add_argument("--model", default=None)

    a = sub.add_parser("ask", parents=[common], help="ask one question")
    a.add_argument("question")
    a.add_argument("--trace", action="store_true", help="show every tool call")
    a.add_argument("--json", action="store_true", help="print the full answer as JSON")

    sub.add_parser("chat", parents=[common], help="interactive Q&A")

    e = sub.add_parser("extract", help="dump every financial statement line item")
    e.add_argument("file", type=Path)
    e.add_argument("--csv", type=Path, default=None)

    args = p.parse_args(argv)

    if args.cmd == "extract":
        from .ingest import load_file

        items = extract_line_items(load_file(args.file))
        years = sorted({y for it in items for y in it.values}, reverse=True)
        out = open(args.csv, "w", newline="") if args.csv else sys.stdout
        w = csv.writer(out)
        w.writerow(["page", "statement", "unit", "label", *years])
        for it in items:
            w.writerow([it.page + 1, it.statement or "", it.unit, it.label, *[it.values.get(y, "") for y in years]])
        if args.csv:
            out.close()
            print(f"Wrote {len(items)} line items to {args.csv}")
        return 0

    agent = AnalystAgent.from_file(args.file, provider=args.provider, model=args.model)
    if args.cmd == "ask":
        ans = agent.ask(args.question)
        if args.json:
            print(ans.model_dump_json(indent=2))
        else:
            _print_answer(ans, args.trace)
        return 0 if ans.grounded else 1

    print(agent.tools.overview())
    print("Ask a question (empty line to quit).")
    while True:
        try:
            q = input("\n> ").strip()
        except EOFError:
            break
        if not q:
            break
        _print_answer(agent.ask(q), trace=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
