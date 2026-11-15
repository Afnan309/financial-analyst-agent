"""REST API.

    uvicorn finagent.api:app --reload      # docs at http://localhost:8000/docs
"""
from __future__ import annotations

import os
import uuid
from collections import OrderedDict

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .agent import AnalystAgent
from .llm import PROVIDERS
from .schemas import AgentAnswer, LineItem

MAX_BYTES = int(os.getenv("FINAGENT_MAX_MB", "40")) * 1024 * 1024
CACHE = int(os.getenv("FINAGENT_CACHE", "20"))

app = FastAPI(title="10-K Analyst Agent API", version=__version__,
              description="Upload a 10-K (PDF or EDGAR HTML), then ask questions. Every answer cites pages and "
                          "every number is checked against the filing.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","), allow_methods=["*"],
                   allow_headers=["*"])
_docs: OrderedDict[str, AnalystAgent] = OrderedDict()


class UploadResponse(BaseModel):
    doc_id: str
    name: str
    pages: int
    overview: str


class Question(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)


def _agent(doc_id: str) -> AnalystAgent:
    if doc_id not in _docs:
        raise HTTPException(404, "Unknown or expired doc_id")
    return _docs[doc_id]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "providers": list(PROVIDERS)}


@app.post("/documents", response_model=UploadResponse)
async def upload(file: UploadFile = File(...), provider: str = Form("offline"), model: str | None = Form(None)):
    if provider not in PROVIDERS:
        raise HTTPException(400, f"provider must be one of {PROVIDERS}")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large")
    try:
        agent = AnalystAgent.from_bytes(data, file.filename or "filing.pdf", provider=provider, model=model)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(422, str(e)) from e
    doc_id = uuid.uuid4().hex[:12]
    _docs[doc_id] = agent
    while len(_docs) > CACHE:
        _docs.popitem(last=False)
    return UploadResponse(doc_id=doc_id, name=agent.filing.name, pages=len(agent.filing.pages),
                          overview=agent.tools.overview())


@app.post("/documents/{doc_id}/ask", response_model=AgentAnswer)
def ask(doc_id: str, q: Question):
    return _agent(doc_id).ask(q.question)


@app.get("/documents/{doc_id}/line-items", response_model=list[LineItem])
def line_items(doc_id: str):
    return _agent(doc_id).tools.items


@app.get("/documents/{doc_id}/pages/{page}")
def page(doc_id: str, page: int):
    f = _agent(doc_id).filing
    if not 1 <= page <= len(f.pages):
        raise HTTPException(404, "No such page")
    p = f.pages[page - 1]
    return {"page": page, "section": p.section, "text": p.text}
