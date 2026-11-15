"""Load 10-K filings (PDF or SEC EDGAR HTML) into pages.

Pages matter: every answer cites a page, and FinanceBench scores evidence by
page number. EDGAR HTML has no physical pages, so we split on the page-break
markers EDGAR documents use (``page-break-before/after`` styles and ``<hr>``).
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from .schemas import Page

SECTION_RX = re.compile(
    r"^\s*item\s+(1a|1b|1c|1|2|3|4|5|6|7a|7|8|9a|9b|9|10|11|12|13|14|15)\b[\.:\s]*([^\n]{0,80})",
    re.I | re.M,
)
SECTION_NAMES = {
    "1": "Item 1. Business", "1a": "Item 1A. Risk Factors", "1b": "Item 1B. Unresolved Staff Comments",
    "1c": "Item 1C. Cybersecurity", "2": "Item 2. Properties", "3": "Item 3. Legal Proceedings",
    "5": "Item 5. Market for Common Equity", "7": "Item 7. MD&A", "7a": "Item 7A. Market Risk",
    "8": "Item 8. Financial Statements", "9a": "Item 9A. Controls and Procedures",
}


@dataclass
class Filing:
    name: str
    pages: list[Page] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    def page(self, index: int) -> Page:
        return self.pages[index]


def _clean(text: str) -> str:
    text = text.replace(" ", " ").replace(" ", " ").replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _tag_sections(pages: list[Page]) -> list[Page]:
    """Carry the most recent 'Item X' heading forward onto each page.

    Table-of-contents pages list every item, so a page that mentions 4+ items is
    treated as a TOC and does not change the current section.
    """
    current: str | None = None
    for p in pages:
        hits = SECTION_RX.findall(p.text)
        if 0 < len(hits) < 4:
            key = hits[-1][0].lower()
            current = SECTION_NAMES.get(key, f"Item {key.upper()}")
        p.section = current
    return pages


# ----------------------------------------------------------------------- PDF
def _pdf_pages(data: bytes) -> list[str]:
    import pdfplumber

    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            # layout-free text with small x tolerance keeps table rows on one line
            out.append(page.extract_text(x_tolerance=1.5, y_tolerance=3) or "")
    return out


# ---------------------------------------------------------------------- HTML
class _EdgarHTML(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"}
    PAGE_BREAK = re.compile(r"page-break-(before|after)\s*:\s*always", re.I)

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pages: list[list[str]] = [[]]
        self.skip = 0
        self.in_cell = False

    def _break(self):
        if any(s.strip() for s in self.pages[-1]):
            self.pages.append([])

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "head", "ix:header"):
            self.skip += 1
        style = (a.get("style") or "").lower()
        if tag == "hr" or (self.PAGE_BREAK.search(style) and "before" in style):
            self._break()  # page-break-after on non-void tags is rewritten to a trailing <hr/> before parsing
        if tag in self.BLOCK:
            self.pages[-1].append("\n")
        if tag in ("td", "th"):
            self.pages[-1].append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "ix:header"):
            self.skip = max(0, self.skip - 1)
        if tag in self.BLOCK:
            self.pages[-1].append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.pages[-1].append(data)


def _html_pages(data: bytes) -> list[str]:
    html = data.decode("utf-8", errors="replace")
    # "page-break-after" on an element: break after it closes. Normalise to an <hr> after the tag.
    # (void tags like <hr/> are handled directly by the parser)
    html = re.sub(r"(<(?!hr\b|br\b)(\w+)\b[^>]*page-break-after\s*:\s*always[^>]*>.*?</\2>)", r"\1<hr/>", html,
                  flags=re.I | re.S)
    p = _EdgarHTML()
    p.feed(html)
    pages = []
    for chunks in p.pages:
        text = "".join(chunks)
        # join "$" and "(" cells that EDGAR puts in their own <td>
        text = re.sub(r"\$\s+(?=[\d(])", "$", text)
        text = re.sub(r"\(\s+(?=\d)", "(", text)
        text = re.sub(r"(?<=\d)\s+\)", ")", text)
        lines = [" ".join(line.split()) for line in text.split("\n")]
        pages.append("\n".join(line for line in lines if line))
    return [pg for pg in pages if pg.strip()]


# ------------------------------------------------------------------- public
def load_bytes(data: bytes, filename: str) -> Filing:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        raw = _pdf_pages(data)
    elif suffix in (".htm", ".html"):
        raw = _html_pages(data)
    elif suffix in (".txt", ".md"):
        text = data.decode("utf-8", errors="replace")
        raw = re.split(r"\f|\n-{5,} ?page ?break ?-{5,}\n", text, flags=re.I)
    else:
        raise ValueError(f"Unsupported file type '{suffix}'. Use .pdf, .htm/.html or .txt")
    pages = [Page(index=i, text=_clean(t)) for i, t in enumerate(raw)]
    if not any(p.text for p in pages):
        raise ValueError("No extractable text. The PDF may be scanned; run OCR first.")
    return Filing(name=filename, pages=_tag_sections(pages))


def load_file(path: str | Path) -> Filing:
    path = Path(path)
    return load_bytes(path.read_bytes(), path.name)
