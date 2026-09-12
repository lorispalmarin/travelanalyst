"""Normalizzazione dei contenuti della fonte.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Literal

LinkKind = Literal["web", "email", "phone"]

_BLOCK_END = re.compile(r"(?i)</(p|div|li|tr|h[1-6])\s*>")
_BR = re.compile(r"(?i)<br\s*/?>")
_TAG = re.compile(r"<[^>]+>")
_ANCHOR = re.compile(r'<a\b[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
_DECORATIVE = re.compile(r"^[\s*_=~·•+\-–—]{3,}$")

# Nomi con cui la fonte cita le proprie sezioni -> campi di CountrySheet.
_SECTION_NAMES: dict[str, str] = {
    "sicurezza": "security",
    "situazione sanitaria": "health",
    "requisiti di ingresso": "entry",
    "requisiti d ingresso": "entry",
    "informazioni generali": "general",
    "mobilita": "mobility",
    "primo piano": "highlights",
}

# Rimando esplicito a una sezione della scheda
_NAMED_INTERNAL_REF = re.compile(
    r"sezion\w*\s+(?:di\s+)?(" + "|".join(_SECTION_NAMES) + r")\b(?!\s+aerea)"
)
def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    text = _BR.sub("\n", html)
    text = _BLOCK_END.sub("\n\n", text)
    text = _TAG.sub("", text)
    text = unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = "\n".join("" if _DECORATIVE.match(line) else line for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_links(html: str | None) -> list[tuple[str, str]]:
    """Coppie (testo, url) prese dal grezzo, prima che i tag vengano rimossi."""
    if not html:
        return []
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _ANCHOR.finditer(html):
        url = unescape(match.group(1)).strip()
        if not url or url.startswith("#") or url in seen:
            continue
        seen.add(url)
        label = html_to_text(match.group(2)) or url
        links.append((" ".join(label.split()), url))
    return links


def link_kind(url: str) -> LinkKind:
    lowered = url.lower()
    if lowered.startswith("mailto:"):
        return "email"
    if lowered.startswith("tel:"):
        return "phone"
    return "web"


def _fold(text: str) -> str:
    folded = text.lower().replace("à", "a").replace("è", "e").replace("é", "e")
    folded = folded.replace("ì", "i").replace("ò", "o").replace("ù", "u")
    return re.sub(r"[^a-z0-9 ]+", " ", folded)


def _internal_refs(sentence: str) -> list[str]:
    """Sezioni della scheda citate esplicitamente in questa frase.
    """
    folded = re.sub(r"\s+", " ", _fold(sentence))
    found: list[str] = []
    for match in _NAMED_INTERNAL_REF.finditer(folded):
        section = _SECTION_NAMES[match.group(1)]
        if section not in found:
            found.append(section)
    return found


def find_see_also(text: str) -> list[str]:
    """Le sezioni di *questa* scheda che il testo richiama, come riferimenti strutturati.
    """
    return _internal_refs(text) if text else []
