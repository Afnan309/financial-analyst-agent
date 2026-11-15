import json

import pytest

from finagent import AnalystAgent
from finagent.grounding import answer_numbers, check
from finagent.llm import LLMClient, extract_json
from finagent.schemas import ToolCall
from finagent.scoring import numeric_match, score, yes_no


# ------------------------------------------------------------- offline planner
def test_offline_answers_every_sample_question(northwind, northwind_questions):
    for q in northwind_questions:
        ans = northwind.ask(q["question"])
        gold_pages = {e["evidence_page_num"] for e in q["evidence"]}
        s = score(q["question"], q["answer"], ans.answer, ans.value, list(gold_pages), ans.pages, q["question_type"])
        assert s.correct, (q["financebench_id"], q["answer"], ans.answer)
        assert s.page_hit, (q["financebench_id"], ans.pages, gold_pages)
        assert ans.grounded


def test_offline_held_out_html_filing(cascade, cascade_questions):
    correct = sum(score(q["question"], q["answer"], (a := cascade.ask(q["question"])).answer, a.value,
                        [e["evidence_page_num"] for e in q["evidence"]], a.pages, q["question_type"]).correct
                  for q in cascade_questions)
    assert correct == len(cascade_questions)


def test_every_calculation_goes_through_the_calculator(northwind):
    ans = northwind.ask("What is Northwind Robotics' FY2025 return on assets? Use average total assets. Round to two decimal places.")
    tools = [s.tool for s in ans.steps]
    assert "calculate" in tools and "find_line_item" in tools
    assert ans.value == pytest.approx(13.54, abs=0.01)


def test_not_in_filing(northwind):
    ans = northwind.ask("What is the CEO's annual salary?")
    assert not ans.grounded and "could not find" in ans.answer.lower()


# ------------------------------------------------------------- grounding guard
def test_grounding():
    steps = [ToolCall(tool="find_line_item", args={}, output="", numbers=[4210.0, -256.6, 0.40000])]
    assert check("Revenue was $4,210 million in FY2025 (p.7).", None, steps) == []
    assert check("Capex was $256.6 million.", 256.6, steps) == []          # sign flip allowed
    assert check("Gross margin was 40.0%.", 40.0, steps) == []              # ratio -> percent allowed
    assert check("Revenue was $4.21 billion.", None, steps) == []           # unit change allowed
    assert check("Revenue was $4,950 million.", 4950, steps) == [4950]      # invented number caught
    assert answer_numbers("FY2025 margin on p.7 was 40%") == [40.0]          # years and pages ignored


# ------------------------------------------------------------------- LLM loop
class ScriptedLLM(LLMClient):
    name = "scripted"

    def __init__(self, replies):
        self.replies = iter(replies)
        self.seen: list[list[dict]] = []

    def complete(self, system, messages):
        self.seen.append(list(messages))
        r = next(self.replies)
        return r if isinstance(r, str) else json.dumps(r)


def test_llm_agent_happy_path(northwind):
    llm = ScriptedLLM([
        "Sure! let me think...",  # not JSON: the agent asks again
        {"thought": "need GP", "tool": "find_line_item", "args": {"name": "gross profit", "period": "2025"}},
        {"tool": "find_line_item", "args": {"name": "revenue", "period": "FY2025"}},
        {"tool": "calculate", "args": {"expression": "1684.0 / 4210.0 * 100"}},
        {"final": {"answer": "FY2025 gross margin was 40.0%.", "value": 40.0, "unit": "%", "pages": [7, 3]}},
    ])
    agent = AnalystAgent(northwind.filing, provider=llm)
    ans = agent.ask("What is the FY2025 gross margin?")
    assert ans.grounded and ans.value == 40.0 and ans.provider == "scripted"
    assert ans.pages == [6]                                    # p.3 dropped: never opened
    assert any("dropped citation p.3" in w for w in ans.warnings)
    assert "Observation (find_line_item)" in llm.seen[2][-1]["content"]
    assert "not valid JSON" in llm.seen[1][-1]["content"]


def test_llm_hallucinated_number_is_flagged(northwind):
    llm = ScriptedLLM([{"tool": "find_line_item", "args": {"name": "revenue"}},
                       {"final": {"answer": "Revenue was $4,950 million, up 14%.", "value": 4950, "pages": [7]}}])
    ans = AnalystAgent(northwind.filing, provider=llm).ask("FY2025 revenue?")
    assert not ans.grounded
    assert "4950" in ans.warnings[-1] and "14" in ans.warnings[-1]


def test_llm_without_tools_is_unverified(northwind):
    llm = ScriptedLLM([{"final": {"answer": "Revenue was about $4 billion.", "value": None, "pages": []}}])
    ans = AnalystAgent(northwind.filing, provider=llm).ask("Revenue?")
    assert not ans.grounded and "without consulting" in ans.warnings[0]


def test_llm_that_never_finishes_falls_back(northwind):
    llm = ScriptedLLM([{"tool": "search_filing", "args": {"query": "revenue"}}] * 3)
    agent = AnalystAgent(northwind.filing, provider=llm, max_steps=3)
    ans = agent.ask("What is Northwind Robotics' FY2025 total net sales in USD millions?")
    assert ans.value == 4210.0 and "offline planner" in ans.warnings[-1]


def test_llm_error_falls_back(northwind):
    class Broken(LLMClient):
        name = "broken"

        def complete(self, system, messages):
            raise ConnectionError("no network")

    ans = AnalystAgent(northwind.filing, provider=Broken()).ask("What is the FY2025 current ratio?")
    assert ans.value == pytest.approx(2.68, abs=0.01) and "ConnectionError" in ans.warnings[-1]


def test_unknown_tool_is_reported(northwind):
    call = northwind.tools.run("delete_everything", {})
    assert "Unknown tool" in call.output


# --------------------------------------------------------------------- scoring
def test_scoring_rules():
    assert numeric_match("$1577.00", "Capex was $1.577 billion")             # unit rescale
    assert numeric_match("24.26%", "0.2426")                                  # ratio vs percent
    assert not numeric_match("$1577.00", "$1,800 million")
    assert yes_no("No, the company did not.", "The company did not pay dividends.")
    assert yes_no("Yes. It acquired X.", "Yes, it completed one acquisition.")
    assert not yes_no("Yes.", "No, it did not.")
    assert score("q", "Logistics", "Services segment", None, [1], [1], "domain-relevant").verdict == "needs_review"
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
