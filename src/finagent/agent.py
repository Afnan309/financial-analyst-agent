"""The 10-K analyst agent.

LLM mode is a ReAct-style loop: the model picks one tool per turn as a JSON
action, sees the observation, and finishes with a JSON final answer. Every
provider speaks the same protocol, so Claude, GPT and local Llama/Qwen models
are interchangeable and the loop is testable with a scripted fake model.

After the model answers, two guards run:
  1. citations: pages the agent never looked at are dropped
  2. numbers:   any number not traceable to a tool output marks the answer
                unverified (see grounding.py)
If the model fails to finish, the deterministic planner answers instead.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .grounding import check
from .ingest import Filing, load_bytes, load_file
from .llm import LLMClient, extract_json, get_client
from .planner import Planner
from .schemas import AgentAnswer, Citation, ToolCall
from .tools import TOOL_SPECS, Toolbox

log = logging.getLogger(__name__)

SYSTEM = """You are a meticulous financial analyst answering questions about one SEC filing (10-K / 10-Q).
You can only learn about the filing by calling tools. Never use outside knowledge of the company.

{overview}

TOOLS
{tools}

RULES
- Reported numbers: use find_line_item first; use search_filing for anything in the text (MD&A, notes, risk factors).
- ALL arithmetic (ratios, growth, averages, unit conversion, rounding) goes through calculate. Never compute in your head.
- Cash outflows such as capital expenditures and dividends appear as negative numbers in the cash flow statement;
  report them as positive amounts unless asked otherwise.
- Follow any definition, unit ("USD millions") or rounding instruction in the question exactly.
- Cite the page numbers (as shown, e.g. p.7 -> 7) where the numbers or text came from.
- If the filing does not contain the answer, say so and set "value" to null.

Reply with exactly ONE JSON object per turn, either a tool call:
{{"thought": "<short reasoning>", "tool": "<tool name>", "args": {{...}}}}
or the final answer:
{{"thought": "<short reasoning>", "final": {{"answer": "<one or two sentences>", "value": <number or null>, "unit": "<e.g. USD millions, %, ratio or null>", "pages": [<page numbers>]}}}}"""


def _tool_text() -> str:
    lines = []
    for name, spec in TOOL_SPECS.items():
        args = ", ".join(f'"{k}": {v}' for k, v in spec["args"].items())
        lines.append(f"- {name}: {spec['description']}\n  args: {{{args}}}")
    return "\n".join(lines)


class AnalystAgent:
    def __init__(self, filing: Filing, provider: str | LLMClient | None = "offline", model: str | None = None,
                 max_steps: int = 8):
        self.filing = filing
        self.tools = Toolbox(filing)
        self.planner = Planner(self.tools)
        if provider is None or provider == "offline":
            self.client: LLMClient | None = None
        elif isinstance(provider, LLMClient):
            self.client = provider
        else:
            self.client = get_client(provider, model)
        self.max_steps = max_steps

    @classmethod
    def from_file(cls, path: str | Path, **kw) -> AnalystAgent:
        return cls(load_file(path), **kw)

    @classmethod
    def from_bytes(cls, data: bytes, filename: str, **kw) -> AnalystAgent:
        return cls(load_bytes(data, filename), **kw)

    @property
    def provider_name(self) -> str:
        return self.client.name if self.client else "offline"

    # ------------------------------------------------------------------- ask
    def ask(self, question: str) -> AgentAnswer:
        if self.client is None:
            return self.planner.answer(question)
        try:
            return self._llm_loop(question)
        except Exception as e:  # network, auth, rate limits... never leave the user without an answer
            log.warning("LLM agent failed (%s); using deterministic planner", e)
            ans = self.planner.answer(question)
            ans.warnings.append(f"LLM agent failed ({type(e).__name__}); answered by the offline planner")
            return ans

    def _llm_loop(self, question: str) -> AgentAnswer:
        system = SYSTEM.format(overview=self.tools.overview(), tools=_tool_text())
        messages: list[dict[str, str]] = [{"role": "user", "content": f"Question: {question}"}]
        steps: list[ToolCall] = []
        for _ in range(self.max_steps):
            raw = self.client.complete(system, messages)
            try:
                data = extract_json(raw)
            except (json.JSONDecodeError, ValueError):
                messages += [{"role": "assistant", "content": raw[:2000]},
                             {"role": "user", "content": "That was not valid JSON. Reply with exactly one JSON object."}]
                continue
            messages.append({"role": "assistant", "content": json.dumps(data)})
            if isinstance(data.get("final"), dict):
                return self._finish(question, data["final"], steps)
            tool, args = data.get("tool"), data.get("args") or {}
            call = self.tools.run(str(tool), args if isinstance(args, dict) else {})
            steps.append(call)
            messages.append({"role": "user", "content": f"Observation ({call.tool}):\n{call.output[:6000]}"})

        ans = self.planner.answer(question)
        ans.steps = steps + ans.steps
        ans.warnings.append(f"LLM agent did not finish in {self.max_steps} steps; answered by the offline planner")
        return ans

    def _finish(self, question: str, final: dict, steps: list[ToolCall]) -> AgentAnswer:
        warnings: list[str] = []
        seen = {p for s in steps for p in s.pages}
        cited: list[int] = []
        for p in final.get("pages") or []:
            try:
                idx = int(str(p).lstrip("p.")) - 1
            except ValueError:
                continue
            if idx in seen:
                cited.append(idx)
            else:
                warnings.append(f"dropped citation p.{idx + 1}: the agent never opened that page")
        if not cited:  # fall back to the pages the evidence actually came from
            cited = sorted({p for s in steps if s.tool in ("find_line_item", "read_page") for p in s.pages}) or \
                    sorted({p for s in steps for p in s.pages})[:2]

        value = final.get("value")
        try:
            value = float(value) if value is not None else None
        except (TypeError, ValueError):
            value = None
        answer = str(final.get("answer", "")).strip()

        bad = check(answer, value, steps)
        if not steps:
            warnings.append("answered without consulting the filing")
        if bad:
            warnings.append("numbers not found in the filing or in a calculation: " + ", ".join(f"{b:g}" for b in bad))
        cites = [Citation(page=p, excerpt=self.filing.pages[p].text[:240]) for p in sorted(set(cited))]
        return AgentAnswer(question=question, answer=answer, value=value, unit=final.get("unit"), citations=cites,
                           steps=steps, grounded=bool(steps) and not bad, warnings=warnings, provider=self.provider_name)
