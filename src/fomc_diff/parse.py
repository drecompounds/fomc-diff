"""HTML -> role-tagged paragraphs. Stdlib only; never touches the network."""
from __future__ import annotations

import hashlib
import html as html_mod
import re
from dataclasses import dataclass

_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)
# Comments must go BEFORE tags: <[^>]+> stops at the first ">" inside a
# "<!-- ... -->" block, so tag-stripping alone leaves "-->" fragments behind in
# the text -- and therefore in its sha256.
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

_DATE_LINE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")

# The Fed glues its release line -- and the "Share" widget -- onto the FRONT of
# the first body paragraph. In 86 of the 89 statements from 2016-2026 the
# opening economic assessment lives inside that same <p>, and on 2020-03-03 the
# emergency 50bp rate decision does too. So this boilerplate must be stripped as
# a PREFIX, never used to discard the paragraph carrying it; dropping the whole
# paragraph deleted the decision and left a parse that looked successful.
_RELEASE_LINE = re.compile(
    r"^For\s+(?:release\s+at\s+[\d:]+\s*[ap]\.m\.\s*E[SD]T|immediate\s+release)"
    r"\s*(?:Share\s*)?",
    re.I,
)

# These stand alone as their own paragraphs -- nothing substantive is ever glued
# behind them -- so matching one means the whole paragraph is boilerplate.
_DROP_PREFIXES = (
    "For media inquiries",
    "Implementation Note",
    "Last Update",
    "Share",
)


class ArticleContainerError(ValueError):
    """Raised when HTML article container is missing or malformed."""
    pass


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
        raise ArticleContainerError(
            "Article container not found: page structure is unrecognised "
            "(expected <div id=\"article\">)"
        )

    # Find the matching closing </div> for the article container.
    # Note: assumes well-formed input; does not account for <div in comments/strings.
    depth = 1
    pos = article_start + len('<div id="article">')
    article_html = None
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

    if article_html is None:
        raise ArticleContainerError(
            "Article container unterminated: no matching closing tag found for "
            "<div id=\"article\">"
        )

    out: list[str] = []
    for raw in _P.findall(article_html):
        text = html_mod.unescape(_TAG.sub(" ", _COMMENT.sub(" ", raw)))
        # _WS (regex \s+) already matches NBSP (Unicode \s includes NBSP),
        # so a separate NBSP-to-space replace here would be dead code.
        text = _WS.sub(" ", text).strip()
        if text:
            out.append(text)
    return out


def _strip_boilerplate(text: str) -> str:
    """Remove boilerplate and return whatever real content remains.

    Returns "" when the paragraph is boilerplate through and through. Anything
    else is body text and is kept -- including body text that had a release
    line welded to the front of it.
    """
    if _DATE_LINE.match(text):
        return ""
    text = _RELEASE_LINE.sub("", text).strip()
    if not text or any(text.startswith(p) for p in _DROP_PREFIXES):
        return ""
    return text


def role_for(text: str) -> str:
    # The vote-announcement line ("...approved the following statement for
    # release by a 9-3 vote:") is where parse_vote reads the count.
    if "approved the following statement for release" in text:
        return "vote"
    # BOTH vote checks MUST precede `policy`. In 2016-2025 the voting paragraph
    # contains "target range for the federal funds rate", because the
    # dissenter's preferred alternative names it -- so `policy` would swallow
    # the entire vote record. This is the same trap that already required
    # dissent-before-policy; its scope was simply too narrow.
    if text.startswith("Voting for"):
        return "vote_for"
    if text.startswith("Voting against"):
        return "vote_against"
    if "target range for the federal funds rate" in text:
        return "policy"
    if text.startswith("Inflation"):
        return "inflation"
    if "Economic activity" in text:
        return "economy"
    return "unclassified"


def parse_statement(html: str) -> list[Paragraph]:
    paras = [s for s in (_strip_boilerplate(p) for p in extract_paragraphs(html)) if s]
    return [
        Paragraph(i, role_for(t), t,
                  hashlib.sha256(t.encode("utf-8")).hexdigest())
        for i, t in enumerate(paras)
    ]
