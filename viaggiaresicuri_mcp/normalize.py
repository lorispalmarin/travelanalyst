"""Normalizzazione dei contenuti della fonte.

La fonte serve HTML dentro JSON, con entità non decodificate e i recapiti consolari annidati
in `<a href="mailto:...">`. L'ordine delle operazioni conta: i link vanno estratti dal grezzo
prima di rimuovere i tag, altrimenti si perdono.
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

# Un punto chiude una frase solo se seguito da spazio e da una maiuscola: così restano intatti
# "68.20.27.064", "segramb.tirana@esteri.it", "20.000 THB" e "https://tdac.immigration.go.th/".
# La seconda alternativa copre il refuso della fonte "di questa Scheda.Per ulteriori...".
_SENTENCE_BREAK = re.compile(
    r"(?<=[.!?…])[ \t]+(?=[A-ZÀ-Þ«\"“'(])|(?<=[a-zà-ÿ]\.)(?=[A-ZÀ-Þ][a-zà-ÿ])"
)

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

# Rimando esplicito a una sezione della scheda: "consultare la Sezione «Sicurezza»".
# "aerea" è escluso di proposito: "Sezione Sicurezza aerea" è l'approfondimento curato con ENAC,
# una risorsa esterna, non la sezione Sicurezza di questa scheda.
_NAMED_INTERNAL_REF = re.compile(
    r"sezion\w*\s+(?:di\s+)?(" + "|".join(_SECTION_NAMES) + r")\b(?!\s+aerea)"
)
# Rimando generico senza nome di sezione: "consultare le varie Sezioni di questa Scheda".
_GENERIC_SELF_REF = re.compile(
    r"(consult\w+|ved(?:i|ere|asi)|rimand\w+)[^.]{0,80}?"
    r"(le varie sezion\w+|di questa scheda|della presente scheda)"
)

# Parole di servizio delle formule di rinvio: quello che resta dopo averle tolte è contenuto
# vero, e se c'è la frase non va rimossa.
_FILLER = re.compile(
    r"\b(?:consult\w+|ved(?:i|ere|asi)|rimand\w+|invita\w*|prega\w*|raccomanda\w*|consiglia\w*|"
    r"si|per|maggiori|ulteriori|altre|informazioni|dettagli|indicazioni|approfondi\w*|piu|"
    r"attentamente|relativ\w+|merito|riguardo|questa|questo|scheda|sezion\w*|della|delle|dello|"
    r"del|dei|degli|di|da|a|ad|in|e|ed|il|lo|la|le|i|gli|un|una|uno|che|con|su|nonche)\b"
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

    Vuoto per i rinvii a risorse esterne (sito dell'Ambasciata, ENAC, approfondimenti del sito):
    quelli sono contenuto utile all'operatore e non vanno toccati.
    """
    folded = re.sub(r"\s+", " ", _fold(sentence))
    found: list[str] = []
    for match in _NAMED_INTERNAL_REF.finditer(folded):
        section = _SECTION_NAMES[match.group(1)]
        if section not in found:
            found.append(section)
    return found


def _sentence_spans(line: str) -> list[tuple[int, int]]:
    """Intervalli di frase, separatore incluso: rimuoverne uno non tocca il resto del testo."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_BREAK.finditer(line):
        spans.append((start, match.end()))
        start = match.end()
    if start < len(line):
        spans.append((start, len(line)))
    return spans


def split_see_also(text: str) -> tuple[str, list[str]]:
    """Toglie i rimandi interni alla scheda e li restituisce come riferimenti strutturati.

    Sono istruzioni per chi naviga il sito ("consultare la Sezione Sicurezza di questa Scheda"):
    in chat sono rumore, e quando un nodo di primo piano viene servito come fallback dentro il
    tool sicurezza il rimando punterebbe alla sezione appena richiesta.

    Vengono rimossi solo i rinvii a sezioni di *questa* scheda. Un rinvio a una risorsa esterna
    resta nel testo: è quanto la fonte ha da dire su quel punto, e toglierlo trasformerebbe un
    nodo compilato in un falso "non pubblicato".
    """
    if not text:
        return "", []

    refs: list[str] = []
    output_lines: list[str] = []

    for line in text.split("\n"):
        if not line.strip():
            output_lines.append(line)
            continue

        tenuti: list[str] = []

        for start, end in _sentence_spans(line):
            frase = line[start:end]
            folded = _fold(frase)
            sezioni = _internal_refs(frase)

            if sezioni:
                for sezione in sezioni:
                    if sezione not in refs:
                        refs.append(sezione)

            if not sezioni and not _GENERIC_SELF_REF.search(folded):
                tenuti.append(frase)
                continue

            # La frase contiene un rimando: si toglie solo se non contiene altro. Sono i casi
            # come "Per maggiori informazioni, consultare la Sezione Sicurezza di questa Scheda".
            # Se invece porta anche contenuto — "Passaporto oppure CIE: consultare la Sezione
            # Requisiti di Ingresso" — resta, perché è quello che la fonte ha da dire.
            residuo = _NAMED_INTERNAL_REF.sub(" ", folded)
            residuo = re.sub(r"[^a-z0-9]+", "", _FILLER.sub(" ", residuo))
            if len(residuo) >= 10:
                tenuti.append(frase)

        riga = "".join(tenuti).strip()
        if riga:
            output_lines.append(riga)

    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(output_lines)).strip()
    return cleaned, refs
