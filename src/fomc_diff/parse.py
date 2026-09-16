"""HTML -> role-tagged paragraphs. Stdlib only; never touches the network."""
from __future__ import annotations

import hashlib
import html as html_mod
import re
from dataclasses import dataclass

_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

_DATE_LINE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")
_DROP_PREFIXES = (
    "For release at",
    "For media inquiries",
    "Implementation Note",
    "Last Update",
    "Share",
)


@dataclass(frozen=True)
class Paragraph:
    index: int
    role: str
    text: str
    sha256: str


def extract_paragraphs(html: str) -> list[str]:
    # Extract only from the article div to avoid header/footer/nav boilerplate
    article_start = html.find('<div id="article">')
    if article_start == -1:
        # Fallback: extract from entire HTML if article div not found
        article_html = html
    else:
        # Find the matching closing </div> for the article container
        depth = 1
        pos = article_start + len('<div id="article">')
        while depth > 0 and pos < len(html):
            next_open = html.find('<div', pos)
            next_close = html.find('</div>', pos)
            if next_close == -1:
                break
            if next_open == -1 or next_close < next_open:
                depth -= 1
                if depth == 0:
                    article_html = html[article_start:next_close + len('</div>')]
                    break
                pos = next_close + len('</div>')
            else:
                depth += 1
                pos = next_open + len('<div')
        else:
            article_html = html

    out: list[str] = []
    for raw in _P.findall(article_html):
        text = html_mod.unescape(_TAG.sub(" ", raw))
        text = text.replace(" ", " ")
        text = _WS.sub(" ", text).strip()
        if text:
            out.append(text)
    return out


def _is_boilerplate(text: str) -> bool:
    if _DATE_LINE.match(text):
        return True
    return any(text.startswith(p) for p in _DROP_PREFIXES)


def role_for(text: str) -> str:
    if text.startswith("Voting against"):
        return "dissent"
    if "target range for the federal funds rate" in text:
        return "policy"
    if text.startswith("Inflation"):
        return "inflation"
    if "Economic activity" in text:
        return "economy"
    return "unclassified"


def parse_statement(html: str) -> list[Paragraph]:
    paras = [p for p in extract_paragraphs(html) if not _is_boilerplate(p)]
    return [
        Paragraph(i, role_for(t), t,
                  hashlib.sha256(t.encode("utf-8")).hexdigest())
        for i, t in enumerate(paras)
    ]
