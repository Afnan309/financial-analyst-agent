import json
from pathlib import Path

import pytest

from finagent import AnalystAgent

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def _questions(name):
    return [json.loads(line) for line in (SAMPLES / name).read_text().splitlines() if line.strip()]


@pytest.fixture(scope="session")
def northwind():
    return AnalystAgent.from_file(SAMPLES / "NORTHWIND_2025_10K.pdf")


@pytest.fixture(scope="session")
def cascade():
    return AnalystAgent.from_file(SAMPLES / "CASCADE_2024_10K.htm")


@pytest.fixture(scope="session")
def northwind_questions():
    return _questions("northwind_questions.jsonl")


@pytest.fixture(scope="session")
def cascade_questions():
    return _questions("cascade_questions.jsonl")
