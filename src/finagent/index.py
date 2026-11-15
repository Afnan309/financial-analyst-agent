"""Search over a filing: TF-IDF chunks with page numbers + finance query expansion."""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .ingest import Filing

EXPAND = {
    "revenue": "net sales revenues", "sales": "net sales revenues", "capex": "capital expenditures property plant equipment",
    "debt": "notes borrowings long-term debt", "customer": "customers concentration largest", "risk": "risk factors",
    "acquisition": "acquired acquisitions purchase", "acquisitions": "acquired acquisition", "segment": "segments segment",
    "grew": "increase growth increased", "growth": "increase increased", "interest": "interest rate notes",
    "dividend": "dividends paid", "buyback": "repurchases share", "repaid": "principal payments scheduled maturities",
    "repayment": "principal payments scheduled maturities", "matures": "maturities scheduled principal payments",
    "employees": "employees headcount", "tax": "income taxes effective tax rate", "margin": "gross margin percentage",
}


@dataclass
class Chunk:
    page: int
    text: str
    section: str | None


def _chunks(filing: Filing, size: int = 900, overlap: int = 150) -> list[Chunk]:
    out = []
    for p in filing.pages:
        t = p.text
        if len(t) <= size:
            out.append(Chunk(p.index, t, p.section))
            continue
        start = 0
        while start < len(t):
            end = min(len(t), start + size)
            # finish on a sentence or line break when possible
            cut = max(t.rfind(". ", start, end), t.rfind("\n", start, end))
            if end < len(t) and cut > start + size // 2:
                end = cut + 1
            out.append(Chunk(p.index, t[start:end].strip(), p.section))
            if end >= len(t):
                break
            start = max(end - overlap, start + 1)
    return out


_STOPWORDS = {"the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "is", "are", "was", "were", "be", "by", "with",
              "what", "which", "who", "when", "how", "does", "did", "do", "this", "that", "it", "its", "our", "we", "as",
              "at", "from", "has", "have", "had", "any", "inc", "corp", "company"}


def stem(w: str) -> str:
    for suf in ("ations", "ation", "ing", "ies", "es", "ed", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def analyze(text: str) -> list[str]:
    """Lower-case, drop stopwords, stem, then unigrams + bigrams."""
    words = [stem(w) for w in re.findall(r"[a-z0-9][a-z0-9&.-]*[a-z0-9]|[a-z0-9]", text.lower()) if w not in _STOPWORDS]
    return words + [f"{a} {b}" for a, b in zip(words, words[1:])]


def expand(query: str) -> str:
    extra = [EXPAND[w] for w in re.findall(r"[a-z]+", query.lower()) if w in EXPAND]
    return " ".join([query, *extra])


class FilingIndex:
    def __init__(self, filing: Filing):
        self.filing = filing
        self.chunks = _chunks(filing)
        docs = [f"{c.section or ''} {c.text}" for c in self.chunks]
        self.vec = TfidfVectorizer(analyzer=analyze, sublinear_tf=True)
        self.matrix = self.vec.fit_transform(docs)
        # table-of-contents pages mention every topic and win searches they should not, so they are excluded
        from .ingest import SECTION_RX

        self.weights = np.array([0.0 if len(SECTION_RX.findall(filing.pages[c.page].text)) >= 4 else 1.0
                                 for c in self.chunks])

    def search(self, query: str, k: int = 4) -> list[tuple[Chunk, float]]:
        scores = (self.matrix @ self.vec.transform([expand(query)]).T).toarray().ravel() * self.weights
        order = np.argsort(-scores)
        out, seen = [], set()
        for i in order:
            if scores[i] <= 0 or len(out) >= k:
                break
            key = (self.chunks[i].page, self.chunks[i].text[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append((self.chunks[i], float(scores[i])))
        return out
