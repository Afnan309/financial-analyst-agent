"""Typed models shared across the agent.

Page numbers are ZERO-indexed internally (same convention as FinanceBench's
``evidence_page_num``) and shown to humans as ``page + 1``.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Page(BaseModel):
    index: int = Field(..., description="Zero-indexed page number")
    text: str
    section: str | None = Field(None, description="e.g. 'Item 7. MD&A'")

    @property
    def label(self) -> str:
        return f"p.{self.index + 1}"


class LineItem(BaseModel):
    """One row of a financial table, e.g. 'Total net sales' with values per fiscal year."""

    label: str
    values: dict[str, float] = Field(..., description="period -> value, e.g. {'2025': 4210.0}")
    unit: str = Field("units", description="'millions', 'thousands', 'billions' or 'units'")
    page: int
    statement: str | None = Field(None, description="income_statement / balance_sheet / cash_flow / other")

    def value_for(self, period: str | None) -> tuple[str, float] | None:
        if not self.values:
            return None
        if period is None:
            p = max(self.values)
            return p, self.values[p]
        for key in (period, period[-4:]):
            if key in self.values:
                return key, self.values[key]
        return None


class ToolCall(BaseModel):
    tool: str
    args: dict[str, Any]
    output: str
    pages: list[int] = Field(default_factory=list)
    numbers: list[float] = Field(default_factory=list, description="numbers the tool returned, for grounding")


class Citation(BaseModel):
    page: int
    excerpt: str

    @property
    def label(self) -> str:
        return f"p.{self.page + 1}"


class AgentAnswer(BaseModel):
    question: str
    answer: str
    value: float | None = None
    unit: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    steps: list[ToolCall] = Field(default_factory=list)
    grounded: bool = Field(..., description="True when every number in the answer traces back to a tool output")
    warnings: list[str] = Field(default_factory=list)
    provider: str = "offline"

    @property
    def pages(self) -> list[int]:
        return sorted({c.page for c in self.citations})
