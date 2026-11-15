"""Run the analyst agent on FinanceBench (or any file in the same format).

FinanceBench (Patronus AI, 2023): open-book QA over real SEC filings. The open
sample has 150 questions with gold answers and evidence page numbers
(zero-indexed). License: CC BY-NC 4.0, so do not redistribute the data.

Get the data (on your machine):
    python scripts/download_data.py financebench          # -> data/financebench/

Run:
    python eval/run_financebench.py --data data/financebench --provider offline
    python eval/run_financebench.py --data data/financebench --provider claude --limit 30
    python eval/run_financebench.py --data data/financebench --provider claude --judge claude   # LLM-graded text answers

    # the bundled fictional sample (no download needed)
    python eval/run_financebench.py --questions samples/northwind_questions.jsonl --pdfs samples
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from finagent import AnalystAgent  # noqa: E402
from finagent.llm import get_client  # noqa: E402
from finagent.scoring import score  # noqa: E402


def load_questions(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for r in rows:
        r["gold_pages"] = sorted({int(e["evidence_page_num"]) for e in r.get("evidence", []) if "evidence_page_num" in e})
    return rows


def run(questions: list[dict], pdf_dir: Path, provider: str, model: str | None = None, judge: str | None = None,
        limit: int | None = None, types: set[str] | None = None, out_dir: Path | None = None, quiet: bool = False) -> dict:
    qs = [q for q in questions if not types or q.get("question_type") in types][:limit]
    judge_client = get_client(judge) if judge else None
    agents: dict[str, AnalystAgent | None] = {}
    results = []
    t_start = time.time()

    for i, q in enumerate(qs, 1):
        doc = q["doc_name"]
        if doc not in agents:
            pdf = next((pdf_dir / f"{doc}{ext}" for ext in (".pdf", ".htm", ".html") if (pdf_dir / f"{doc}{ext}").exists()), pdf_dir / f"{doc}.pdf")
            try:
                agents[doc] = AnalystAgent.from_file(pdf, provider=provider, model=model) if pdf.exists() else None
            except ValueError as e:
                print(f"  ! could not read {pdf.name}: {e}", file=sys.stderr)
                agents[doc] = None
        agent = agents[doc]
        if agent is None:
            results.append({**_base(q), "verdict": "skipped", "reason": "pdf missing or unreadable"})
            continue
        t0 = time.time()
        ans = agent.ask(q["question"])
        s = score(q["question"], q["answer"], ans.answer, ans.value, q["gold_pages"], ans.pages, q.get("question_type"),
                  judge_client)
        results.append({**_base(q), "prediction": ans.answer, "value": ans.value, "pred_pages": ans.pages,
                        "verdict": s.verdict, "method": s.method, "page_hit": s.page_hit, "grounded": ans.grounded,
                        "steps": len(ans.steps), "warnings": ans.warnings, "seconds": round(time.time() - t0, 2)})
        if not quiet:
            mark = {"correct": "✓", "incorrect": "✗", "needs_review": "?"}[s.verdict]
            print(f"[{i}/{len(qs)}] {mark} {q['financebench_id']}  {q['question'][:70]}", file=sys.stderr)

    summary = summarize(results, provider, model, time.time() - t_start)
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{Path(qs[0]['doc_name']).stem.split('_')[0].lower() if qs else 'empty'}_{provider}_{len(qs)}"
        (out_dir / f"{stem}.jsonl").write_text("\n".join(json.dumps(r) for r in results) + "\n")
        (out_dir / f"{stem}.md").write_text(to_markdown(summary))
        summary["files"] = [str(out_dir / f"{stem}.jsonl"), str(out_dir / f"{stem}.md")]
    return summary


def _base(q: dict) -> dict:
    return {"id": q["financebench_id"], "doc": q["doc_name"], "type": q.get("question_type"), "question": q["question"],
            "gold": q["answer"], "gold_pages": q["gold_pages"]}


def summarize(results: list[dict], provider: str, model: str | None, seconds: float) -> dict:
    scored = [r for r in results if r["verdict"] != "skipped"]
    by_type: dict[str, Counter] = defaultdict(Counter)
    for r in scored:
        by_type[r["type"] or "unknown"][r["verdict"]] += 1
    n = len(scored)
    correct = sum(r["verdict"] == "correct" for r in scored)
    review = sum(r["verdict"] == "needs_review" for r in scored)
    hits = [r["page_hit"] for r in scored if r.get("page_hit") is not None]
    return {
        "provider": provider, "model": model, "questions": len(results), "scored": n,
        "skipped": len(results) - n, "correct": correct, "needs_review": review,
        "accuracy": round(correct / n, 3) if n else 0.0,
        "accuracy_excl_review": round(correct / (n - review), 3) if n - review else 0.0,
        "page_hit_rate": round(sum(hits) / len(hits), 3) if hits else None,
        "grounded_rate": round(sum(bool(r.get("grounded")) for r in scored) / n, 3) if n else None,
        "avg_steps": round(sum(r.get("steps", 0) for r in scored) / n, 1) if n else None,
        "seconds": round(seconds, 1),
        "by_type": {k: dict(v) for k, v in by_type.items()},
    }


def to_markdown(s: dict) -> str:
    lines = [
        f"**Provider:** {s['provider']}{' / ' + s['model'] if s.get('model') else ''} · **Questions:** {s['scored']} "
        f"(skipped {s['skipped']}) · **Accuracy:** {s['accuracy']:.1%} · **Page hit rate:** "
        f"{(s['page_hit_rate'] or 0):.1%} · **Grounded:** {(s['grounded_rate'] or 0):.1%} · **Avg tool calls:** {s['avg_steps']}",
        "", "| Question type | Correct | Incorrect | Needs review |", "|---|---:|---:|---:|",
    ]
    for t, c in sorted(s["by_type"].items()):
        lines.append(f"| {t} | {c.get('correct', 0)} | {c.get('incorrect', 0)} | {c.get('needs_review', 0)} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, help="FinanceBench repo folder (with data/ and pdfs/)")
    ap.add_argument("--questions", type=Path, help="questions .jsonl (overrides --data)")
    ap.add_argument("--pdfs", type=Path, help="folder of <doc_name>.pdf files (overrides --data)")
    ap.add_argument("--provider", default="offline")
    ap.add_argument("--model", default=None)
    ap.add_argument("--judge", default=None, help="provider used to grade free-text answers (optional)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--types", default=None, help="comma list: metrics-generated,domain-relevant,novel-generated")
    ap.add_argument("--out", type=Path, default=Path("eval/results"))
    a = ap.parse_args()

    qpath = a.questions or (a.data / "data" / "financebench_open_source.jsonl" if a.data else None)
    pdfs = a.pdfs or (a.data / "pdfs" if a.data else None)
    if not qpath or not pdfs:
        ap.error("give --data, or both --questions and --pdfs")
    types = set(a.types.split(",")) if a.types else None
    summary = run(load_questions(qpath), pdfs, a.provider, a.model, a.judge, a.limit, types, a.out)
    print(to_markdown(summary))
    print(json.dumps({k: v for k, v in summary.items() if k != "by_type"}, indent=2))


if __name__ == "__main__":
    main()
