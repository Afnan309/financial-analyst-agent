import importlib.util
import json
from pathlib import Path

import pytest

from finagent.cli import main

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "samples" / "NORTHWIND_2025_10K.pdf"


def test_cli_ask_trace(capsys):
    assert main(["ask", str(PDF), "What is the FY2025 operating margin? Round to one decimal place.", "--trace"]) == 0
    out = capsys.readouterr().out
    assert "18.0%" in out and "Sources: p.7" in out and "calculate(" in out


def test_cli_ask_json(capsys):
    main(["ask", str(PDF), "What is the FY2025 capital expenditure in USD millions?", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["value"] == 256.6 and data["citations"][0]["page"] == 8


def test_cli_extract(tmp_path):
    out = tmp_path / "items.csv"
    assert main(["extract", str(PDF), "--csv", str(out)]) == 0
    assert "Net income" in out.read_text()


def test_eval_runner(tmp_path):
    spec = importlib.util.spec_from_file_location("run_fb", ROOT / "eval" / "run_financebench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    qs = mod.load_questions(ROOT / "samples" / "cascade_questions.jsonl")
    qs.append({**qs[0], "financebench_id": "missing_doc", "doc_name": "NOPE_2020_10K"})
    s = mod.run(qs, ROOT / "samples", "offline", out_dir=tmp_path, quiet=True)
    assert s["scored"] == 13 and s["skipped"] == 1 and s["accuracy"] == 1.0 and s["page_hit_rate"] == 1.0
    assert "| metrics-generated | 10 |" in mod.to_markdown(s)


def test_api():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from finagent.api import app

    c = TestClient(app)
    r = c.post("/documents", files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    doc = r.json()["doc_id"]
    a = c.post(f"/documents/{doc}/ask", json={"question": "What is the FY2025 current ratio?"}).json()
    assert a["grounded"] and abs(a["value"] - 2.68) < 0.01
    assert c.get(f"/documents/{doc}/pages/7").json()["section"].startswith("Item 8")
    assert len(c.get(f"/documents/{doc}/line-items").json()) > 50
    assert c.post("/documents", files={"file": ("x.xlsx", b"1", "application/octet-stream")}).status_code == 422
